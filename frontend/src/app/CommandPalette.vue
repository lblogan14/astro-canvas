<script setup lang="ts">
/**
 * Quick-add palette (`Tab`), also opened when a connection is dropped on empty canvas: then the
 * list is filtered to node types accepting the dragged output and the pick is wired up.
 */
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Fuse from 'fuse.js'

import type { NodeSpec } from '@/api/types'
import { useCanvasAdapter } from '@/canvas/CanvasAdapter'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useSelectionStore } from '@/stores/selection'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'

const { t } = useI18n()
const ui = useUiStore()
const schema = useNodesSchemaStore()
const workflow = useWorkflowStore()
const selection = useSelectionStore()
const canvas = useCanvasAdapter()

const query = ref('')
const active = ref(0)
const input = ref<HTMLInputElement | null>(null)

const candidates = computed<NodeSpec[]>(() => {
  const type = ui.paletteContext?.sourceType
  return type ? schema.acceptingInput(type) : schema.specs
})

const fuse = computed(
  () =>
    new Fuse(candidates.value, {
      keys: ['name', 'id', 'category', 'description'],
      threshold: 0.4,
      ignoreLocation: true,
    }),
)

const results = computed<NodeSpec[]>(() => {
  const q = query.value.trim()
  if (!q) return candidates.value.slice(0, 30)
  return fuse.value.search(q, { limit: 30 }).map((r) => r.item)
})

watch(
  () => ui.paletteOpen,
  (open) => {
    if (open) {
      query.value = ''
      active.value = 0
      void nextTick(() => input.value?.focus())
    }
  },
)
watch(results, () => {
  active.value = 0
})

function pick(spec: NodeSpec): void {
  if (!workflow.isOpen) return
  const context = ui.paletteContext
  const at = context ? canvas.value?.screenToFlow(context.at) : canvas.value?.viewportCenter()
  const pos: [number, number] = [
    Math.round((at?.x ?? 0) - (context ? 0 : 120)),
    Math.round((at?.y ?? 0) - 16),
  ]
  const id = workflow.transaction('command.add_node', () => {
    const nodeId = workflow.addNode(spec, pos)
    if (context?.sourceType) {
      const port =
        spec.inputs.find((p) => schema.compatible(context.sourceType as string, p.type))?.name ??
        spec.params.find(
          (p) => p.linkable && schema.compatible(context.sourceType as string, p.link_type),
        )?.name
      if (port) {
        workflow.connect({
          source: context.sourceNodeId,
          sourcePort: context.sourcePort,
          target: nodeId,
          targetPort: port,
        })
      }
    }
    return nodeId
  })
  selection.set([id])
  ui.closePalette()
  canvas.value?.focus()
}

function onKeyDown(event: KeyboardEvent): void {
  if (event.key === 'ArrowDown') {
    active.value = Math.min(results.value.length - 1, active.value + 1)
    event.preventDefault()
  } else if (event.key === 'ArrowUp') {
    active.value = Math.max(0, active.value - 1)
    event.preventDefault()
  } else if (event.key === 'Enter') {
    const spec = results.value[active.value]
    if (spec) pick(spec)
    event.preventDefault()
  } else if (event.key === 'Escape' || event.key === 'Tab') {
    ui.closePalette()
    event.preventDefault()
  }
}
</script>

<template>
  <div
    v-if="ui.paletteOpen"
    class="absolute inset-0 z-40 flex items-start justify-center bg-background/40 pt-24"
    @mousedown.self="ui.closePalette()"
  >
    <div
      class="w-[28rem] overflow-hidden rounded-lg border bg-popover text-popover-foreground shadow-lg"
      role="dialog"
      aria-modal="true"
      :aria-label="t('palette.title')"
      data-testid="palette"
      @keydown="onKeyDown"
    >
      <input
        ref="input"
        v-model="query"
        class="h-10 w-full border-b bg-transparent px-3 text-sm focus:outline-none"
        :placeholder="
          ui.paletteContext ? t('palette.connect_placeholder') : t('palette.placeholder')
        "
        :aria-label="t('palette.title')"
        role="combobox"
        aria-autocomplete="list"
        aria-controls="palette-results"
        :aria-expanded="true"
        :aria-activedescendant="results[active] ? `palette-item-${active}` : undefined"
      />
      <ul id="palette-results" class="max-h-80 overflow-auto p-1" role="listbox">
        <li
          v-for="(spec, i) in results"
          :id="`palette-item-${i}`"
          :key="spec.id"
          role="option"
          class="flex cursor-default items-center gap-2 rounded-md px-2 py-1.5 text-xs"
          :class="{ 'bg-accent text-accent-foreground': i === active }"
          :aria-selected="i === active"
          :data-node-type="spec.id"
          @mousemove="active = i"
          @click="pick(spec)"
        >
          <span class="min-w-0 flex-1">
            <span class="block truncate font-medium">{{ spec.name }}</span>
            <span class="block truncate text-[10px] text-muted-foreground"
              >{{ spec.category }} · {{ spec.id }}</span
            >
          </span>
          <span class="rounded bg-muted px-1 text-[10px] text-muted-foreground">{{
            spec.pack
          }}</span>
        </li>
        <li v-if="!results.length" class="px-2 py-3 text-center text-xs text-muted-foreground">
          {{ t('palette.no_results') }}
        </li>
      </ul>
      <p class="border-t px-3 py-1.5 text-[10px] text-muted-foreground">{{ t('palette.hint') }}</p>
    </div>
  </div>
</template>
