<script setup lang="ts">
/**
 * One panel of the multi-spectrum viewer: a uPlot line for the flux (canvas, so ten panels of
 * 1e5 decimated points still pan at interactive frame rates), an error band, vertical line
 * markers with labels drawn in uPlot's `draw` hook, and an optional model overlay for a quick
 * fit. The x scale is driven from the outside so every panel shares it.
 *
 * Emits data coordinates: `hover` on every cursor move, `click` where the user clicks, `select`
 * after a horizontal drag.
 */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

import { useUiStore } from '@/stores/ui'
import { fluxRange, type SpectrumSeries } from '@/widgets/spectrumSeries'

export interface PanelMarker {
  x: number
  label?: string
  color?: string
  dash?: boolean
}

const props = withDefaults(
  defineProps<{
    series: SpectrumSeries | null
    markers?: PanelMarker[]
    /** Model curve of a quick fit, drawn over the flux. */
    model?: { x: number[]; y: number[] } | null
    /** Shared x range; `null` uses the panel's own extent. */
    xRange?: [number, number] | null
    /** Explicit y range; `null` autoscales to the visible x window. */
    yRange?: [number, number] | null
    height?: number
    showError?: boolean
    showLabels?: boolean
    /** Only the bottom panel of a stack draws the wavelength axis. */
    showAxis?: boolean
    label?: string
  }>(),
  {
    markers: () => [],
    model: null,
    xRange: null,
    yRange: null,
    height: 130,
    showError: true,
    showLabels: true,
    showAxis: false,
    label: '',
  },
)

const emit = defineEmits<{
  hover: [x: number, y: number]
  click: [x: number, y: number]
  select: [lo: number, hi: number]
}>()

const ui = useUiStore()
const container = ref<HTMLDivElement | null>(null)
const chart = shallowRef<uPlot | null>(null)
let observer: ResizeObserver | null = null
/** Last cursor position in data coordinates (the `g`/`c` keys read it). */
const cursor = { x: Number.NaN, y: Number.NaN }

function toArray(values: ArrayLike<number> | null | undefined): number[] {
  if (!values) return []
  return Array.from(values as ArrayLike<number>, (v) => (Number.isFinite(v) ? v : Number.NaN))
}

/** Flux extent inside the visible x window, so a zoomed panel is not flattened by outliers. */
function visibleRange(): [number, number] {
  const s = props.series
  if (!s) return [0, 1]
  if (props.yRange) return props.yRange
  const window = props.xRange
  if (!window) return fluxRange(s)
  let lo = Number.POSITIVE_INFINITY
  let hi = Number.NEGATIVE_INFINITY
  for (let i = 0; i < s.wave.length; i += 1) {
    const w = s.wave[i]
    const f = s.flux[i]
    if (w === undefined || f === undefined || !Number.isFinite(f)) continue
    if (w < window[0] || w > window[1]) continue
    if (f < lo) lo = f
    if (f > hi) hi = f
  }
  if (!(lo <= hi)) return fluxRange(s)
  if (lo === hi) return [lo - 1, hi + 1]
  const pad = (hi - lo) * 0.08
  return [lo - pad, hi + pad]
}

function buildData(): uPlot.AlignedData | null {
  const s = props.series
  if (!s) return null
  const x = toArray(s.wave)
  const flux = toArray(s.flux)
  const data: number[][] = [x, flux]
  if (props.showError && s.error) {
    const error = toArray(s.error)
    data.push(flux.map((f, i) => f + (error[i] ?? 0)))
    data.push(flux.map((f, i) => f - (error[i] ?? 0)))
  }
  return data as unknown as uPlot.AlignedData
}

function drawMarkers(u: uPlot): void {
  const ctx = u.ctx
  const top = u.bbox.top
  const height = u.bbox.height
  ctx.save()
  ctx.beginPath()
  ctx.rect(u.bbox.left, top, u.bbox.width, height)
  ctx.clip()
  ctx.font = `10px ${getComputedStyle(u.root).fontFamily || 'sans-serif'}`
  ctx.textAlign = 'left'
  ctx.textBaseline = 'top'
  for (const marker of props.markers) {
    const left = u.valToPos(marker.x, 'x', true)
    if (left < u.bbox.left || left > u.bbox.left + u.bbox.width) continue
    ctx.strokeStyle = marker.color ?? '#8B5CF6'
    ctx.lineWidth = 1
    ctx.setLineDash(marker.dash ? [4, 3] : [])
    ctx.beginPath()
    ctx.moveTo(left, top)
    ctx.lineTo(left, top + height)
    ctx.stroke()
    if (props.showLabels && marker.label) {
      ctx.save()
      ctx.fillStyle = marker.color ?? '#8B5CF6'
      ctx.translate(left + 2, top + 2)
      ctx.rotate(Math.PI / 2)
      ctx.fillText(marker.label, 0, 0)
      ctx.restore()
    }
  }
  const model = props.model
  if (model && model.x.length > 1) {
    ctx.setLineDash([])
    ctx.strokeStyle = '#F59E0B'
    ctx.lineWidth = 1.5
    ctx.beginPath()
    for (let i = 0; i < model.x.length; i += 1) {
      const px = u.valToPos(model.x[i] ?? 0, 'x', true)
      const py = u.valToPos(model.y[i] ?? 0, 'y', true)
      if (i === 0) ctx.moveTo(px, py)
      else ctx.lineTo(px, py)
    }
    ctx.stroke()
  }
  ctx.restore()
}

function buildOptions(width: number): uPlot.Options {
  const s = props.series
  const dark = ui.isDark
  const hasError = Boolean(props.showError && s?.error)
  const series: uPlot.Series[] = [
    {},
    { label: 'flux', stroke: '#5B8DEF', width: 1, points: { show: false } },
  ]
  const bands: uPlot.Band[] = []
  if (hasError) {
    series.push(
      { label: 'hi', stroke: 'transparent', points: { show: false } },
      { label: 'lo', stroke: 'transparent', points: { show: false } },
    )
    bands.push({ series: [2, 3], fill: 'rgba(91, 141, 239, 0.18)' })
  }
  const range = visibleRange()
  const window = props.xRange
  return {
    width,
    height: props.height,
    cursor: { drag: { x: true, y: false }, y: false },
    legend: { show: false },
    select: { show: true, left: 0, top: 0, width: 0, height: 0 },
    scales: {
      x: { time: false, range: window ? () => [...window] as [number, number] : undefined },
      y: { range: () => range },
    },
    axes: [
      { show: props.showAxis, size: props.showAxis ? 28 : 0, stroke: dark ? '#9ca3af' : '#4b5563' },
      { size: 52, stroke: dark ? '#9ca3af' : '#4b5563' },
    ],
    series,
    bands,
    hooks: {
      draw: [drawMarkers],
      setCursor: [
        (u) => {
          const { left, top } = u.cursor
          if (left === undefined || top === undefined || left < 0 || top < 0) return
          cursor.x = u.posToVal(left, 'x')
          cursor.y = u.posToVal(top, 'y')
          emit('hover', cursor.x, cursor.y)
        },
      ],
      setSelect: [
        (u) => {
          if (u.select.width <= 2) return
          const lo = u.posToVal(u.select.left, 'x')
          const hi = u.posToVal(u.select.left + u.select.width, 'x')
          emit('select', Math.min(lo, hi), Math.max(lo, hi))
          u.setSelect({ left: 0, top: 0, width: 0, height: 0 }, false)
        },
      ],
    },
  }
}

function render(): void {
  const el = container.value
  if (!el) return
  const data = buildData()
  chart.value?.destroy()
  chart.value = null
  if (!data) return
  const width = Math.max(80, el.clientWidth || 480)
  chart.value = new uPlot(buildOptions(width), data, el)
}

function onClick(): void {
  if (Number.isFinite(cursor.x)) emit('click', cursor.x, cursor.y)
}

onMounted(() => {
  render()
  if (typeof ResizeObserver !== 'undefined' && container.value) {
    observer = new ResizeObserver(() => {
      const el = container.value
      if (el && chart.value) {
        chart.value.setSize({ width: Math.max(80, el.clientWidth || 480), height: props.height })
      }
    })
    observer.observe(container.value)
  }
})

onBeforeUnmount(() => {
  observer?.disconnect()
  chart.value?.destroy()
  chart.value = null
})

// uPlot has no reactive API: rebuild on data changes, redraw on marker/overlay changes.
watch(
  () => [props.series, props.showError, props.showAxis, props.height, ui.isDark],
  () => render(),
)
watch(
  () => [props.markers, props.model, props.xRange, props.yRange, props.showLabels],
  () => {
    const u = chart.value
    if (!u) return
    u.setScale('y', { min: visibleRange()[0], max: visibleRange()[1] })
    if (props.xRange) u.setScale('x', { min: props.xRange[0], max: props.xRange[1] })
    u.redraw()
  },
  { deep: true },
)
</script>

<template>
  <div
    class="ac-multispec-panel relative w-full select-none"
    data-testid="multispec-panel"
    :data-label="label"
    :data-markers="markers.length"
    @click="onClick"
  >
    <span
      v-if="label"
      class="pointer-events-none absolute top-0.5 right-1 z-10 rounded bg-background/70 px-1 text-[10px] text-muted-foreground"
    >
      {{ label }}
    </span>
    <div ref="container" class="w-full" :style="{ height: `${height}px` }" />
  </div>
</template>

<style>
.ac-multispec-panel .u-axis {
  font-size: 10px;
}
.ac-multispec-panel .u-select {
  background: color-mix(in oklab, #f59e0b 25%, transparent);
}
</style>
