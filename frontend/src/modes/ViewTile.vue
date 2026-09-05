<script setup lang="ts">
/**
 * One pinned view, drawn at whatever size the mode gives it: App's right-hand column, a Wizard
 * step's result panel, a Dashboard tile.
 *
 * The renderer is the one the node's live output picked, falling back to the view's stored
 * `kind` before the node has run (design 8.4). Like `PreviewHost`, the tile asks the server for
 * a payload matching its own width, so a Dashboard tile resized wide gets more points.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Maximize2, SquarePen } from '@lucide/vue'

import type { ViewDoc } from '@/api/types'
import { previewBudget, previewComponent, rendererFor } from '@/previews'
import { useExecutionStore } from '@/stores/execution'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'
import { useLinkedStore } from '@/stores/linked'
import { useWorkflowStore } from '@/stores/workflow'
import { viewRenderer } from './layouts'
import {
  axisName,
  fractionOf,
  rowsInRange,
  upstreamNodes,
  valueAt,
  valuesOfRows,
  xDomain,
} from './linked'

const props = withDefaults(
  defineProps<{
    view: ViewDoc
    label?: string
    /** Body height in pixels; `null` lets the tile fill its container. */
    height?: number | null
    compact?: boolean
    /** Take part in the dashboard's linked selection (design 8.4). */
    linked?: boolean
  }>(),
  { label: '', height: null, compact: false, linked: false },
)

const { t } = useI18n()
const execution = useExecutionStore()
const schema = useNodesSchemaStore()
const session = useSessionStore()
const workflow = useWorkflowStore()
const ui = useUiStore()
const links = useLinkedStore()

const host = ref<HTMLDivElement | null>(null)
const width = ref(360)
let observer: ResizeObserver | null = null
let debounce: ReturnType<typeof setTimeout> | null = null
let requested: number | null = null

const exec = computed(() => execution.node(props.view.node))
const entry = computed(() => exec.value.summaries[props.view.port])
const node = computed(() => workflow.rootNodes[props.view.node])
const spec = computed(() => workflow.specFor(node.value))
const typeId = computed(
  () =>
    entry.value?.typeId ??
    spec.value?.outputs.find((port) => port.name === props.view.port)?.type ??
    'astro.Any',
)
const live = computed(() =>
  entry.value
    ? rendererFor(spec.value, schema.typeById[entry.value.typeId], entry.value.summary)
    : null,
)
const renderer = computed(() => viewRenderer(props.view, live.value))
const title = computed(
  () => props.label || node.value?.title || spec.value?.name || props.view.node,
)
const progress = computed(() => exec.value.progress)

/**
 * Ask the server for this port's summary. A node that finished *before* the page opened is only
 * described by the status snapshot, which carries states but no summaries — so a tile with no
 * cached entry always asks, and one that has an entry only re-asks when its width buys it more
 * points.
 */
function scheduleRequest(): void {
  if (debounce !== null) clearTimeout(debounce)
  debounce = setTimeout(() => {
    debounce = null
    if (exec.value.state !== 'done') return
    const kind = renderer.value
    const budget = kind ? previewBudget(kind, width.value) : null
    if (entry.value && (budget === null || requested === budget)) return
    requested = budget
    session.requestPreview(
      props.view.node,
      props.view.port,
      budget === null ? {} : { n_out: budget },
    )
  }, 100)
}

onMounted(() => {
  if (host.value) width.value = host.value.clientWidth || width.value
  if (typeof ResizeObserver !== 'undefined' && host.value) {
    observer = new ResizeObserver((entries) => {
      const next = Math.round(entries[0]?.contentRect.width ?? width.value)
      if (next && Math.abs(next - width.value) >= 16) {
        width.value = next
        scheduleRequest()
      }
    })
    observer.observe(host.value)
  }
  scheduleRequest()
})

onBeforeUnmount(() => {
  observer?.disconnect()
  if (debounce !== null) clearTimeout(debounce)
})

watch(
  () => [exec.value.state, exec.value.runId],
  () => {
    requested = null
    scheduleRequest()
  },
)

function expand(): void {
  ui.openViewer({ nodeId: props.view.node, port: props.view.port })
}

// --- linked selection ----------------------------------------------------------------------------

const CURVES = new Set(['spectrum-thumb', 'spectrum-stack', 'zfind-curve', 'multispec-thumb'])
const TABLES = new Set(['table-head', 'candidates-table'])

/** The nodes this view is linked through: itself plus everything upstream of it. */
const group = computed(() => upstreamNodes(props.view.node, workflow.doc?.edges ?? {}))
const summary = computed<Record<string, unknown>>(() => entry.value?.summary ?? {})
const isCurve = computed(() => props.linked && !!renderer.value && CURVES.has(renderer.value))
const isTable = computed(() => props.linked && !!renderer.value && TABLES.has(renderer.value))
const domain = computed(() => (isCurve.value ? xDomain(summary.value) : null))
const active = computed(() => (props.linked ? links.selectionFor(group.value) : null))

/** Rows this tile highlights: a linked range mapped onto its own axis, or a row selection. */
const selectedRows = computed<number[]>(() => {
  const selection = active.value
  if (!isTable.value || !selection) return []
  if (selection.kind === 'rows') return selection.rows
  return rowsInRange(summary.value, selection.lo, selection.hi)?.rows ?? []
})

/** The band a curve tile paints, as CSS percentages of its own x domain. */
const band = computed<{ left: string; width: string } | null>(() => {
  const selection = active.value
  const span = domain.value
  if (!selection || !span) return null
  const values = selection.kind === 'range' ? [selection.lo, selection.hi] : selection.values
  if (values.length === 0) return null
  const lo = fractionOf(Math.min(...values), span)
  const hi = fractionOf(Math.max(...values), span)
  if (hi <= lo) return { left: `${lo * 100}%`, width: '2px' }
  return { left: `${lo * 100}%`, width: `${(hi - lo) * 100}%` }
})

const dragFrom = ref<number | null>(null)
const dragTo = ref<number | null>(null)

function fractionAt(event: PointerEvent, element: HTMLElement): number {
  const rect = element.getBoundingClientRect()
  return rect.width > 0 ? Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)) : 0
}

function onPointerDown(event: PointerEvent): void {
  if (!domain.value) return
  const target = event.currentTarget as HTMLElement
  target.setPointerCapture(event.pointerId)
  dragFrom.value = fractionAt(event, target)
  dragTo.value = dragFrom.value
}

function onPointerMove(event: PointerEvent): void {
  if (dragFrom.value === null) return
  dragTo.value = fractionAt(event, event.currentTarget as HTMLElement)
}

function onPointerUp(event: PointerEvent): void {
  const span = domain.value
  const from = dragFrom.value
  dragFrom.value = null
  if (from === null || !span) return
  const to = fractionAt(event, event.currentTarget as HTMLElement)
  dragTo.value = null
  // A click without a drag clears the selection instead of selecting nothing.
  if (Math.abs(to - from) < 0.01) {
    links.clear()
    return
  }
  links.setRange(
    props.view.id,
    group.value,
    axisName(summary.value),
    valueAt(from, span),
    valueAt(to, span),
  )
}

/** A table row click publishes the rows plus their axis values, so curves can mark them. */
function onSelectRows(rows: number[]): void {
  if (rows.length === 0) {
    links.clear()
    return
  }
  links.setRows(
    props.view.id,
    group.value,
    rows,
    valuesOfRows(summary.value, rows),
    rowsInRange(summary.value, -Infinity, Infinity)?.column ?? null,
  )
}

const dragBand = computed<{ left: string; width: string } | null>(() => {
  if (dragFrom.value === null || dragTo.value === null) return null
  const lo = Math.min(dragFrom.value, dragTo.value)
  const hi = Math.max(dragFrom.value, dragTo.value)
  return { left: `${lo * 100}%`, width: `${(hi - lo) * 100}%` }
})
</script>

<template>
  <figure
    class="flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border bg-card"
    :data-testid="`view-tile-${view.id}`"
    :data-state="exec.state"
    :data-renderer="renderer ?? 'none'"
    :data-linked="active ? 'true' : undefined"
    :data-selected-rows="isTable ? selectedRows.length : undefined"
  >
    <figcaption
      class="flex h-7 shrink-0 items-center gap-1 border-b px-2 text-[11px] font-medium"
      :class="compact ? 'h-6' : ''"
    >
      <span class="min-w-0 flex-1 truncate" :title="`${view.node}.${view.port}`">{{ title }}</span>
      <span
        v-if="exec.state === 'running'"
        class="rounded bg-blue-500/15 px-1 text-blue-700 dark:text-blue-400"
        data-testid="view-tile-running"
      >
        {{
          progress?.frac
            ? t('modes.progress', { pct: Math.round(progress.frac * 100) })
            : t('node.state.running')
        }}
      </span>
      <span
        v-else-if="exec.stale"
        class="rounded bg-amber-500/15 px-1 text-amber-700 dark:text-amber-400"
      >
        {{ t('node.state.stale') }}
      </span>
      <button
        v-if="spec?.editor"
        type="button"
        class="inline-flex size-5 items-center justify-center rounded text-muted-foreground hover:text-foreground"
        :aria-label="t('inspector.open_editor')"
        :title="t('inspector.open_editor')"
        :data-testid="`view-editor-${view.id}`"
        @click="ui.openEditor({ nodeId: view.node })"
      >
        <SquarePen class="size-3" />
      </button>
      <button
        type="button"
        class="inline-flex size-5 items-center justify-center rounded text-muted-foreground hover:text-foreground"
        :aria-label="t('preview.expand', { port: view.port })"
        :title="t('preview.expand', { port: view.port })"
        :data-testid="`view-expand-${view.id}`"
        @click="expand"
      >
        <Maximize2 class="size-3" />
      </button>
    </figcaption>

    <!-- A scrollable region needs to be reachable by keyboard, or its content is unreadable
         without a mouse (axe `scrollable-region-focusable`). -->
    <div
      ref="host"
      class="min-h-0 min-w-0 flex-1 overflow-auto p-2 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      tabindex="0"
      :style="height === null ? undefined : { height: `${height}px` }"
    >
      <p v-if="exec.error" class="text-[11px] text-destructive" data-testid="view-tile-error">
        {{ exec.error.message }}
      </p>
      <div v-else-if="entry && renderer" class="relative">
        <component
          :is="previewComponent(renderer)"
          :node-id="view.node"
          :port="view.port"
          :type-id="typeId"
          :summary="entry.summary"
          :width="width"
          :selected-rows="isTable ? selectedRows : undefined"
          @select-rows="onSelectRows"
        />
        <div
          v-if="isCurve && domain"
          class="absolute inset-0 cursor-crosshair"
          :data-testid="`view-select-${view.id}`"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
        >
          <div
            v-if="dragBand ?? band"
            class="pointer-events-none absolute inset-y-0 border-x border-primary/60 bg-primary/15"
            :style="dragBand ?? band ?? undefined"
            :data-testid="`view-band-${view.id}`"
          />
        </div>
      </div>
      <p v-else class="text-[11px] text-muted-foreground">
        {{ exec.state === 'done' ? t('preview.no_output') : t('preview.waiting') }}
      </p>
    </div>
  </figure>
</template>
