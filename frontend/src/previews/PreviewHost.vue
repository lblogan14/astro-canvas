<script setup lang="ts">
/**
 * Fills a node's preview slot: one renderer per output port (from the registry), an Expand button
 * for outputs that have a full-size view, and viewport-driven `preview.request`s (100 ms debounce
 * on width changes, as plotly-resampler does) so thumbnails never carry more points than pixels.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Maximize2 } from '@lucide/vue'

import type { NodeSpec } from '@/api/types'
import type { NodeExecution } from '@/stores/execution'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'
import {
  EXPANDABLE,
  type PreviewId,
  previewBudget,
  previewComponent,
  rendererFor,
} from './registry'

const props = defineProps<{
  nodeId: string
  spec: NodeSpec | undefined
  exec: NodeExecution
}>()

const { t } = useI18n()
const schema = useNodesSchemaStore()
const session = useSessionStore()
const ui = useUiStore()
const host = ref<HTMLDivElement | null>(null)
const width = ref(220)
let observer: ResizeObserver | null = null
let debounce: ReturnType<typeof setTimeout> | null = null
const requested = new Map<string, number>()

interface Slot {
  port: string
  typeId: string
  renderer: PreviewId
  summary: Record<string, unknown>
  expandable: boolean
}

const slots = computed<Slot[]>(() => {
  const out: Slot[] = []
  const ports = props.spec?.outputs ?? []
  for (const port of ports) {
    const entry = props.exec.summaries[port.name]
    if (!entry) continue
    const typeSpec = schema.typeById[entry.typeId]
    const renderer = rendererFor(props.spec, typeSpec, entry.summary)
    out.push({
      port: port.name,
      typeId: entry.typeId,
      renderer,
      summary: entry.summary,
      expandable: EXPANDABLE.has(renderer),
    })
  }
  const live = props.exec.summaries['$preview']
  if (live) {
    out.push({
      port: '$preview',
      typeId: live.typeId,
      renderer: rendererFor(undefined, undefined, live.summary),
      summary: live.summary,
      expandable: false,
    })
  }
  return out
})

const failed = computed(
  () =>
    slots.value.find((s) => typeof s.summary['error'] === 'string')?.summary['error'] as
      string | undefined,
)

/** Ask the server for a slice matching the current width (only for budgeted renderers). */
function scheduleRequests(): void {
  if (debounce !== null) clearTimeout(debounce)
  debounce = setTimeout(() => {
    debounce = null
    if (props.exec.state !== 'done') return
    for (const slot of slots.value) {
      if (slot.port === '$preview') continue
      const budget = previewBudget(slot.renderer, width.value)
      if (budget === null) continue
      if (requested.get(slot.port) === budget) continue
      // Spectra: skip when the summary already fits the budget; tiles: skip when at full size.
      const points = Array.isArray(slot.summary['wave']) ? slot.summary['wave'].length : null
      const n = typeof slot.summary['n'] === 'number' ? slot.summary['n'] : null
      if (points !== null && n !== null && points >= Math.min(n, budget)) {
        requested.set(slot.port, budget)
        continue
      }
      requested.set(slot.port, budget)
      session.requestPreview(props.nodeId, slot.port, { n_out: budget })
    }
  }, 100)
}

onMounted(() => {
  if (host.value) width.value = host.value.clientWidth || width.value
  if (typeof ResizeObserver !== 'undefined' && host.value) {
    observer = new ResizeObserver((entries) => {
      const next = Math.round(entries[0]?.contentRect.width ?? width.value)
      if (next && Math.abs(next - width.value) >= 8) {
        width.value = next
        scheduleRequests()
      }
    })
    observer.observe(host.value)
  }
  scheduleRequests()
})

onBeforeUnmount(() => {
  observer?.disconnect()
  if (debounce !== null) clearTimeout(debounce)
})

// A fresh run invalidates what was requested before.
watch(
  () => props.exec.runId,
  () => requested.clear(),
)
watch(
  () => props.exec.state,
  (state) => {
    if (state === 'done') scheduleRequests()
  },
)

function expand(port: string): void {
  ui.openViewer({ nodeId: props.nodeId, port })
}
</script>

<template>
  <div ref="host" class="min-w-0" data-testid="preview-host" :data-preview-count="slots.length">
    <template v-if="slots.length">
      <div
        v-for="slot in slots"
        :key="slot.port"
        class="relative"
        :data-preview-port="slot.port"
        :data-preview-kind="slot.renderer"
      >
        <component
          :is="previewComponent(slot.renderer)"
          :node-id="nodeId"
          :port="slot.port"
          :type-id="slot.typeId"
          :summary="slot.summary"
          :width="width"
        />
        <button
          v-if="slot.expandable"
          type="button"
          class="nodrag absolute top-0.5 right-0.5 inline-flex size-5 items-center justify-center rounded bg-background/80 text-muted-foreground shadow-sm hover:text-foreground"
          :aria-label="t('preview.expand', { port: slot.port })"
          :title="t('preview.expand', { port: slot.port })"
          data-testid="preview-expand"
          @click.stop="expand(slot.port)"
        >
          <Maximize2 class="size-3" />
        </button>
      </div>
      <p v-if="failed" class="text-[10px] text-destructive">
        {{ t('preview.error_summary', { message: failed }) }}
      </p>
    </template>
    <p v-else class="text-[11px] text-muted-foreground">
      {{ exec.state === 'done' ? t('preview.no_output') : t('preview.waiting') }}
    </p>
  </div>
</template>
