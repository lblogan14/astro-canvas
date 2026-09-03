<script setup lang="ts">
/**
 * Full-size Plotly chart (lazy `plotly.js-dist-min`, WebGL `scattergl` traces). Accepts either
 * a ready Plotly figure (`astro.Figure`) or a spectrum series, and reports x-axis range changes
 * (box zoom, autorange) so the host can request a re-decimated slice from the server.
 */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { useUiStore } from '@/stores/ui'
import { acquirePlotly, loadPlotly, nextPlotlyId, releasePlotly, touchPlotly } from './plotlyPool'
import { axisLabel, type SpectrumSeries, toVelocity } from './spectrumSeries'

export interface PlotlyFigure {
  data: Record<string, unknown>[]
  layout?: Record<string, unknown>
}

const props = withDefaults(
  defineProps<{
    figure?: PlotlyFigure | null
    series?: SpectrumSeries | null
    showError?: boolean
    showContinuum?: boolean
    velocityWrest?: number | null
    title?: string
    /** Keep this x range when re-rendering (after a server re-decimation). */
    xRange?: [number, number] | null
  }>(),
  {
    figure: null,
    series: null,
    showError: true,
    showContinuum: true,
    velocityWrest: null,
    title: '',
    xRange: null,
  },
)

const emit = defineEmits<{
  /** New visible x range (`null` = autorange). */
  relayout: [range: [number, number] | null]
  ready: []
}>()

const { t } = useI18n()
const ui = useUiStore()
const host = ref<HTMLDivElement | null>(null)
const paused = ref(false)
const loading = ref(true)
const error = ref<string | null>(null)
const id = nextPlotlyId()
type PlotlyModule = Awaited<ReturnType<typeof loadPlotly>>
const plotly = shallowRef<PlotlyModule | null>(null)
let drawn = false
let observer: ResizeObserver | null = null

function toList(values: ArrayLike<number>): number[] {
  return Array.from(values as ArrayLike<number>)
}

function seriesFigure(s: SpectrumSeries): PlotlyFigure {
  const velocity = props.velocityWrest && s.frame !== 'velocity'
  const x = velocity
    ? toList(toVelocity(s.wave, props.velocityWrest as number, s.z))
    : toList(s.wave)
  const traces: Record<string, unknown>[] = [
    {
      type: 'scattergl',
      mode: 'lines',
      name: t('widgets.flux'),
      x,
      y: toList(s.flux),
      line: { width: 1, color: '#5B8DEF' },
    },
  ]
  if (props.showError && s.error) {
    traces.push({
      type: 'scattergl',
      mode: 'lines',
      name: t('widgets.error'),
      x,
      y: toList(s.error),
      line: { width: 1, color: '#D64545' },
    })
  }
  if (props.showContinuum && s.continuum) {
    traces.push({
      type: 'scattergl',
      mode: 'lines',
      name: t('widgets.continuum'),
      x,
      y: toList(s.continuum),
      line: { width: 1.5, color: '#1C9C5A', dash: 'dash' },
    })
  }
  return {
    data: traces,
    layout: {
      xaxis: { title: { text: velocity ? 'v (km/s)' : axisLabel(s) } },
      yaxis: { title: { text: s.fluxUnit ? `Flux (${s.fluxUnit})` : 'Flux' } },
    },
  }
}

function themedLayout(layout: Record<string, unknown>): Record<string, unknown> {
  const dark = ui.isDark
  const fg = dark ? '#e5e7eb' : '#1f2937'
  const grid = dark ? '#374151' : '#e5e7eb'
  const xaxis: Record<string, unknown> = {
    ...(layout['xaxis'] as Record<string, unknown> | undefined),
    gridcolor: grid,
  }
  const yaxis: Record<string, unknown> = {
    ...(layout['yaxis'] as Record<string, unknown> | undefined),
    gridcolor: grid,
  }
  if (props.xRange) xaxis['range'] = [...props.xRange]
  return {
    ...layout,
    xaxis,
    yaxis,
    autosize: true,
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: fg, size: 12 },
    margin: { l: 60, r: 20, t: props.title ? 40 : 20, b: 50 },
    dragmode: 'zoom',
    legend: { orientation: 'h', y: 1.02 },
    title: props.title ? { text: props.title } : (layout['title'] ?? undefined),
    uirevision: 'keep',
  }
}

function currentFigure(): PlotlyFigure | null {
  if (props.figure) return props.figure
  if (props.series) return seriesFigure(props.series)
  return null
}

async function draw(): Promise<void> {
  const el = host.value
  if (!el || paused.value) return
  const figure = currentFigure()
  if (!figure) return
  try {
    const mod = plotly.value ?? (await loadPlotly())
    plotly.value = mod
    acquirePlotly(id, pause)
    await mod.react(el, figure.data as never, themedLayout(figure.layout ?? {}) as never, {
      responsive: true,
      displaylogo: false,
      scrollZoom: true,
      modeBarButtonsToRemove: ['lasso2d', 'select2d'],
    })
    if (!drawn) {
      drawn = true
      ;(
        el as unknown as { on: (event: string, cb: (ev: Record<string, unknown>) => void) => void }
      ).on('plotly_relayout', onRelayout)
      ;(el as unknown as { on: (event: string, cb: () => void) => void }).on('plotly_click', () =>
        touchPlotly(id),
      )
    }
    loading.value = false
    error.value = null
    emit('ready')
  } catch (err) {
    loading.value = false
    error.value = err instanceof Error ? err.message : String(err)
  }
}

function onRelayout(event: Record<string, unknown>): void {
  touchPlotly(id)
  if (event['xaxis.autorange'] === true) {
    emit('relayout', null)
    return
  }
  const lo = event['xaxis.range[0]']
  const hi = event['xaxis.range[1]']
  if (typeof lo === 'number' && typeof hi === 'number') {
    emit('relayout', [Math.min(lo, hi), Math.max(lo, hi)])
    return
  }
  const range = event['xaxis.range']
  if (Array.isArray(range) && range.length === 2) {
    const [a, b] = range as [number, number]
    emit('relayout', [Math.min(a, b), Math.max(a, b)])
  }
}

function pause(): void {
  paused.value = true
  if (host.value && plotly.value) {
    plotly.value.purge(host.value)
    drawn = false
  }
}

function resume(): void {
  paused.value = false
  void draw()
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
    props.figure,
    props.series,
    props.showError,
    props.showContinuum,
    props.velocityWrest,
    props.xRange,
    ui.isDark,
  ],
  () => void draw(),
)

defineExpose({ pause, resume, id })
</script>

<template>
  <div class="relative h-full min-h-40 w-full" data-widget="plotly-view" :data-paused="paused">
    <div ref="host" class="h-full w-full" />
    <div
      v-if="paused"
      class="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-background/80 text-xs text-muted-foreground"
    >
      <p>{{ t('widgets.plotly_paused') }}</p>
      <button type="button" class="rounded-md border px-2 py-1 hover:bg-muted" @click="resume">
        {{ t('widgets.plotly_resume') }}
      </button>
    </div>
    <p
      v-else-if="loading && !error"
      class="pointer-events-none absolute inset-0 flex items-center justify-center text-xs text-muted-foreground"
    >
      {{ t('common.loading') }}
    </p>
    <p v-if="error" class="absolute inset-x-0 bottom-0 p-2 text-xs text-destructive">{{ error }}</p>
  </div>
</template>
