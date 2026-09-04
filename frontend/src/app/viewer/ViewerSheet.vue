<script setup lang="ts">
/**
 * Full-size view of one node output (design §8.3, "Expand"): Plotly for spectra with server-side
 * re-decimation on box zoom, ImageView for images and cube white-light bands, DataTable for tables
 * (Arrow), Plotly/PNG for figures, key/value for everything else. Not an editor yet (phase 05+).
 */
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from 'reka-ui'
import { Download, X } from '@lucide/vue'

import { api, getToken } from '@/api/client'
import type { DecodedFrame } from '@/api/frames'
import {
  DEFAULT_RENDER,
  type DecodedTile,
  type RenderOptions,
  decodeTile,
  isTileSummary,
  tileFromArray,
} from '@/lib/tile'
import type { WcsDict } from '@/lib/wcs'
import { SCALED, previewBudget, previewComponent, rendererFor } from '@/previews'
import { useExecutionStore } from '@/stores/execution'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'
import {
  DataTable,
  ImageView,
  KeyValueTile,
  type PlotlyFigure,
  PlotlyView,
  type SpectrumSeries,
  type TableHead,
  UPlotLine,
  seriesFromSummary,
} from '@/widgets'

const VIEW_TAG = 'viewer'
const FULL_POINTS = 20000
const FULL_TILE = 1024

const { t } = useI18n()
const ui = useUiStore()
const execution = useExecutionStore()
const session = useSessionStore()
const schema = useNodesSchemaStore()
const workflow = useWorkflowStore()

const target = computed(() => ui.viewer)
const open = computed(() => target.value !== null)
const node = computed(() => (target.value ? workflow.nodes[target.value.nodeId] : undefined))
const spec = computed(() => workflow.specFor(node.value))
const thumb = computed(() =>
  target.value ? execution.node(target.value.nodeId).summaries[target.value.port] : undefined,
)
const typeId = computed(
  () =>
    thumb.value?.typeId ??
    spec.value?.outputs.find((p) => p.name === target.value?.port)?.type ??
    'astro.Any',
)
const renderer = computed(() =>
  rendererFor(spec.value, schema.typeById[typeId.value], thumb.value?.summary),
)
const title = computed(() =>
  target.value
    ? t('viewer.title', {
        node: node.value?.title ?? spec.value?.name ?? target.value.nodeId,
        port: target.value.port,
      })
    : '',
)
const viewSummary = computed(() =>
  target.value ? execution.view(target.value.nodeId, target.value.port, VIEW_TAG) : undefined,
)

// --- renderers shown at full width -------------------------------------------------------------

/** Width the scaled renderers paint into (they all take a `width` prop). */
const SCALED_WIDTH = 1100

const scaled = computed(() => SCALED.has(renderer.value))
const scaledSummary = computed<Record<string, unknown>>(
  () => viewSummary.value?.summary ?? thumb.value?.summary ?? {},
)

/** Ask for a denser payload than the node thumbnail carried. */
function requestScaled(): void {
  if (!target.value) return
  const budget = previewBudget(renderer.value, SCALED_WIDTH)
  session.requestPreview(target.value.nodeId, target.value.port, {
    tag: VIEW_TAG,
    ...(budget === null ? {} : { n_out: budget }),
  })
}

// --- spectra -----------------------------------------------------------------------------------

const showError = ref(true)
const showContinuum = ref(true)
const velocity = ref(false)
const restWavelength = ref<number | null>(null)
const xRange = ref<[number, number] | null>(null)
let relayoutTimer: ReturnType<typeof setTimeout> | null = null

const series = computed<SpectrumSeries | null>(() => {
  const summary = viewSummary.value?.summary ?? thumb.value?.summary
  return summary ? seriesFromSummary(summary) : null
})

function requestSpectrum(range: [number, number] | null): void {
  if (!target.value) return
  session.requestPreview(target.value.nodeId, target.value.port, {
    n_out: FULL_POINTS,
    tag: VIEW_TAG,
    ...(range ? { lo: range[0], hi: range[1] } : {}),
  })
}

function onRelayout(range: [number, number] | null): void {
  xRange.value = range
  if (relayoutTimer !== null) clearTimeout(relayoutTimer)
  relayoutTimer = setTimeout(() => {
    relayoutTimer = null
    requestSpectrum(range)
  }, 100)
}

// --- images and cubes --------------------------------------------------------------------------

const renderOptions = ref<RenderOptions>({ ...DEFAULT_RENDER })
const fullTile = shallowRef<DecodedTile | null>(null)
const band = ref<[number, number] | null>(null)
let stopFrames: (() => void) | null = null

const tile = computed<DecodedTile | null>(() => {
  if (fullTile.value) return fullTile.value
  const summary = viewSummary.value?.summary ?? thumb.value?.summary
  const raw = summary?.['tile']
  return isTileSummary(raw) ? decodeTile(raw) : null
})
const wcs = computed<WcsDict | null>(() => {
  const summary = viewSummary.value?.summary ?? thumb.value?.summary
  const raw = summary?.['wcs']
  return raw && typeof raw === 'object' ? (raw as WcsDict) : null
})
const unit = computed(() => {
  const raw = thumb.value?.summary['unit']
  return typeof raw === 'string' ? raw : null
})
const cubeSpectrum = computed<SpectrumSeries | null>(() => {
  const summary = thumb.value?.summary
  const spec2 = summary?.['spectrum'] as { wave?: unknown; flux?: unknown } | undefined
  if (!spec2 || !Array.isArray(spec2.wave) || !Array.isArray(spec2.flux)) return null
  const wave = spec2.wave as number[]
  return {
    wave,
    flux: (spec2.flux as (number | null)[]).map((v) => (v === null ? Number.NaN : v)),
    waveUnit:
      typeof summary?.['wave_unit'] === 'string' ? (summary['wave_unit'] as string) : 'Angstrom',
    fluxUnit: '',
    frame: 'observed',
    z: null,
    v0Wrest: null,
    n: wave.length,
    range: wave.length ? [wave[0] ?? 0, wave[wave.length - 1] ?? 0] : null,
  }
})

function onFrame(frame: DecodedFrame): void {
  if (!target.value) return
  if (frame.header.node_id !== target.value.nodeId || frame.header.port !== target.value.port)
    return
  if (frame.header.type_id !== 'astro.Image2D') return
  const data = frame.arrays['data']
  if (!data || data.shape.length !== 2) return
  const [ny, nx] = data.shape as [number, number]
  const view = data.view
  if (view instanceof Float32Array || view instanceof Float64Array) {
    fullTile.value = tileFromArray(view, nx, ny)
  }
}

function requestCubeBand(range: [number, number] | null): void {
  if (!target.value) return
  band.value = range
  session.requestPreview(target.value.nodeId, target.value.port, {
    n_out: FULL_TILE,
    tag: VIEW_TAG,
    ...(range ? { lo: range[0], hi: range[1] } : {}),
  })
}

// --- tables and figures ------------------------------------------------------------------------

const arrow = shallowRef<ArrayBuffer | null>(null)
const figure = shallowRef<PlotlyFigure | null>(null)
const png = ref<string | null>(null)
const loadError = ref<string | null>(null)

const head = computed<TableHead | null>(() => {
  const summary = thumb.value?.summary
  const columns = summary?.['columns']
  const rows = summary?.['head']
  if (!Array.isArray(columns) || typeof rows !== 'object' || rows === null) return null
  return {
    columns: columns as string[],
    rows: rows as Record<string, unknown[]>,
    units: (summary?.['units'] as Record<string, string> | undefined) ?? {},
    nRows: typeof summary?.['n_rows'] === 'number' ? (summary['n_rows'] as number) : undefined,
  }
})

const kvData = computed<Record<string, unknown>>(() => {
  const summary = thumb.value?.summary ?? {}
  const inner = summary['data']
  return typeof inner === 'object' && inner !== null && !Array.isArray(inner)
    ? (inner as Record<string, unknown>)
    : summary
})

async function loadTable(): Promise<void> {
  if (!target.value || !workflow.id) return
  try {
    arrow.value = await api.fetchOutputArrow(workflow.id, target.value.nodeId, target.value.port)
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : String(err)
  }
}

async function loadFigure(): Promise<void> {
  if (!target.value || !workflow.id) return
  const summary = thumb.value?.summary
  if (summary?.['plotly']) {
    figure.value = summary['plotly'] as PlotlyFigure
    return
  }
  if (typeof summary?.['png_b64'] === 'string') {
    png.value = `data:image/png;base64,${summary['png_b64']}`
    return
  }
  try {
    const response = await fetch(
      api.outputUrl(workflow.id, target.value.nodeId, target.value.port, 'json'),
      {
        headers: { Authorization: `Bearer ${getToken() ?? ''}` },
      },
    )
    const body = (await response.json()) as { data?: { plotly?: PlotlyFigure; png?: string } }
    if (body.data?.plotly) figure.value = body.data.plotly
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : String(err)
  }
}

const downloadJson = computed(() => {
  if (!target.value || !workflow.id) return null
  const token = getToken()
  return `${api.outputUrl(workflow.id, target.value.nodeId, target.value.port, 'json')}${token ? `&token=${encodeURIComponent(token)}` : ''}`
})
const downloadArrow = computed(() => {
  if (!target.value || !workflow.id) return null
  const token = getToken()
  return `${api.outputUrl(workflow.id, target.value.nodeId, target.value.port, 'arrow')}${token ? `&token=${encodeURIComponent(token)}` : ''}`
})

// --- lifecycle ---------------------------------------------------------------------------------

function reset(): void {
  xRange.value = null
  fullTile.value = null
  band.value = null
  arrow.value = null
  figure.value = null
  png.value = null
  loadError.value = null
  velocity.value = false
  if (relayoutTimer !== null) clearTimeout(relayoutTimer)
  relayoutTimer = null
  stopFrames?.()
  stopFrames = null
}

watch(
  target,
  (next, previous) => {
    if (previous) execution.clearView(previous.nodeId, previous.port, VIEW_TAG)
    reset()
    if (!next) return
    switch (renderer.value) {
      case 'spectrum-thumb':
      case 'spectrum-stack':
        requestSpectrum(null)
        break
      case 'image-thumb':
        stopFrames = session.onFrame(onFrame)
        session.requestOutput(next.nodeId, next.port)
        break
      case 'cube-thumb':
        requestCubeBand(null)
        break
      case 'table-head':
        void loadTable()
        break
      case 'figure':
        void loadFigure()
        break
      default:
        if (scaled.value) requestScaled()
        break
    }
  },
  { immediate: true },
)

onBeforeUnmount(reset)

function close(): void {
  ui.closeViewer()
}
</script>

<template>
  <DialogRoot :open="open" @update:open="(value) => !value && close()">
    <DialogPortal>
      <DialogOverlay class="fixed inset-0 z-40 bg-black/40" />
      <DialogContent
        class="fixed inset-4 z-50 flex flex-col rounded-lg border bg-background shadow-xl focus:outline-none md:inset-x-12 md:inset-y-8"
        data-testid="viewer"
        :data-renderer="renderer"
        @escape-key-down="close"
      >
        <header class="flex h-10 items-center gap-2 border-b px-3">
          <DialogTitle class="min-w-0 flex-1 truncate text-sm font-semibold">{{
            title
          }}</DialogTitle>
          <DialogDescription class="sr-only">{{ typeId }}</DialogDescription>
          <span class="rounded bg-muted px-1.5 py-px font-mono text-[10px] text-muted-foreground">{{
            typeId
          }}</span>
          <a
            v-if="downloadArrow && renderer === 'table-head'"
            :href="downloadArrow"
            class="inline-flex h-7 items-center gap-1 rounded border px-2 text-xs hover:bg-muted"
            download
          >
            <Download class="size-3.5" /> {{ t('viewer.download_arrow') }}
          </a>
          <a
            v-if="downloadJson"
            :href="downloadJson"
            class="inline-flex h-7 items-center gap-1 rounded border px-2 text-xs hover:bg-muted"
            download
          >
            <Download class="size-3.5" /> {{ t('viewer.download_json') }}
          </a>
          <DialogClose
            class="inline-flex size-7 items-center justify-center rounded hover:bg-muted"
            :aria-label="t('viewer.close')"
            data-testid="viewer-close"
          >
            <X class="size-4" />
          </DialogClose>
        </header>

        <!-- Spectrum: Plotly with server re-decimation -->
        <template v-if="renderer === 'spectrum-thumb' || renderer === 'spectrum-stack'">
          <div class="flex flex-wrap items-center gap-3 border-b px-3 py-1 text-xs">
            <label class="flex items-center gap-1">
              <input v-model="showError" type="checkbox" /> {{ t('widgets.show_error') }}
            </label>
            <label class="flex items-center gap-1">
              <input v-model="showContinuum" type="checkbox" /> {{ t('widgets.show_continuum') }}
            </label>
            <label class="flex items-center gap-1">
              <input v-model="velocity" type="checkbox" /> {{ t('widgets.velocity_axis') }}
            </label>
            <label v-if="velocity" class="flex items-center gap-1">
              <span class="text-muted-foreground">{{ t('widgets.rest_wavelength') }}</span>
              <input
                v-model.number="restWavelength"
                type="number"
                step="0.01"
                class="h-6 w-28 rounded border bg-background px-1 font-mono"
              />
            </label>
            <span class="ml-auto text-muted-foreground">{{ t('viewer.zoom_hint') }}</span>
          </div>
          <div class="min-h-0 flex-1 p-2">
            <PlotlyView
              :series="series"
              :show-error="showError"
              :show-continuum="showContinuum"
              :velocity-wrest="velocity ? restWavelength : null"
              :x-range="velocity ? null : xRange"
              @relayout="onRelayout"
            />
          </div>
          <footer
            class="flex h-6 items-center border-t px-3 font-mono text-[11px] text-muted-foreground"
          >
            <span v-if="series" data-testid="viewer-points">
              {{ t('viewer.points_shown', { shown: series.wave.length, total: series.n }) }}
            </span>
          </footer>
        </template>

        <!-- Image -->
        <div v-else-if="renderer === 'image-thumb'" class="min-h-0 flex-1">
          <ImageView v-model:options="renderOptions" :tile="tile" :wcs="wcs" :unit="unit" />
          <p v-if="!fullTile" class="px-3 py-1 text-[11px] text-muted-foreground">
            {{ t('viewer.loading_full') }}
          </p>
        </div>

        <!-- Cube: white light + band selection -->
        <template v-else-if="renderer === 'cube-thumb'">
          <div class="flex flex-wrap items-center gap-2 border-b px-3 py-1 text-xs">
            <span class="text-muted-foreground">{{ t('viewer.band_select') }}</span>
            <span class="font-mono" data-testid="viewer-band">
              {{
                band
                  ? t('preview.band', { lo: band[0].toFixed(1), hi: band[1].toFixed(1) })
                  : t('preview.white_light')
              }}
            </span>
            <button
              v-if="band"
              type="button"
              class="rounded border px-1.5 hover:bg-muted"
              @click="requestCubeBand(null)"
            >
              {{ t('viewer.band_reset') }}
            </button>
          </div>
          <div class="grid min-h-0 flex-1 grid-rows-[1fr_auto]">
            <ImageView v-model:options="renderOptions" :tile="tile" :wcs="wcs" :unit="unit" />
            <div class="border-t p-2">
              <UPlotLine
                :series="cubeSpectrum"
                :height="120"
                :axes="true"
                :show-error="false"
                :show-continuum="false"
                @view-change="(range) => requestCubeBand(range)"
              />
            </div>
          </div>
        </template>

        <!-- Table -->
        <div v-else-if="renderer === 'table-head'" class="min-h-0 flex-1">
          <DataTable :arrow="arrow" :head="head" :units="head?.units ?? {}" />
        </div>

        <!-- Figure -->
        <div v-else-if="renderer === 'figure'" class="min-h-0 flex-1 p-2">
          <img v-if="png" :src="png" alt="" class="mx-auto max-h-full object-contain" />
          <PlotlyView v-else-if="figure" :figure="figure" />
          <p v-else class="p-4 text-xs text-muted-foreground">{{ t('common.loading') }}</p>
        </div>

        <!-- rbcodes renderers (curves, candidate tables, stacks, moment maps) at full width -->
        <div
          v-else-if="scaled"
          class="min-h-0 flex-1 overflow-auto p-3"
          data-testid="viewer-scaled"
        >
          <component
            :is="previewComponent(renderer)"
            :node-id="target!.nodeId"
            :port="target!.port"
            :type-id="typeId"
            :summary="scaledSummary"
            :width="SCALED_WIDTH"
          />
        </div>

        <!-- Everything else -->
        <div v-else class="min-h-0 flex-1 overflow-auto p-4">
          <KeyValueTile :data="kvData" />
          <pre class="mt-3 rounded bg-muted p-2 font-mono text-[11px] whitespace-pre-wrap">{{
            JSON.stringify(thumb?.summary ?? {}, null, 2)
          }}</pre>
        </div>

        <p v-if="loadError" class="border-t px-3 py-1 text-xs text-destructive">{{ loadError }}</p>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
