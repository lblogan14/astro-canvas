<script setup lang="ts">
/**
 * Plotly chart for the editors: a step line (flux) with optional error and overlay traces,
 * shaded bands (masks), vertical markers (transitions), and two draggable range handles.
 * Horizontal drag-select emits `select`, a click emits `click` with the x position, dragging a
 * handle emits `range-change`. Uses the shared Plotly pool like `PlotlyView`.
 */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { useUiStore } from '@/stores/ui'
import {
  acquirePlotly,
  loadPlotly,
  nextPlotlyId,
  releasePlotly,
  touchPlotly,
} from '@/widgets/plotlyPool'

export interface PlotBand {
  lo: number
  hi: number
  color?: string
}

export interface PlotMarker {
  x: number
  label?: string
  color?: string
  dash?: 'solid' | 'dot' | 'dash'
}

export interface PlotOverlay {
  x: ArrayLike<number>
  y: ArrayLike<number>
  name: string
  color?: string
  dash?: 'solid' | 'dot' | 'dash'
}

const props = withDefaults(
  defineProps<{
    x: ArrayLike<number> | null
    y: ArrayLike<number> | null
    error?: ArrayLike<number> | null
    overlays?: PlotOverlay[]
    bands?: PlotBand[]
    markers?: PlotMarker[]
    /** Two draggable handles; `null` hides them. */
    range?: [number, number] | null
    xRange?: [number, number] | null
    yRange?: [number, number] | null
    xLabel?: string
    yLabel?: string
    dragmode?: 'select' | 'zoom' | 'pan'
    step?: boolean
  }>(),
  {
    error: null,
    overlays: () => [],
    bands: () => [],
    markers: () => [],
    range: null,
    xRange: null,
    yRange: null,
    xLabel: '',
    yLabel: '',
    dragmode: 'select',
    step: true,
  },
)

const emit = defineEmits<{
  select: [lo: number, hi: number]
  click: [x: number]
  'range-change': [lo: number, hi: number]
  'view-change': [range: [number, number] | null]
  ready: []
}>()

const { t } = useI18n()
const ui = useUiStore()
const host = ref<HTMLDivElement | null>(null)
const loading = ref(true)
const loadError = ref<string | null>(null)
const id = nextPlotlyId()
type PlotlyModule = Awaited<ReturnType<typeof loadPlotly>>
const plotly = shallowRef<PlotlyModule | null>(null)
let drawn = false
let observer: ResizeObserver | null = null

const toList = (values: ArrayLike<number>): number[] => Array.from(values)
const HANDLE_COUNT = 2

function traces(): Record<string, unknown>[] {
  if (!props.x || !props.y) return []
  const x = toList(props.x)
  const out: Record<string, unknown>[] = [
    {
      type: 'scattergl',
      mode: 'lines',
      name: t('widgets.flux'),
      x,
      y: toList(props.y),
      line: { width: 1, color: '#5B8DEF', shape: props.step ? 'hv' : 'linear' },
    },
  ]
  if (props.error) {
    out.push({
      type: 'scattergl',
      mode: 'lines',
      name: t('widgets.error'),
      x,
      y: toList(props.error),
      line: { width: 1, color: '#D64545', shape: props.step ? 'hv' : 'linear' },
    })
  }
  for (const overlay of props.overlays) {
    out.push({
      type: 'scattergl',
      mode: 'lines',
      name: overlay.name,
      x: toList(overlay.x),
      y: toList(overlay.y),
      line: { width: 1.5, color: overlay.color ?? '#1C9C5A', dash: overlay.dash ?? 'dash' },
    })
  }
  return out
}

function shapes(): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = []
  // Range handles come first so their indices in relayout events are stable (0 and 1).
  if (props.range) {
    for (const x of props.range) {
      out.push({
        type: 'line',
        xref: 'x',
        yref: 'paper',
        x0: x,
        x1: x,
        y0: 0,
        y1: 1,
        editable: true,
        line: { color: '#F59E0B', width: 2 },
      })
    }
  }
  for (const band of props.bands) {
    out.push({
      type: 'rect',
      xref: 'x',
      yref: 'paper',
      x0: band.lo,
      x1: band.hi,
      y0: 0,
      y1: 1,
      fillcolor: band.color ?? 'rgba(148, 163, 184, 0.35)',
      line: { width: 0 },
      layer: 'below',
      editable: false,
    })
  }
  for (const marker of props.markers) {
    out.push({
      type: 'line',
      xref: 'x',
      yref: 'paper',
      x0: marker.x,
      x1: marker.x,
      y0: 0,
      y1: 1,
      line: { color: marker.color ?? '#8B5CF6', width: 1, dash: marker.dash ?? 'dot' },
      editable: false,
    })
  }
  return out
}

function annotations(): Record<string, unknown>[] {
  return props.markers
    .filter((m) => m.label)
    .map((m) => ({
      x: m.x,
      y: 1,
      xref: 'x',
      yref: 'paper',
      text: m.label,
      showarrow: false,
      yanchor: 'bottom',
      font: { size: 10, color: m.color ?? '#8B5CF6' },
    }))
}

function layout(): Record<string, unknown> {
  const dark = ui.isDark
  const fg = dark ? '#e5e7eb' : '#1f2937'
  const grid = dark ? '#374151' : '#e5e7eb'
  const xaxis: Record<string, unknown> = { title: { text: props.xLabel }, gridcolor: grid }
  const yaxis: Record<string, unknown> = { title: { text: props.yLabel }, gridcolor: grid }
  if (props.xRange) xaxis['range'] = [...props.xRange]
  if (props.yRange) yaxis['range'] = [...props.yRange]
  return {
    xaxis,
    yaxis,
    shapes: shapes(),
    annotations: annotations(),
    autosize: true,
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: fg, size: 12 },
    margin: { l: 60, r: 20, t: 24, b: 50 },
    dragmode: props.dragmode,
    selectdirection: 'h',
    legend: { orientation: 'h', y: 1.06 },
    uirevision: 'keep',
  }
}

async function draw(): Promise<void> {
  const el = host.value
  if (!el) return
  try {
    const mod = plotly.value ?? (await loadPlotly())
    plotly.value = mod
    acquirePlotly(id, () => undefined)
    await mod.react(el, traces() as never, layout() as never, {
      responsive: true,
      displaylogo: false,
      scrollZoom: true,
      edits: { shapePosition: true },
      modeBarButtonsToRemove: ['lasso2d'],
    })
    if (!drawn) {
      drawn = true
      const target = el as unknown as {
        on: (event: string, cb: (ev: Record<string, unknown>) => void) => void
      }
      target.on('plotly_selected', onSelected)
      target.on('plotly_click', onClick)
      target.on('plotly_relayout', onRelayout)
    }
    loading.value = false
    loadError.value = null
    emit('ready')
  } catch (err) {
    loading.value = false
    loadError.value = err instanceof Error ? err.message : String(err)
  }
}

function onSelected(event: Record<string, unknown>): void {
  touchPlotly(id)
  const range = (event as { range?: { x?: [number, number] } } | undefined)?.range?.x
  if (!range) return
  const [a, b] = range
  if (typeof a === 'number' && typeof b === 'number' && a !== b) {
    emit('select', Math.min(a, b), Math.max(a, b))
    // Clear the selection box so the next drag starts fresh.
    if (host.value && plotly.value) {
      void plotly.value.relayout(host.value, { selections: [] } as never)
    }
  }
}

function onClick(event: Record<string, unknown>): void {
  touchPlotly(id)
  const points = (event as { points?: { x?: unknown }[] }).points
  const x = points?.[0]?.x
  if (typeof x === 'number') emit('click', x)
}

function onRelayout(event: Record<string, unknown>): void {
  touchPlotly(id)
  if (props.range) {
    const lo = event['shapes[0].x0'] ?? event['shapes[0].x1']
    const hi = event['shapes[1].x0'] ?? event['shapes[1].x1']
    if (typeof lo === 'number' || typeof hi === 'number') {
      const a = typeof lo === 'number' ? lo : props.range[0]
      const b = typeof hi === 'number' ? hi : props.range[1]
      emit('range-change', Math.min(a, b), Math.max(a, b))
      return
    }
    for (let i = HANDLE_COUNT; i < HANDLE_COUNT + props.bands.length; i += 1) {
      if (`shapes[${i}].x0` in event) return
    }
  }
  if (event['xaxis.autorange'] === true) {
    emit('view-change', null)
    return
  }
  const lo = event['xaxis.range[0]']
  const hi = event['xaxis.range[1]']
  if (typeof lo === 'number' && typeof hi === 'number') {
    emit('view-change', [Math.min(lo, hi), Math.max(lo, hi)])
  }
}

onMounted(() => {
  void draw()
  if (typeof ResizeObserver !== 'undefined' && host.value) {
    observer = new ResizeObserver(() => {
      if (host.value && plotly.value && drawn) void plotly.value.Plots.resize(host.value)
    })
    observer.observe(host.value)
  }
})

onBeforeUnmount(() => {
  observer?.disconnect()
  releasePlotly(id)
  if (host.value && plotly.value) plotly.value.purge(host.value)
})

watch(
  () => [
    props.x,
    props.y,
    props.error,
    props.overlays,
    props.bands,
    props.markers,
    props.range,
    props.xRange,
    props.yRange,
    props.dragmode,
    ui.isDark,
  ],
  () => void draw(),
  { deep: true },
)
</script>

<template>
  <div class="relative h-full min-h-48 w-full" data-widget="editor-plot">
    <div ref="host" class="h-full w-full" />
    <p
      v-if="loading && !loadError"
      class="pointer-events-none absolute inset-0 flex items-center justify-center text-xs text-muted-foreground"
    >
      {{ t('common.loading') }}
    </p>
    <p v-if="loadError" class="absolute inset-x-0 bottom-0 p-2 text-xs text-destructive">
      {{ loadError }}
    </p>
  </div>
</template>
