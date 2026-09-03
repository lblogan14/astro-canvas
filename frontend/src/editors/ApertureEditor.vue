<script setup lang="ts">
/**
 * `aperture-editor` for `rbcodes.ifu.aperture_extract`: rb_ifuview's image panel on the canvas.
 *
 * The cube's white-light collapse is the backdrop (a wavelength slider re-collapses it through
 * `preview.request`, so the server does the work); apertures are drawn on an SVG layer above it in
 * data pixels, so a pan or zoom of the image moves them with it. Selecting one asks the server to
 * run *this* node with the candidate apertures (`preview.compute` with `node_id`) and draws the
 * extracted spectrum underneath — the same code that will run in the graph, not a re-implementation.
 *
 * Apply is one `workflow.setParams(nodeId, { regions })`.
 */
import { computed, onBeforeUnmount, onMounted, ref, toRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { Button } from '@/components/ui/button'
import { DEFAULT_RENDER, type RenderOptions, decodeTile, isTileSummary } from '@/lib/tile'
import { type WcsDict, formatDec, formatRa, wcsFromDict } from '@/lib/wcs'
import { useExecutionStore } from '@/stores/execution'
import { useSessionStore } from '@/stores/session'
import { useWorkflowStore } from '@/stores/workflow'
import { ImageView, UPlotLine } from '@/widgets'
import { type SpectrumSeries, seriesFromSummary } from '@/widgets/spectrumSeries'

import {
  type Aperture,
  type ApertureShape,
  SHAPES,
  aperturesFrom,
  apertureFromDrag,
  center,
  clampToField,
  defaultLabel,
  describe,
  fromDs9,
  moveTo,
  outerRadius,
  pick,
  resizeTo,
  toDs9,
  toParam,
} from './aperture'
import { EDITOR_TAG, type EditorProps } from './registry'
import { useUpstream } from './useUpstream'

/** Tile edge for the backdrop: enough to see structure, small enough to stay inside the JSON. */
const TILE = 512
const EXTRACT_TAG = `${EDITOR_TAG}-extract`
const SOURCE_COLOR = '#38BDF8'
const BACKGROUND_COLOR = '#FB923C'
const SELECTED_COLOR = '#FACC15'

const props = defineProps<EditorProps>()
const emit = defineEmits<{ close: [] }>()

const { t } = useI18n()
const workflow = useWorkflowStore()
const execution = useExecutionStore()
const session = useSessionStore()
const nodeId = toRef(props, 'nodeId')

// --- the cube behind the editor -----------------------------------------------------------------

const band = ref<[number, number] | null>(null)
const viewport = computed(() => {
  const window = band.value
  return window ? { n_out: TILE, lo: window[0], hi: window[1] } : { n_out: TILE }
})
const cube = useUpstream(nodeId, 'cube', { n_out: TILE })
const seed = useUpstream(nodeId, 'region_seed', { rows: 500 })

const summary = computed(() => cube.entry.value?.summary ?? null)
const tile = computed(() => {
  const value = summary.value?.['tile']
  return isTileSummary(value) ? decodeTile(value) : null
})
const shape = computed(() => {
  const value = summary.value?.['shape']
  if (!Array.isArray(value) || value.length !== 3) return null
  return { nz: Number(value[0]), ny: Number(value[1]), nx: Number(value[2]) }
})
const waveRange = computed<[number, number] | null>(() => {
  const value = summary.value?.['wave_range']
  return Array.isArray(value) && value.length === 2 ? [Number(value[0]), Number(value[1])] : null
})
const wcsDict = computed<WcsDict | null>(() => (summary.value?.['wcs'] as WcsDict) ?? null)
const wcs = computed(() => wcsFromDict(wcsDict.value))
const arcsecPerPixel = computed(() => {
  const w = wcs.value
  if (!w || !w.celestial) return null
  return w.pixelScale()[0] * 3600
})
const render = ref<RenderOptions>({ ...DEFAULT_RENDER })

/** Re-collapse on the server when the band changes (debounced by the slider's `change` event). */
function requestBand(): void {
  const source = cube.source.value
  if (!source) return
  session.requestPreview(source.nodeId, source.port, { ...viewport.value, tag: EDITOR_TAG })
}

// --- apertures ----------------------------------------------------------------------------------

const apertures = ref<Aperture[]>([])
const selected = ref(-1)
const dirty = ref(false)
const tool = ref<ApertureShape>('circle')
const nextRole = ref<'source' | 'background'>('source')
const status = ref('')

const params = computed<Record<string, unknown>>(() => workflow.nodes[props.nodeId]?.params ?? {})

function seedApertures(): void {
  const fromParam = aperturesFrom(params.value['regions'])
  apertures.value = fromParam.length ? fromParam : aperturesFrom(seed.entry.value?.summary)
  selected.value = apertures.value.length ? 0 : -1
  dirty.value = false
}

onMounted(seedApertures)
watch(
  () => seed.entry.value,
  () => {
    if (!dirty.value) seedApertures()
  },
)

function touch(): void {
  dirty.value = true
}

function say(message: string): void {
  status.value = message
}

function update(index: number, next: Aperture): void {
  apertures.value = apertures.value.map((a, i) => (i === index ? next : a))
  touch()
}

function remove(index: number): void {
  apertures.value = apertures.value.filter((_, i) => i !== index)
  selected.value = Math.min(selected.value, apertures.value.length - 1)
  touch()
  say(t('editor.aperture.status.removed'))
}

function setRole(index: number, role: 'source' | 'background'): void {
  const aperture = apertures.value[index]
  if (aperture) update(index, { ...aperture, role })
}

function setLabel(index: number, label: string): void {
  const aperture = apertures.value[index]
  if (aperture) update(index, { ...aperture, label: label.trim() || null })
}

function clearAll(): void {
  apertures.value = []
  selected.value = -1
  touch()
}

// --- drawing on the image -----------------------------------------------------------------------

const overlay = ref<SVGSVGElement | null>(null)
const cursor = ref<{ x: number; y: number; value: number } | null>(null)
type Drag =
  | { kind: 'draw'; from: { x: number; y: number } }
  | { kind: 'move'; index: number }
  | { kind: 'resize'; index: number }
const drag = ref<Drag | null>(null)
const preview = ref<Aperture | null>(null)

/** The overlay is positioned over the image, so a client point maps through the same transform. */
function dataAt(event: MouseEvent): { x: number; y: number } | null {
  const el = overlay.value
  const decoded = tile.value
  if (!el || !decoded) return null
  const rect = el.getBoundingClientRect()
  const x = ((event.clientX - rect.left) / rect.width) * decoded.width * decoded.step
  const y = (1 - (event.clientY - rect.top) / rect.height) * decoded.height * decoded.step
  return { x, y }
}

function onDown(event: MouseEvent): void {
  const point = dataAt(event)
  if (!point) return
  event.preventDefault()
  const hit = pick(apertures.value, point)
  if (hit >= 0 && !event.shiftKey) {
    selected.value = hit
    const aperture = apertures.value[hit]
    const distance = aperture
      ? Math.hypot(point.x - center(aperture).x, point.y - center(aperture).y)
      : 0
    const edge = aperture ? outerRadius(aperture) : 0
    drag.value = { kind: distance > edge * 0.7 ? 'resize' : 'move', index: hit }
    return
  }
  drag.value = { kind: 'draw', from: point }
  preview.value = apertureFromDrag(tool.value, point, point, nextRole.value)
}

function onMove(event: MouseEvent): void {
  const point = dataAt(event)
  if (!point) return
  const current = drag.value
  if (!current) return
  if (current.kind === 'draw') {
    preview.value = apertureFromDrag(tool.value, current.from, point, nextRole.value)
    return
  }
  const aperture = apertures.value[current.index]
  if (!aperture) return
  update(
    current.index,
    current.kind === 'move' ? moveTo(aperture, point) : resizeTo(aperture, point),
  )
}

function onUp(): void {
  const current = drag.value
  const drawn = preview.value
  drag.value = null
  preview.value = null
  if (current?.kind !== 'draw' || !drawn) return
  const field = shape.value
  if (outerRadius(drawn) < 1) return
  const placed = field ? clampToField(drawn, field.ny, field.nx) : drawn
  apertures.value = [...apertures.value, placed]
  selected.value = apertures.value.length - 1
  touch()
  say(t('editor.aperture.status.added', { shape: t(`editor.aperture.shapes.${placed.shape}`) }))
}

function onHover(pixel: { x: number; y: number; value: number } | null): void {
  cursor.value = pixel
}

/** Data pixels → the overlay's viewBox (SVG y grows downward, FITS y upward). */
const viewBox = computed(() => {
  const decoded = tile.value
  if (!decoded) return '0 0 1 1'
  return `0 0 ${decoded.width * decoded.step} ${decoded.height * decoded.step}`
})

function svgY(y: number): number {
  const decoded = tile.value
  return decoded ? decoded.height * decoded.step - y : y
}

function polygonPoints(aperture: Aperture): string {
  const parts: string[] = []
  for (let i = 0; i + 1 < aperture.pixel.length; i += 2) {
    parts.push(`${aperture.pixel[i]},${svgY(aperture.pixel[i + 1] ?? 0)}`)
  }
  return parts.join(' ')
}

function colorOf(aperture: Aperture, index: number): string {
  if (index === selected.value) return SELECTED_COLOR
  return aperture.role === 'background' ? BACKGROUND_COLOR : SOURCE_COLOR
}

const drawn = computed(() =>
  preview.value ? [...apertures.value, preview.value] : apertures.value,
)

// --- readout -------------------------------------------------------------------------------------

const readout = computed<string[]>(() => {
  const point = cursor.value
  if (!point) return []
  const parts = [`x ${point.x.toFixed(1)}  y ${point.y.toFixed(1)}`]
  const w = wcs.value
  if (w) {
    const world = w.pixelToWorld(point.x, point.y)
    parts.push(
      w.celestial
        ? `${formatRa(world.lon)} ${formatDec(world.lat)}`
        : `${world.lon.toFixed(4)}, ${world.lat.toFixed(4)}`,
    )
  }
  if (Number.isFinite(point.value)) parts.push(point.value.toPrecision(4))
  return parts
})

// --- live extraction ------------------------------------------------------------------------------

const extractRun = ref(0)

/** Run this node with the current apertures; the reply arrives as a tagged summary. */
function extract(): void {
  if (!apertures.value.some((a) => a.role === 'source')) return
  extractRun.value += 1
  session.requestCompute({
    node_id: props.nodeId,
    params: { ...params.value, regions: toParam(apertures.value) },
    tag: EXTRACT_TAG,
    viewport: { n_out: 2000, max_items: 8 },
  })
}

const computeState = computed(() => execution.compute(props.nodeId, EXTRACT_TAG))
const extracted = computed<SpectrumSeries | null>(() => {
  const entry = execution.view(props.nodeId, 'spectra', EXTRACT_TAG)
  const items = entry?.summary?.['items']
  if (!Array.isArray(items)) return null
  const sources = apertures.value.filter((a) => a.role === 'source')
  const index = Math.max(0, sources.indexOf(apertures.value[selected.value] ?? sources[0]!))
  const item = items[Math.min(index, items.length - 1)]
  return typeof item === 'object' && item !== null
    ? seriesFromSummary(item as Record<string, unknown>)
    : null
})

// Re-extract when the apertures settle (not on every pixel of a drag).
watch(
  () => [apertures.value.length, JSON.stringify(toParam(apertures.value)), params.value['method']],
  () => {
    if (!drag.value) extract()
  },
)
watch(
  () => selected.value,
  () => {
    if (!extracted.value) extract()
  },
)

// --- ds9 -------------------------------------------------------------------------------------------

const fileInput = ref<HTMLInputElement | null>(null)

function importDs9(): void {
  fileInput.value?.click()
}

async function onFile(event: Event): Promise<void> {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  const { apertures: parsed, skipped } = fromDs9(await file.text())
  ;(event.target as HTMLInputElement).value = ''
  if (!parsed.length) {
    say(t('editor.aperture.status.import_empty'))
    return
  }
  apertures.value = [...apertures.value, ...parsed]
  selected.value = apertures.value.length - 1
  touch()
  say(
    skipped
      ? t('editor.aperture.status.import_partial', { n: parsed.length, skipped })
      : t('editor.aperture.status.imported', { n: parsed.length }),
  )
}

function exportDs9(): void {
  const blob = new Blob([toDs9(apertures.value)], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${props.nodeId}-apertures.reg`
  link.click()
  URL.revokeObjectURL(url)
  say(t('editor.aperture.status.exported', { n: apertures.value.length }))
}

// --- band slider ------------------------------------------------------------------------------------

function onBand(which: 0 | 1, value: number): void {
  const full = waveRange.value
  if (!full) return
  const current = band.value ?? [full[0], full[1]]
  const next: [number, number] = which === 0 ? [value, current[1]] : [current[0], value]
  band.value = next[0] <= next[1] ? next : [next[1], next[0]]
  requestBand()
}

function resetBand(): void {
  band.value = null
  requestBand()
}

// --- apply --------------------------------------------------------------------------------------------

const sourceCount = computed(() => apertures.value.filter((a) => a.role === 'source').length)

function apply(): void {
  workflow.setParams(props.nodeId, { regions: toParam(apertures.value) })
  emit('close')
}

onBeforeUnmount(() => {
  execution.clearTag(props.nodeId, EXTRACT_TAG)
})
</script>

<template>
  <div
    class="flex h-full min-h-0 flex-col gap-2"
    data-testid="editor-aperture"
    :data-apertures="apertures.length"
  >
    <!-- toolbar -->
    <div class="flex flex-wrap items-center gap-2 text-xs">
      <div class="flex items-center gap-1" role="group" :aria-label="t('editor.aperture.tool')">
        <button
          v-for="s in SHAPES"
          :key="s"
          type="button"
          class="h-7 rounded border px-2 capitalize"
          :class="tool === s ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'"
          :data-testid="`aperture-tool-${s}`"
          @click="tool = s"
        >
          {{ t(`editor.aperture.shapes.${s}`) }}
        </button>
      </div>
      <label class="flex items-center gap-1">
        <input
          type="checkbox"
          data-testid="aperture-background-toggle"
          :checked="nextRole === 'background'"
          @change="nextRole = nextRole === 'background' ? 'source' : 'background'"
        />
        <span>{{ t('editor.aperture.draw_background') }}</span>
      </label>
      <Button size="sm" variant="outline" data-testid="aperture-import" @click="importDs9">
        {{ t('editor.aperture.import') }}
      </Button>
      <Button
        size="sm"
        variant="outline"
        data-testid="aperture-export"
        :disabled="!apertures.length"
        @click="exportDs9"
      >
        {{ t('editor.aperture.export') }}
      </Button>
      <Button
        size="sm"
        variant="outline"
        data-testid="aperture-clear"
        :disabled="!apertures.length"
        @click="clearAll"
      >
        {{ t('editor.aperture.clear') }}
      </Button>
      <input
        ref="fileInput"
        type="file"
        accept=".reg,text/plain"
        class="hidden"
        data-testid="aperture-file"
        @change="onFile"
      />
      <span
        class="ml-auto font-mono text-[11px] text-muted-foreground"
        data-testid="aperture-status"
      >
        {{ status }}
      </span>
    </div>

    <!-- band -->
    <div v-if="waveRange" class="flex items-center gap-2 text-[11px]" data-testid="aperture-band">
      <span class="text-muted-foreground">{{ t('editor.aperture.band') }}</span>
      <input
        type="range"
        class="w-32"
        data-testid="aperture-band-lo"
        :min="waveRange[0]"
        :max="waveRange[1]"
        :step="(waveRange[1] - waveRange[0]) / 200"
        :value="band ? band[0] : waveRange[0]"
        @change="onBand(0, Number(($event.target as HTMLInputElement).value))"
      />
      <input
        type="range"
        class="w-32"
        data-testid="aperture-band-hi"
        :min="waveRange[0]"
        :max="waveRange[1]"
        :step="(waveRange[1] - waveRange[0]) / 200"
        :value="band ? band[1] : waveRange[1]"
        @change="onBand(1, Number(($event.target as HTMLInputElement).value))"
      />
      <span class="font-mono text-muted-foreground">
        {{ (band ? band[0] : waveRange[0]).toFixed(1) }}–{{
          (band ? band[1] : waveRange[1]).toFixed(1)
        }}
        Å
      </span>
      <Button size="sm" variant="ghost" data-testid="aperture-band-reset" @click="resetBand">
        {{ t('editor.aperture.full_band') }}
      </Button>
    </div>

    <div class="flex min-h-0 flex-1 gap-2">
      <!-- image + overlay -->
      <div class="relative min-h-0 min-w-0 flex-1">
        <ImageView
          :tile="tile"
          :wcs="wcsDict"
          :options="render"
          :interactive="false"
          :controls="true"
          class="h-full"
          @update:options="render = $event"
          @hover="onHover"
        />
        <svg
          ref="overlay"
          class="absolute inset-x-0 cursor-crosshair"
          style="top: 28px; bottom: 24px"
          :viewBox="viewBox"
          preserveAspectRatio="none"
          data-testid="aperture-overlay"
          @mousedown="onDown"
          @mousemove="onMove"
          @mouseup="onUp"
          @mouseleave="onUp"
        >
          <g v-for="(aperture, index) in drawn" :key="index" data-testid="aperture-shape">
            <circle
              v-if="aperture.shape === 'circle'"
              :cx="aperture.pixel[0]"
              :cy="svgY(aperture.pixel[1] ?? 0)"
              :r="aperture.pixel[2]"
              fill="none"
              vector-effect="non-scaling-stroke"
              stroke-width="1.5"
              :stroke="colorOf(aperture, index)"
            />
            <template v-else-if="aperture.shape === 'annulus'">
              <circle
                :cx="aperture.pixel[0]"
                :cy="svgY(aperture.pixel[1] ?? 0)"
                :r="aperture.pixel[2]"
                fill="none"
                vector-effect="non-scaling-stroke"
                stroke-width="1.5"
                stroke-dasharray="4 3"
                :stroke="colorOf(aperture, index)"
              />
              <circle
                :cx="aperture.pixel[0]"
                :cy="svgY(aperture.pixel[1] ?? 0)"
                :r="aperture.pixel[3]"
                fill="none"
                vector-effect="non-scaling-stroke"
                stroke-width="1.5"
                :stroke="colorOf(aperture, index)"
              />
            </template>
            <rect
              v-else-if="aperture.shape === 'box'"
              :x="(aperture.pixel[0] ?? 0) - (aperture.pixel[2] ?? 0) / 2"
              :y="svgY(aperture.pixel[1] ?? 0) - (aperture.pixel[3] ?? 0) / 2"
              :width="aperture.pixel[2]"
              :height="aperture.pixel[3]"
              fill="none"
              vector-effect="non-scaling-stroke"
              stroke-width="1.5"
              :stroke="colorOf(aperture, index)"
              :transform="`rotate(${-(aperture.pixel[4] ?? 0)} ${aperture.pixel[0]} ${svgY(aperture.pixel[1] ?? 0)})`"
            />
            <polygon
              v-else
              :points="polygonPoints(aperture)"
              fill="none"
              vector-effect="non-scaling-stroke"
              stroke-width="1.5"
              :stroke="colorOf(aperture, index)"
            />
          </g>
        </svg>
      </div>

      <!-- aperture list -->
      <div class="flex w-56 min-h-0 flex-col gap-1 overflow-auto" data-testid="aperture-list">
        <p v-if="!apertures.length" class="text-xs text-muted-foreground">
          {{ t('editor.aperture.empty') }}
        </p>
        <div
          v-for="(aperture, index) in apertures"
          :key="index"
          class="rounded border p-1 text-[11px]"
          :class="index === selected ? 'border-primary bg-muted/40' : ''"
          data-testid="aperture-row"
          :data-role="aperture.role"
          @click="selected = index"
        >
          <div class="flex items-center gap-1">
            <span
              class="inline-block size-2 rounded-full"
              :style="{ background: colorOf(aperture, index) }"
            />
            <input
              class="h-6 min-w-0 flex-1 rounded border bg-background px-1"
              data-testid="aperture-label"
              :value="aperture.label ?? ''"
              :placeholder="defaultLabel(aperture, index)"
              @change="setLabel(index, ($event.target as HTMLInputElement).value)"
            />
            <button
              type="button"
              class="rounded px-1 hover:bg-muted"
              data-testid="aperture-remove"
              :aria-label="t('editor.aperture.remove')"
              @click.stop="remove(index)"
            >
              ×
            </button>
          </div>
          <div class="mt-0.5 flex items-center justify-between text-muted-foreground">
            <span class="font-mono">{{ describe(aperture, arcsecPerPixel) }}</span>
            <label class="flex items-center gap-1">
              <input
                type="checkbox"
                data-testid="aperture-row-background"
                :checked="aperture.role === 'background'"
                @change="setRole(index, aperture.role === 'background' ? 'source' : 'background')"
              />
              <span>{{ t('editor.aperture.background') }}</span>
            </label>
          </div>
        </div>
      </div>
    </div>

    <!-- extracted spectrum -->
    <div class="h-32 shrink-0 rounded border p-1" data-testid="aperture-spectrum">
      <UPlotLine v-if="extracted" :series="extracted" :height="110" :axes="true" />
      <p v-else class="flex h-full items-center justify-center text-xs text-muted-foreground">
        {{
          computeState?.error
            ? t('editor.aperture.extract_error', { message: computeState.error })
            : sourceCount
              ? t('editor.aperture.extracting')
              : t('editor.aperture.no_source')
        }}
      </p>
    </div>

    <!-- footer -->
    <div class="flex items-center gap-2 text-xs">
      <span class="font-mono text-muted-foreground" data-testid="aperture-readout">
        <template v-if="readout.length">
          <span v-for="(part, i) in readout" :key="i" class="mr-3">{{ part }}</span>
        </template>
        <template v-else-if="shape">{{ shape.ny }} × {{ shape.nx }} px</template>
      </span>
      <span class="ml-auto text-muted-foreground" data-testid="aperture-counts">
        {{ t('editor.aperture.counts', { sources: sourceCount, total: apertures.length }) }}
      </span>
      <Button size="sm" variant="outline" @click="emit('close')">{{ t('editor.close') }}</Button>
      <Button size="sm" data-testid="aperture-apply" :disabled="!sourceCount" @click="apply">
        {{ t('editor.apply') }}
      </Button>
    </div>
  </div>
</template>
