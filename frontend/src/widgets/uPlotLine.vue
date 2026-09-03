<script setup lang="ts">
/**
 * Compact spectrum line chart (uPlot): flux line, error band, dashed continuum, optional velocity
 * axis. Used for inline node previews; the full-size viewer uses PlotlyView.
 */
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

import { axisLabel, fluxRange, type SpectrumSeries, toVelocity } from './spectrumSeries'

const props = withDefaults(
  defineProps<{
    series: SpectrumSeries | null
    height?: number
    showError?: boolean
    showContinuum?: boolean
    /** Rest wavelength for a velocity axis (ignored when the series is already in velocity). */
    velocityWrest?: number | null
    /** Show axes and cursor (thumbnails hide them). */
    axes?: boolean
    /** Explicit x range to display; `null` = full data. */
    xRange?: [number, number] | null
  }>(),
  {
    height: 90,
    showError: true,
    showContinuum: true,
    velocityWrest: null,
    axes: false,
    xRange: null,
  },
)

const emit = defineEmits<{
  /** Visible x range after a user selection (box zoom) or reset (`null`). */
  'view-change': [range: [number, number] | null]
}>()

const container = ref<HTMLDivElement | null>(null)
const chart = shallowRef<uPlot | null>(null)
let observer: ResizeObserver | null = null

const xValues = computed<ArrayLike<number> | null>(() => {
  const s = props.series
  if (!s) return null
  if (props.velocityWrest && s.frame !== 'velocity')
    return toVelocity(s.wave, props.velocityWrest, s.z)
  return s.wave
})

const label = computed(() => {
  const s = props.series
  if (!s) return ''
  if (props.velocityWrest && s.frame !== 'velocity') return 'v (km/s)'
  return axisLabel(s)
})

function toArray(values: ArrayLike<number> | null | undefined): number[] | null {
  if (!values) return null
  return Array.from(values as ArrayLike<number>, (v) => (Number.isFinite(v) ? v : Number.NaN))
}

function buildData(): uPlot.AlignedData | null {
  const s = props.series
  const x = toArray(xValues.value)
  if (!s || !x) return null
  const flux = toArray(s.flux) ?? []
  const data: (number | null)[][] = [x, flux]
  const error = props.showError && s.error ? toArray(s.error) : null
  if (error) {
    data.push(flux.map((f, i) => f + (error[i] ?? 0)))
    data.push(flux.map((f, i) => f - (error[i] ?? 0)))
  }
  const continuum = props.showContinuum && s.continuum ? toArray(s.continuum) : null
  if (continuum) data.push(continuum)
  return data as unknown as uPlot.AlignedData
}

function buildOptions(width: number): uPlot.Options {
  const s = props.series
  const hasError = Boolean(props.showError && s?.error)
  const hasContinuum = Boolean(props.showContinuum && s?.continuum)
  const series: uPlot.Series[] = [
    {},
    { label: 'flux', stroke: '#5B8DEF', width: 1, points: { show: false } },
  ]
  const bands: uPlot.Band[] = []
  if (hasError) {
    series.push(
      { label: '+σ', stroke: 'transparent', points: { show: false } },
      { label: '−σ', stroke: 'transparent', points: { show: false } },
    )
    bands.push({ series: [2, 3], fill: 'rgba(91, 141, 239, 0.18)' })
  }
  if (hasContinuum) {
    series.push({
      label: 'continuum',
      stroke: '#1C9C5A',
      width: 1.5,
      dash: [4, 3],
      points: { show: false },
    })
  }
  const range = s ? fluxRange(s) : [0, 1]
  return {
    width,
    height: props.height,
    cursor: props.axes ? { drag: { x: true, y: false } } : { show: false },
    legend: { show: false },
    select: { show: props.axes, left: 0, top: 0, width: 0, height: 0 },
    scales: {
      x: { time: false, range: props.xRange ? () => props.xRange as [number, number] : undefined },
      y: { range: () => range as [number, number] },
    },
    axes: [
      { show: props.axes, label: props.axes ? label.value : undefined, labelSize: 14, size: 26 },
      { show: props.axes, size: 46 },
    ],
    series,
    bands,
    hooks: {
      setSelect: [
        (u) => {
          if (!props.axes || u.select.width <= 0) return
          const lo = u.posToVal(u.select.left, 'x')
          const hi = u.posToVal(u.select.left + u.select.width, 'x')
          emit('view-change', [Math.min(lo, hi), Math.max(lo, hi)])
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
  const width = Math.max(40, el.clientWidth || 200)
  chart.value = new uPlot(buildOptions(width), data, el)
}

function resize(): void {
  const el = container.value
  if (!el || !chart.value) return
  chart.value.setSize({ width: Math.max(40, el.clientWidth || 200), height: props.height })
}

function resetView(): void {
  emit('view-change', null)
}

onMounted(() => {
  render()
  if (typeof ResizeObserver !== 'undefined' && container.value) {
    observer = new ResizeObserver(() => resize())
    observer.observe(container.value)
  }
})

onBeforeUnmount(() => {
  observer?.disconnect()
  chart.value?.destroy()
  chart.value = null
})

watch(
  () => [
    props.series,
    props.showError,
    props.showContinuum,
    props.velocityWrest,
    props.axes,
    props.xRange,
    props.height,
  ],
  () => render(),
)

defineExpose({ resetView, chart })
</script>

<template>
  <div
    ref="container"
    class="ac-uplot nodrag nowheel w-full select-none"
    :class="{ 'ac-uplot--interactive': axes }"
    :style="{ height: `${height}px` }"
    data-widget="uplot-line"
    :data-points="series?.wave.length ?? 0"
    @dblclick="resetView"
  />
</template>

<style>
.ac-uplot .u-wrap {
  font-family: inherit;
}
.ac-uplot .u-axis {
  font-size: 10px;
  color: var(--muted-foreground);
}
.ac-uplot .u-select {
  background: color-mix(in oklab, var(--ac-selection, #5b8def) 25%, transparent);
}
</style>
