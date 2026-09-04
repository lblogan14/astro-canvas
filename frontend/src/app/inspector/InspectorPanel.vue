<script setup lang="ts">
/** Right inspector: the selected node's params (stacked AutoForm), cost, bypass and notes. */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { NodeDoc } from '@/api/types'
import { groupIdOf, isGroupNodeId } from '@/canvas/vueflow/toFlow'
import { AutoForm } from '@/nodes'
import { useExecutionStore } from '@/stores/execution'
import { useSelectionStore } from '@/stores/selection'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'

const { t } = useI18n()
const workflow = useWorkflowStore()
const selection = useSelectionStore()
const execution = useExecutionStore()
const ui = useUiStore()

const primary = computed(() => selection.primaryNodeId)
const nodeId = computed(() =>
  primary.value && !isGroupNodeId(primary.value) ? primary.value : null,
)
const groupId = computed(() =>
  primary.value && isGroupNodeId(primary.value) ? groupIdOf(primary.value) : null,
)
const node = computed(() => (nodeId.value ? workflow.nodes[nodeId.value] : undefined))
const group = computed(() => (groupId.value ? workflow.groups[groupId.value] : undefined))
const spec = computed(() => workflow.specFor(node.value))
/**
 * The star promotes into the open container: the document's `promoted` on the root canvas, the
 * body's own `promoted` inside a subgraph (which is what an instance may then override).
 */
const openSubgraphId = computed(() => workflow.openSubgraphId)
const promotedParams = computed(() => {
  const id = nodeId.value
  if (!id) return []
  const subgraph = openSubgraphId.value
  const source = subgraph ? (workflow.subgraphs[subgraph]?.promoted ?? []) : workflow.promotedList
  return source.filter((entry) => entry.node === id).map((entry) => entry.param)
})

function promote(param: string): void {
  const id = nodeId.value
  if (!id) return
  const subgraph = openSubgraphId.value
  if (subgraph) {
    workflow.promoteSubgraphParam(subgraph, id, param)
    return
  }
  const spec = workflow.specs[workflow.nodes[id]?.type ?? '']?.params.find((p) => p.name === param)
  const on = workflow.togglePromoted(id, param, { label: spec?.label ?? null })
  ui.notify(on ? t('promote.added', { label: spec?.label ?? param }) : t('promote.removed'))
}
const issues = computed(() => (nodeId.value ? execution.issuesFor(nodeId.value) : []))
const exec = computed(() => (nodeId.value ? execution.node(nodeId.value) : null))

const COSTS: { value: NodeDoc['cost'] | 'default'; key: string }[] = [
  { value: 'default', key: 'default' },
  { value: 'cheap', key: 'cheap' },
  { value: 'expensive', key: 'expensive' },
  { value: 'auto', key: 'auto' },
]

function setCost(event: Event): void {
  if (!nodeId.value) return
  const value = (event.target as HTMLSelectElement).value
  workflow.setCost(nodeId.value, value === 'default' ? null : (value as NodeDoc['cost']))
}
</script>

<template>
  <aside
    class="flex h-full flex-col text-xs"
    :aria-label="t('inspector.title')"
    data-testid="inspector"
  >
    <h2 class="border-b px-3 py-2 font-semibold">{{ t('inspector.title') }}</h2>

    <div v-if="node && nodeId" class="min-h-0 flex-1 space-y-3 overflow-auto p-3">
      <div>
        <label
          :for="`insp-title-${nodeId}`"
          class="block text-[10px] font-medium text-muted-foreground uppercase"
        >
          {{ t('inspector.node_title') }}
        </label>
        <input
          :id="`insp-title-${nodeId}`"
          class="mt-1 h-7 w-full rounded-md border bg-background px-2"
          :value="node.title ?? ''"
          :placeholder="spec?.name ?? node.type"
          @change="workflow.setTitle(nodeId, ($event.target as HTMLInputElement).value)"
        />
        <p class="mt-1 truncate font-mono text-[10px] text-muted-foreground" :title="node.type">
          {{ node.type }} · {{ nodeId }}
        </p>
        <p v-if="spec?.description" class="mt-1 text-muted-foreground">{{ spec.description }}</p>
      </div>

      <div v-if="exec" class="flex flex-wrap gap-1 text-[10px]">
        <span class="rounded bg-muted px-1.5 py-0.5">{{ t(`node.state.${exec.state}`) }}</span>
        <span v-if="exec.stale" class="rounded bg-muted px-1.5 py-0.5">{{
          t('node.state.stale')
        }}</span>
        <span v-if="exec.cacheHit" class="rounded bg-muted px-1.5 py-0.5">{{
          t('node.cache_hit')
        }}</span>
        <span v-if="exec.elapsedMs !== null" class="rounded bg-muted px-1.5 py-0.5">
          {{ t('node.elapsed', { ms: Math.round(exec.elapsedMs) }) }}
        </span>
      </div>

      <section v-if="spec">
        <h3 class="mb-1 text-[10px] font-medium text-muted-foreground uppercase">
          {{ t('inspector.params') }}
        </h3>
        <AutoForm
          :params="spec.params"
          :values="node.params ?? {}"
          :linked="node.linked ?? []"
          :issues="issues"
          :id-prefix="`insp-${nodeId}`"
          :disabled="node.disabled"
          show-advanced
          promotable
          :promoted="promotedParams"
          @update="(name, value) => workflow.setParam(nodeId!, name, value)"
          @toggle-link="(name) => workflow.toggleLink(nodeId!, name)"
          @promote="promote"
        />
        <button
          v-if="spec.editor"
          type="button"
          class="mt-2 inline-flex h-7 w-full items-center justify-center rounded-md border px-2 hover:bg-muted"
          data-testid="inspector-editor"
          @click="ui.openEditor({ nodeId: nodeId! })"
        >
          {{ t('inspector.open_editor') }}
        </button>
      </section>

      <section class="grid grid-cols-2 gap-2">
        <label class="flex flex-col gap-1">
          <span class="text-[10px] font-medium text-muted-foreground uppercase">{{
            t('inspector.cost')
          }}</span>
          <select
            class="h-7 rounded-md border bg-background px-1"
            :value="node.cost ?? 'default'"
            @change="setCost"
          >
            <option v-for="cost in COSTS" :key="cost.key" :value="cost.value">
              {{ t(`node.cost.${cost.key}`) }}
            </option>
          </select>
        </label>
        <label class="flex items-end gap-2 pb-1">
          <input
            type="checkbox"
            class="size-4"
            :checked="node.disabled"
            @change="workflow.setDisabled(nodeId, ($event.target as HTMLInputElement).checked)"
          />
          <span>{{ t('inspector.bypass') }}</span>
        </label>
      </section>

      <section>
        <label
          :for="`insp-notes-${nodeId}`"
          class="block text-[10px] font-medium text-muted-foreground uppercase"
        >
          {{ t('inspector.notes') }}
        </label>
        <textarea
          :id="`insp-notes-${nodeId}`"
          class="mt-1 min-h-16 w-full rounded-md border bg-background p-2"
          :value="node.notes"
          :placeholder="t('inspector.notes_placeholder')"
          @input="workflow.setNotes(nodeId, ($event.target as HTMLTextAreaElement).value)"
        />
      </section>

      <section
        v-if="exec?.error"
        class="rounded-md border border-destructive/40 bg-destructive/5 p-2"
      >
        <p class="font-medium text-destructive">{{ exec.error.message }}</p>
        <p v-if="exec.error.hint" class="mt-1 text-muted-foreground">{{ exec.error.hint }}</p>
      </section>
    </div>

    <div v-else-if="group && groupId" class="space-y-3 p-3">
      <label
        :for="`insp-group-${groupId}`"
        class="block text-[10px] font-medium text-muted-foreground uppercase"
      >
        {{ t('inspector.group_title') }}
      </label>
      <input
        :id="`insp-group-${groupId}`"
        class="h-7 w-full rounded-md border bg-background px-2"
        :value="group.title"
        @change="
          workflow.updateGroup(groupId, { title: ($event.target as HTMLInputElement).value })
        "
      />
      <p class="text-muted-foreground">
        {{ t('inspector.group_members', (group.nodes ?? []).length) }}
      </p>
    </div>

    <p v-else class="p-3 text-muted-foreground">{{ t('inspector.empty') }}</p>
  </aside>
</template>
