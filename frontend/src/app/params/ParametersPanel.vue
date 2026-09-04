<script setup lang="ts">
/**
 * Parameters panel (design 8.4, research R2's ComfyUI panel): everything the App, Wizard and
 * Dashboard layouts can show, in the order they will show it.
 *
 * Ordering is a drag (with keyboard equivalents, since a drag handle alone is not reachable) and
 * dropping an item on another group's header moves it there — the same `movePromoted` command, so
 * one undo puts it back. Labels, groups and help text are edited in place; the layouts read them
 * through `resolveItem`, which is why a renamed label needs no layout edit.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDown, ChevronUp, GripVertical, Pencil, Star, Trash2 } from '@lucide/vue'

import type { PromotedDoc } from '@/api/types'
import { UNGROUPED, refOf } from '@/modes/layouts'
import { useSelectionStore } from '@/stores/selection'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'

const { t } = useI18n()
const workflow = useWorkflowStore()
const selection = useSelectionStore()
const ui = useUiStore()

/** Ref of the item whose label/group/help editor is open. */
const editing = ref<string | null>(null)
const dragging = ref<string | null>(null)

const groups = computed(() => workflow.promotedGroups)
const flat = computed(() => workflow.promotedList)

function labelOf(entry: PromotedDoc): string {
  if (entry.label?.trim()) return entry.label
  const node = workflow.rootNodes[entry.node]
  const spec = node ? workflow.specs[node.type] : undefined
  return spec?.params.find((p) => p.name === entry.param)?.label ?? entry.param
}

function helpOf(entry: PromotedDoc): string {
  const help = (entry as Record<string, unknown>)['help']
  return typeof help === 'string' ? help : ''
}

function nodeLabel(nodeId: string): string {
  const node = workflow.rootNodes[nodeId]
  return node?.title ?? (node ? (workflow.specs[node.type]?.name ?? node.type) : nodeId)
}

function indexOf(entry: PromotedDoc): number {
  return flat.value.findIndex((p) => p.node === entry.node && p.param === entry.param)
}

function move(entry: PromotedDoc, delta: number): void {
  const at = indexOf(entry)
  if (at < 0) return
  workflow.movePromoted(entry.node, entry.param, at + delta)
}

function onDrop(target: PromotedDoc): void {
  const source = dragging.value
  dragging.value = null
  if (!source) return
  const from = flat.value.find((p) => refOf(p) === source)
  if (!from || refOf(from) === refOf(target)) return
  workflow.movePromoted(from.node, from.param, indexOf(target), target.group ?? null)
}

/** Dropping on a group header appends the item to that group. */
function onDropGroup(title: string): void {
  const source = dragging.value
  dragging.value = null
  if (!source) return
  const from = flat.value.find((p) => refOf(p) === source)
  if (!from) return
  const members = groups.value.find((g) => g.title === title)?.entries ?? []
  const last = members[members.length - 1]
  const at = last ? indexOf(last) + 1 : flat.value.length
  workflow.movePromoted(from.node, from.param, at, title === UNGROUPED ? null : title)
}

function reveal(nodeId: string): void {
  if (!workflow.rootNodes[nodeId]) return
  workflow.exitSubgraph(0) // layout refs are root refs: leave any open subgraph body
  selection.selectNode(nodeId)
  ui.notify(t('promote.revealed', { node: nodeLabel(nodeId) }))
}
</script>

<template>
  <section
    class="flex h-full flex-col text-xs"
    :aria-label="t('promote.panel_title')"
    data-testid="params-panel"
  >
    <div class="flex items-center justify-between border-b p-2">
      <h2 class="px-1 font-semibold">{{ t('promote.panel_title') }}</h2>
      <span class="text-[10px] text-muted-foreground">
        {{ t('promote.count', flat.length) }}
      </span>
    </div>

    <div class="min-h-0 flex-1 overflow-auto p-2">
      <p v-if="flat.length === 0 && workflow.views.length === 0" class="p-2 text-muted-foreground">
        {{ t('promote.empty') }}
      </p>

      <div v-for="group in groups" :key="group.title" class="mb-3">
        <h3
          class="mb-1 rounded px-1 text-[10px] font-medium tracking-wide text-muted-foreground uppercase"
          :class="dragging ? 'bg-muted/60 outline-1 outline-dashed outline-border' : ''"
          :data-testid="`params-group-${group.title}`"
          @dragover.prevent
          @drop.prevent="onDropGroup(group.title)"
        >
          {{ group.title }}
        </h3>
        <ul class="space-y-1" role="list">
          <li
            v-for="entry in group.entries"
            :key="refOf(entry)"
            class="rounded-md border bg-background"
            :class="dragging === refOf(entry) ? 'opacity-50' : ''"
            :data-testid="`param-item-${refOf(entry)}`"
            draggable="true"
            @dragstart="dragging = refOf(entry)"
            @dragend="dragging = null"
            @dragover.prevent
            @drop.prevent="onDrop(entry)"
          >
            <div class="flex items-center gap-1 px-1 py-1">
              <GripVertical
                class="size-3.5 shrink-0 cursor-grab text-muted-foreground"
                aria-hidden="true"
              />
              <button
                type="button"
                class="min-w-0 flex-1 text-left"
                :title="t('promote.reveal', { node: nodeLabel(entry.node) })"
                @click="reveal(entry.node)"
              >
                <span class="block truncate font-medium">{{ labelOf(entry) }}</span>
                <span class="block truncate font-mono text-[10px] text-muted-foreground">
                  {{ refOf(entry) }}
                </span>
              </button>
              <button
                type="button"
                class="inline-flex size-5 items-center justify-center rounded text-muted-foreground hover:text-foreground disabled:opacity-30"
                :disabled="indexOf(entry) === 0"
                :aria-label="t('promote.move_up', { label: labelOf(entry) })"
                :data-testid="`param-up-${refOf(entry)}`"
                @click="move(entry, -1)"
              >
                <ChevronUp class="size-3.5" />
              </button>
              <button
                type="button"
                class="inline-flex size-5 items-center justify-center rounded text-muted-foreground hover:text-foreground disabled:opacity-30"
                :disabled="indexOf(entry) === flat.length - 1"
                :aria-label="t('promote.move_down', { label: labelOf(entry) })"
                :data-testid="`param-down-${refOf(entry)}`"
                @click="move(entry, 1)"
              >
                <ChevronDown class="size-3.5" />
              </button>
              <button
                type="button"
                class="inline-flex size-5 items-center justify-center rounded text-muted-foreground hover:text-foreground"
                :aria-expanded="editing === refOf(entry)"
                :aria-label="t('promote.edit', { label: labelOf(entry) })"
                :data-testid="`param-edit-${refOf(entry)}`"
                @click="editing = editing === refOf(entry) ? null : refOf(entry)"
              >
                <Pencil class="size-3" />
              </button>
              <button
                type="button"
                class="inline-flex size-5 items-center justify-center rounded text-muted-foreground hover:text-destructive"
                :aria-label="t('promote.remove', { label: labelOf(entry) })"
                :data-testid="`param-remove-${refOf(entry)}`"
                @click="workflow.unpromoteParam(entry.node, entry.param)"
              >
                <Trash2 class="size-3" />
              </button>
            </div>

            <div v-if="editing === refOf(entry)" class="space-y-1 border-t px-2 py-1.5">
              <label class="block">
                <span class="text-[10px] text-muted-foreground">{{ t('promote.label') }}</span>
                <input
                  class="mt-0.5 h-6 w-full rounded border bg-background px-1"
                  :value="entry.label ?? ''"
                  :placeholder="labelOf(entry)"
                  :data-testid="`param-label-${refOf(entry)}`"
                  @input="
                    workflow.updatePromoted(entry.node, entry.param, {
                      label: ($event.target as HTMLInputElement).value || null,
                    })
                  "
                />
              </label>
              <label class="block">
                <span class="text-[10px] text-muted-foreground">{{ t('promote.group') }}</span>
                <input
                  class="mt-0.5 h-6 w-full rounded border bg-background px-1"
                  :value="entry.group ?? ''"
                  :placeholder="UNGROUPED"
                  :data-testid="`param-group-${refOf(entry)}`"
                  @change="
                    workflow.updatePromoted(entry.node, entry.param, {
                      group: ($event.target as HTMLInputElement).value || null,
                    })
                  "
                />
              </label>
              <label class="block">
                <span class="text-[10px] text-muted-foreground">{{ t('promote.help') }}</span>
                <textarea
                  class="mt-0.5 min-h-12 w-full rounded border bg-background p-1"
                  :value="helpOf(entry)"
                  :placeholder="t('promote.help_placeholder')"
                  :data-testid="`param-help-${refOf(entry)}`"
                  @input="
                    workflow.updatePromoted(entry.node, entry.param, {
                      help: ($event.target as HTMLTextAreaElement).value,
                    })
                  "
                />
              </label>
            </div>
          </li>
        </ul>
      </div>

      <div v-if="workflow.views.length" class="mb-3">
        <h3 class="mb-1 px-1 text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
          {{ t('pin.views') }}
        </h3>
        <ul class="space-y-1" role="list">
          <li
            v-for="view in workflow.views"
            :key="view.id"
            class="flex items-center gap-1 rounded-md border bg-background px-1 py-1"
            :data-testid="`view-item-${view.id}`"
          >
            <Star class="size-3 shrink-0 text-amber-500" aria-hidden="true" />
            <button
              type="button"
              class="min-w-0 flex-1 text-left"
              @click="ui.openViewer({ nodeId: view.node, port: view.port })"
            >
              <span class="block truncate font-medium">
                {{ nodeLabel(view.node) }} · {{ view.port }}
              </span>
              <span class="block truncate font-mono text-[10px] text-muted-foreground">
                {{ view.kind ?? t('pin.kind_auto') }}
              </span>
            </button>
            <button
              type="button"
              class="inline-flex size-5 items-center justify-center rounded text-muted-foreground hover:text-destructive"
              :aria-label="t('pin.remove', { port: view.port })"
              :data-testid="`view-remove-${view.id}`"
              @click="workflow.unpinView(view.id)"
            >
              <Trash2 class="size-3" />
            </button>
          </li>
        </ul>
      </div>

      <ul
        v-if="workflow.layoutErrors.length"
        class="space-y-0.5 rounded-md border border-destructive/40 bg-destructive/5 p-2 text-[10px] text-destructive"
        data-testid="layout-errors"
      >
        <li v-for="(issue, index) in workflow.layoutErrors" :key="index">
          {{ issue.layout }}: {{ issue.message }}
        </li>
      </ul>
    </div>

    <p class="border-t p-2 text-[10px] text-muted-foreground">{{ t('promote.hint') }}</p>
  </section>
</template>
