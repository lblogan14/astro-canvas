<script setup lang="ts">
/**
 * Canvas2D image viewer: colour-mapped tile with zscale/minmax/percentile scaling and
 * linear/asinh/log/sqrt stretches, wheel zoom + drag pan, pixel/value/WCS readout.
 * The tile is whatever the server sent (a downsampled summary tile or the full array); `step`
 * maps tile pixels back to data pixels for the readout.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { COLORMAP_NAMES, type ColormapName, colormapGradient } from '@/lib/colormaps'
import {
  DEFAULT_RENDER,
  type DecodedTile,
  type RenderOptions,
  type ScaleMode,
  type Stretch,
  limitsFor,
  paintTile,
  sampleTile,
} from '@/lib/tile'
import { type WcsDict, formatDec, formatRa, wcsFromDict } from '@/lib/wcs'

const props = withDefaults(
  defineProps<{
    tile: DecodedTile | null
    wcs?: WcsDict | null
    unit?: string | null
    options?: RenderOptions
    /** Show the scale/stretch/colormap controls and the readout bar. */
    controls?: boolean
    /** Allow wheel zoom and drag pan. */
    interactive?: boolean
    height?: number | null
  }>(),
  {
    wcs: null,
    unit: null,
    options: () => DEFAULT_RENDER,
    controls: true,
    interactive: true,
    height: null,
  },
)

const emit = defineEmits<{
  'update:options': [options: RenderOptions]
  /** Data pixel under the cursor (0-based) or `null` when it leaves. */
  hover: [pixel: { x: number; y: number; value: number } | null]
}>()

const { t } = useI18n()
const container = ref<HTMLDivElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
const offscreen = document.createElement('canvas')
const view = ref({ scale: 1, tx: 0, ty: 0 })
const hover = ref<{ x: number; y: number; value: number } | null>(null)
let dragging: { x: number; y: number; tx: number; ty: number } | null = null
let observer: ResizeObserver | null = null
let fitted = false

const wcs = computed(() => wcsFromDict(props.wcs ?? null))
const limits = computed<[number, number] | null>(() =>
  props.tile ? limitsFor(props.tile, props.options.scale, props.options.limits) : null,
)
const gradient = computed(() => colormapGradient(props.options.colormap))
const dataWidth = computed(() => (props.tile ? props.tile.width * props.tile.step : 0))
const dataHeight = computed(() => (props.tile ? props.tile.height * props.tile.step : 0))

const SCALES: ScaleMode[] = ['zscale', 'minmax', 'percentile']
const STRETCHES: Stretch[] = ['linear', 'asinh', 'log', 'sqrt']

function update(patch: Partial<RenderOptions>): void {
  emit('update:options', { ...props.options, ...patch })
}

function paintOffscreen(): void {
  const tile = props.tile
  if (!tile) return
  offscreen.width = tile.width
  offscreen.height = tile.height
  const ctx = offscreen.getContext('2d')
  if (!ctx) return
  const image = ctx.createImageData(tile.width, tile.height)
  paintTile(tile, image, props.options)
  ctx.putImageData(image, 0, 0)
}

function fit(): void {
  const el = container.value
  const tile = props.tile
  if (!el || !tile) return
  const w = el.clientWidth || 300
  const h = el.clientHeight || 200
  const scale = Math.min(w / tile.width, h / tile.height) * 0.98
  view.value = {
    scale,
    tx: (w - tile.width * scale) / 2,
    ty: (h - tile.height * scale) / 2,
  }
  fitted = true
}

function draw(): void {
  const el = container.value
  const cv = canvas.value
  const tile = props.tile
  if (!el || !cv) return
  const dpr = window.devicePixelRatio || 1
  const w = el.clientWidth || 300
  const h = el.clientHeight || 200
  cv.width = Math.round(w * dpr)
  cv.height = Math.round(h * dpr)
  cv.style.width = `${w}px`
  cv.style.height = `${h}px`
  const ctx = cv.getContext('2d')
  if (!ctx) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, w, h)
  if (!tile) return
  const { scale, tx, ty } = view.value
  ctx.imageSmoothingEnabled = scale < 1
  ctx.drawImage(offscreen, tx, ty, tile.width * scale, tile.height * scale)
}

function repaint(): void {
  paintOffscreen()
  if (!fitted) fit()
  draw()
}

/** Screen position → data pixel (0-based, FITS y up). */
function dataPixelAt(clientX: number, clientY: number): { x: number; y: number } | null {
  const el = container.value
  const tile = props.tile
  if (!el || !tile) return null
  const rect = el.getBoundingClientRect()
  const { scale, tx, ty } = view.value
  const col = (clientX - rect.left - tx) / scale
  const rowFromTop = (clientY - rect.top - ty) / scale
  if (col < 0 || rowFromTop < 0 || col >= tile.width || rowFromTop >= tile.height) return null
  const row = tile.height - rowFromTop
  return { x: col * tile.step, y: row * tile.step }
}

function onMove(event: MouseEvent): void {
  if (dragging && props.interactive) {
    view.value = {
      ...view.value,
      tx: dragging.tx + (event.clientX - dragging.x),
      ty: dragging.ty + (event.clientY - dragging.y),
    }
    draw()
    return
  }
  const pixel = dataPixelAt(event.clientX, event.clientY)
  if (!pixel || !props.tile) {
    hover.value = null
    emit('hover', null)
    return
  }
  const value = sampleTile(props.tile, pixel.x, pixel.y)
  hover.value = { x: pixel.x, y: pixel.y, value }
  emit('hover', hover.value)
}

function onLeave(): void {
  hover.value = null
  dragging = null
  emit('hover', null)
}

function onDown(event: MouseEvent): void {
  if (!props.interactive || event.button !== 0) return
  dragging = { x: event.clientX, y: event.clientY, tx: view.value.tx, ty: view.value.ty }
}

function onUp(): void {
  dragging = null
}

function onWheel(event: WheelEvent): void {
  if (!props.interactive || !container.value) return
  event.preventDefault()
  const rect = container.value.getBoundingClientRect()
  const px = event.clientX - rect.left
  const py = event.clientY - rect.top
  const factor = Math.exp(-event.deltaY * 0.0015)
  const scale = Math.min(64, Math.max(0.05, view.value.scale * factor))
  const ratio = scale / view.value.scale
  view.value = {
    scale,
    tx: px - (px - view.value.tx) * ratio,
    ty: py - (py - view.value.ty) * ratio,
  }
  draw()
}

function resetView(): void {
  fit()
  draw()
}

const readout = computed(() => {
  const h = hover.value
  if (!h) return null
  const parts: string[] = [`x ${h.x.toFixed(0)}  y ${h.y.toFixed(0)}`]
  parts.push(
    Number.isFinite(h.value)
      ? `${formatValue(h.value)}${props.unit ? ` ${props.unit}` : ''}`
      : 'NaN',
  )
  const w = wcs.value
  if (w) {
    const world = w.pixelToWorld(h.x, h.y)
    if (w.celestial) parts.push(`${formatRa(world.lon)}  ${formatDec(world.lat)}`)
    else parts.push(`${formatValue(world.lon)}, ${formatValue(world.lat)}`)
  }
  return parts
})

function formatValue(value: number): string {
  if (!Number.isFinite(value)) return 'NaN'
  const abs = Math.abs(value)
  if (abs !== 0 && (abs < 1e-3 || abs >= 1e6)) return value.toExponential(3)
  return value.toPrecision(5).replace(/\.?0+$/, '')
}

onMounted(() => {
  repaint()
  if (typeof ResizeObserver !== 'undefined' && container.value) {
    observer = new ResizeObserver(() => {
      if (!fitted) fit()
      draw()
    })
    observer.observe(container.value)
  }
})

onBeforeUnmount(() => observer?.disconnect())

watch(
  () => props.tile,
  () => {
    fitted = false
    repaint()
  },
)
watch(() => props.options, repaint, { deep: true })

defineExpose({ resetView, fit, view })
</script>

<template>
  <div class="flex h-full min-h-0 flex-col" data-widget="image-view">
    <div
      v-if="controls"
      class="flex flex-wrap items-center gap-2 border-b px-2 py-1 text-[11px]"
      data-testid="image-controls"
    >
      <label class="flex items-center gap-1">
        <span class="text-muted-foreground">{{ t('widgets.scale') }}</span>
        <select
          class="h-6 rounded border bg-background px-1"
          :value="options.scale"
          @change="update({ scale: ($event.target as HTMLSelectElement).value as ScaleMode })"
        >
          <option v-for="s in SCALES" :key="s" :value="s">{{ t(`widgets.scales.${s}`) }}</option>
          <option value="manual">{{ t('widgets.scales.manual') }}</option>
        </select>
      </label>
      <label class="flex items-center gap-1">
        <span class="text-muted-foreground">{{ t('widgets.stretch') }}</span>
        <select
          class="h-6 rounded border bg-background px-1"
          :value="options.stretch"
          @change="update({ stretch: ($event.target as HTMLSelectElement).value as Stretch })"
        >
          <option v-for="s in STRETCHES" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <label class="flex items-center gap-1">
        <span class="text-muted-foreground">{{ t('widgets.colormap') }}</span>
        <select
          class="h-6 rounded border bg-background px-1"
          :value="options.colormap"
          @change="update({ colormap: ($event.target as HTMLSelectElement).value as ColormapName })"
        >
          <option v-for="c in COLORMAP_NAMES" :key="c" :value="c">{{ c }}</option>
        </select>
      </label>
      <span class="inline-block h-3 w-16 rounded-sm border" :style="{ background: gradient }" />
      <span v-if="limits" class="font-mono text-muted-foreground" data-testid="image-limits">
        [{{ formatValue(limits[0]) }}, {{ formatValue(limits[1]) }}]
      </span>
      <button type="button" class="ml-auto rounded border px-1.5 hover:bg-muted" @click="resetView">
        {{ t('widgets.fit') }}
      </button>
    </div>
    <div
      ref="container"
      class="relative min-h-0 flex-1 overflow-hidden bg-black/90"
      :class="interactive ? 'cursor-crosshair' : ''"
      :style="height ? { height: `${height}px`, flex: 'none' } : undefined"
      @mousemove="onMove"
      @mouseleave="onLeave"
      @mousedown="onDown"
      @mouseup="onUp"
      @wheel="onWheel"
      @dblclick="resetView"
    >
      <canvas ref="canvas" class="block" />
      <p
        v-if="!tile"
        class="absolute inset-0 flex items-center justify-center text-xs text-muted-foreground"
      >
        {{ t('widgets.no_data') }}
      </p>
    </div>
    <div
      v-if="controls"
      class="flex h-6 items-center gap-3 border-t px-2 font-mono text-[11px] text-muted-foreground"
      data-testid="image-readout"
    >
      <template v-if="readout">
        <span v-for="(part, i) in readout" :key="i">{{ part }}</span>
      </template>
      <span v-else>{{ dataWidth }} × {{ dataHeight }}</span>
    </div>
  </div>
</template>
