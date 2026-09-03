<script setup lang="ts">
/**
 * `multispec-viewer` editor for `rbcodes.multispec.view`: rb_multispec on the canvas.
 *
 * N stacked panels share one wavelength axis; the toolbar carries the redshift (typed, slid, or
 * snapped from a connected `Redshift`), the overlay line list (rbcodes' 16 atomic lists, the 5
 * curated zfind presets and any list wired into `extra_lines`), "add absorber at z", the quick
 * fits and the velocity stack. Clicking a feature identifies the nearest transition of the
 * current list at the current redshift and appends it to the line table; Apply writes the two
 * catalogues, the redshift, the list and the display settings back to the node's parameters.
 *
 * Keyboard parity with rb_multispec where it makes sense in a browser - see `SHORTCUTS`.
 */
import { computed, onBeforeUnmount, onMounted, ref, toRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { Button } from '@/components/ui/button'
import { useExecutionStore } from '@/stores/execution'
import { useSessionStore } from '@/stores/session'
import { useWorkflowStore } from '@/stores/workflow'
import type { SpectrumSeries } from '@/widgets/spectrumSeries'

import MultispecPanel, { type PanelMarker } from './MultispecPanel.vue'
import {
  type AbsorberRow,
  type IdentifiedRow,
  type QuickFit,
  LINE_LIST_OPTIONS,
  SHORTCUTS,
  absorbersFromTable,
  cssColor,
  fitCom,
  fitGaussian,
  formatWave,
  formatZabs,
  identifiedFromTable,
  identifyAt,
  nextColor,
  overallRange,
  panelsFromCollection,
  quickIdRedshift,
  velocityPanels,
} from './multispec'
import { EDITOR_TAG, type EditorProps } from './registry'
import { useUpstream } from './useUpstream'
import { CURATED_LINELISTS, type LineEntry, curatedLinesFromSummary, lineTicks } from './zAccept'

const ATOMIC_NODE = 'rbcodes.lines.line_list'
const CURATED_NODE = 'rbcodes.zfind.curated_linelist'
const PANEL_POINTS = 4000
const MAX_PANELS = 32
const OVERLAY_COLOR = '#0EA5E9'
const ABSORPTION_COLOR = '#D64545'
const SMOOTH_STEP = 2
const MAX_SMOOTH = 51

const props = defineProps<EditorProps>()
const emit = defineEmits<{ close: [] }>()

const { t } = useI18n()
const workflow = useWorkflowStore()
const execution = useExecutionStore()
const session = useSessionStore()
const nodeId = toRef(props, 'nodeId')

const node = computed(() => workflow.nodes[props.nodeId])
const params = computed<Record<string, unknown>>(() => node.value?.params ?? {})

// --- inputs -----------------------------------------------------------------------------------

const spectra = useUpstream(nodeId, 'spectra', { n_out: PANEL_POINTS, max_items: MAX_PANELS })
const absorberSeed = useUpstream(nodeId, 'absorber_seed', { rows: 500 })
const lineSeed = useUpstream(nodeId, 'line_seed', { rows: 1000 })
const extraA = useUpstream(nodeId, 'extra_lines', { rows: 2000 })
const extraB = useUpstream(nodeId, 'extra_lines_2', { rows: 2000 })
const redshiftIn = useUpstream(nodeId, 'redshift')

const stack = computed(() => panelsFromCollection(spectra.entry.value?.summary))
const panels = computed<SpectrumSeries[]>(() => stack.value.panels)
const labels = computed<string[]>(() =>
  panels.value.map((_, i) => stack.value.labels[i] ?? t('editor.multispec.panel', { n: i + 1 })),
)
const dataRange = computed(() => overallRange(panels.value))
const upstreamZ = computed<number | null>(() => {
  const value = redshiftIn.data.value?.['z']
  return typeof value === 'number' ? value : null
})

// --- editable state ----------------------------------------------------------------------------

function paramNumber(key: string, fallback: number): number {
  const value = params.value[key]
  return typeof value === 'number' ? value : fallback
}

const z = ref(paramNumber('z', 0))
const lastZ = ref<number | null>(null)
const linelist = ref(
  typeof params.value['linelist'] === 'string' ? params.value['linelist'] : 'LLS',
)
const absorbers = ref<AbsorberRow[]>([])
const identified = ref<IdentifiedRow[]>([])
const smoothPixels = ref(1)
const showLabels = ref(true)
const showError = ref(true)
const waveWindow = ref<[number, number] | null>(null)
const dirty = ref(false)

/** Seed from the node's parameters, falling back to the connected tables. */
function seed(): void {
  const raw = params.value
  const display = (raw['display'] ?? {}) as Record<string, unknown>
  z.value = paramNumber('z', 0)
  linelist.value = typeof raw['linelist'] === 'string' ? raw['linelist'] : 'LLS'
  smoothPixels.value = typeof display['smooth_pixels'] === 'number' ? display['smooth_pixels'] : 1
  showLabels.value = display['show_labels'] !== false
  showError.value = display['show_error'] !== false
  const lo = display['wave_min']
  const hi = display['wave_max']
  waveWindow.value = typeof lo === 'number' && typeof hi === 'number' ? [lo, hi] : null
  const catalog = Array.isArray(raw['catalog']) ? raw['catalog'] : []
  const lines = Array.isArray(raw['identifications']) ? raw['identifications'] : []
  absorbers.value = catalog.length
    ? absorbersFromTable({ head: columnsOf(catalog) })
    : absorbersFromTable(absorberSeed.entry.value?.summary)
  identified.value = lines.length
    ? identifiedFromTable({ head: columnsOf(lines) })
    : identifiedFromTable(lineSeed.entry.value?.summary)
  dirty.value = false
}

/** Parameter lists are arrays of objects; the table parsers want parallel columns. */
function columnsOf(rows: unknown[]): Record<string, unknown[]> {
  const out: Record<string, unknown[]> = {}
  rows.forEach((raw, index) => {
    if (typeof raw !== 'object' || raw === null) return
    for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
      const column = (out[key] ??= [])
      column[index] = value
    }
  })
  return out
}

onMounted(seed)
// Follow the seeds while the user has not edited anything yet.
watch([() => absorberSeed.entry.value, () => lineSeed.entry.value], () => {
  if (!dirty.value) seed()
})

function touch(): void {
  dirty.value = true
}

// --- line lists ---------------------------------------------------------------------------------

const extraNames = computed(() =>
  [extraA, extraB]
    .map((u) => u.entry.value?.summary)
    .filter((s): s is Record<string, unknown> => Boolean(s))
    .map((s) => (typeof s['source'] === 'string' ? s['source'] : 'custom')),
)
const listOptions = computed<string[]>(() => [
  ...LINE_LIST_OPTIONS,
  ...CURATED_LINELISTS,
  ...extraNames.value.filter((n) => !LINE_LIST_OPTIONS.includes(n)),
])

function listNode(name: string): string {
  return CURATED_LINELISTS.includes(name) ? CURATED_NODE : ATOMIC_NODE
}

function listKey(name: string): string {
  return `type:${listNode(name)}`
}

function listTag(name: string): string {
  return `${EDITOR_TAG}-list:${name}`
}

const requested = new Set<string>()

function loadList(name: string): void {
  if (name === 'None' || requested.has(name)) return
  // A list wired into extra_lines is already in the store.
  const local = [extraA, extraB].find((u) => (u.entry.value?.summary?.['source'] ?? '') === name)
  if (local) return
  if (!LINE_LIST_OPTIONS.includes(name) && !CURATED_LINELISTS.includes(name)) return
  requested.add(name)
  session.requestCompute({
    node_type: listNode(name),
    params: { name },
    tag: listTag(name),
    viewport: { rows: 2000 },
  })
}

function linesOf(name: string): LineEntry[] {
  if (name === 'None') return []
  const local = [extraA, extraB].find((u) => (u.entry.value?.summary?.['source'] ?? '') === name)
  if (local?.entry.value) return curatedLinesFromSummary(local.entry.value.summary)
  return curatedLinesFromSummary(execution.view(listKey(name), 'out', listTag(name))?.summary)
}

const overlayLines = computed(() => linesOf(linelist.value))

/** Every list the overlay and the visible absorbers need. */
const neededLists = computed(() => {
  const names = new Set<string>([linelist.value])
  for (const absorber of absorbers.value) if (absorber.visible) names.add(absorber.linelist)
  return [...names]
})
watch(neededLists, (names) => names.forEach(loadList), { immediate: true })

// --- markers ---------------------------------------------------------------------------------

const xRange = computed<[number, number] | null>(() => waveWindow.value ?? dataRange.value)

const markers = computed<PanelMarker[]>(() => {
  const range = xRange.value
  const out: PanelMarker[] = []
  for (const tick of lineTicks(overlayLines.value, z.value, range)) {
    out.push({
      x: tick.x,
      label: tick.name,
      color: tick.kind === 'absorption' ? ABSORPTION_COLOR : OVERLAY_COLOR,
      dash: tick.kind === 'absorption',
    })
  }
  for (const absorber of absorbers.value) {
    if (!absorber.visible) continue
    const color = cssColor(absorber.color)
    for (const tick of lineTicks(linesOf(absorber.linelist), absorber.zabs, range)) {
      out.push({ x: tick.x, label: tick.name, color, dash: true })
    }
  }
  return out
})

const identifiedMarkers = computed<PanelMarker[]>(() =>
  identified.value.map((line) => ({ x: line.waveObs, label: line.name, color: '#F59E0B' })),
)
const allMarkers = computed(() => [...markers.value, ...identifiedMarkers.value])

// --- cursor, panels, keyboard -------------------------------------------------------------------

/** Panels share the stack's height, within rb_multispec-ish bounds. */
const MIN_PANEL = 110
const MAX_PANEL = 260
const stackEl = ref<HTMLDivElement | null>(null)
const stackHeight = ref(0)
const panelHeight = computed(() => {
  const n = Math.max(1, panels.value.length)
  if (!stackHeight.value) return MIN_PANEL
  return Math.min(MAX_PANEL, Math.max(MIN_PANEL, Math.floor(stackHeight.value / n) - 2))
})

const activePanel = ref(0)
const cursor = ref<{ x: number; y: number }>({ x: Number.NaN, y: Number.NaN })
const yRanges = ref<Record<number, [number, number] | null>>({})
const status = ref('')

function say(message: string): void {
  status.value = message
}

function onHover(index: number, x: number, y: number): void {
  activePanel.value = index
  cursor.value = { x, y }
}

function panelSeries(index: number): SpectrumSeries | null {
  return panels.value[index] ?? null
}

function resetView(): void {
  waveWindow.value = null
  yRanges.value = {}
  say(t('editor.multispec.status.reset'))
}

function setXLimit(side: 'min' | 'max'): void {
  const range = xRange.value
  const x = cursor.value.x
  if (!range || !Number.isFinite(x)) return
  waveWindow.value = side === 'min' ? [x, range[1]] : [range[0], x]
  touch()
}

function setYLimit(side: 'min' | 'max'): void {
  const y = cursor.value.y
  const index = activePanel.value
  if (!Number.isFinite(y)) return
  const current = yRanges.value[index] ?? fallbackY(index)
  yRanges.value = {
    ...yRanges.value,
    [index]: side === 'min' ? [y, current[1]] : [current[0], y],
  }
}

function fallbackY(index: number): [number, number] {
  const series = panelSeries(index)
  if (!series) return [0, 1]
  let lo = Number.POSITIVE_INFINITY
  let hi = Number.NEGATIVE_INFINITY
  for (let i = 0; i < series.flux.length; i += 1) {
    const f = series.flux[i]
    if (f === undefined || !Number.isFinite(f)) continue
    if (f < lo) lo = f
    if (f > hi) hi = f
  }
  return lo <= hi ? [lo, hi] : [0, 1]
}

function autoscale(all: boolean): void {
  if (all) yRanges.value = {}
  else yRanges.value = { ...yRanges.value, [activePanel.value]: null }
  say(t('editor.multispec.status.autoscale'))
}

function page(direction: -1 | 1): void {
  const range = xRange.value
  if (!range) return
  const width = range[1] - range[0]
  waveWindow.value = [range[0] + direction * width, range[1] + direction * width]
  touch()
}

function zoomOut(): void {
  const range = xRange.value
  if (!range) return
  const centre = (range[0] + range[1]) / 2
  const half = (range[1] - centre) * 1.5
  waveWindow.value = [centre - half, centre + half]
  touch()
}

function smoothBy(delta: number): void {
  let next = smoothPixels.value + delta
  if (next % 2 === 0) next += delta > 0 ? 1 : -1
  smoothPixels.value = Math.min(MAX_SMOOTH, Math.max(1, next))
  touch()
  say(t('editor.multispec.status.smooth', { n: smoothPixels.value }))
}

function setZ(next: number, note?: string): void {
  if (Number.isFinite(z.value)) lastZ.value = z.value
  z.value = next
  touch()
  if (note) say(note)
}

function swapZ(): void {
  const previous = lastZ.value
  if (previous === null) {
    say(t('editor.multispec.status.no_last_z'))
    return
  }
  lastZ.value = z.value
  z.value = previous
  touch()
  say(t('editor.multispec.status.z', { z: formatZabs(previous) }))
}

function snapRedshift(): void {
  const value = upstreamZ.value
  if (value === null) return
  setZ(value, t('editor.multispec.status.z', { z: formatZabs(value) }))
}

// --- absorbers and identifications ----------------------------------------------------------------

function addAbsorber(): void {
  absorbers.value = [
    ...absorbers.value,
    {
      zabs: z.value,
      linelist: linelist.value === 'None' ? 'LLS' : linelist.value,
      color: nextColor(absorbers.value.length),
      visible: true,
      label: '',
    },
  ]
  touch()
  say(t('editor.multispec.status.absorber_added', { z: formatZabs(z.value) }))
}

function removeAbsorber(index: number): void {
  absorbers.value = absorbers.value.filter((_, i) => i !== index)
  touch()
}

function updateAbsorber(index: number, patch: Partial<AbsorberRow>): void {
  absorbers.value = absorbers.value.map((row, i) => (i === index ? { ...row, ...patch } : row))
  touch()
}

function removeLine(index: number): void {
  identified.value = identified.value.filter((_, i) => i !== index)
  touch()
}

function clearOverlays(): void {
  fit.value = null
  anchor.value = null
  fitMode.value = null
  say(t('editor.multispec.status.cleared'))
}

function identify(x: number, index: number): void {
  const match = identifyAt(overlayLines.value, x, z.value)
  if (!match) {
    say(t('editor.multispec.status.no_lines'))
    return
  }
  identified.value = [
    ...identified.value,
    {
      name: match.line.name,
      waveObs: match.waveObs,
      zabs: z.value,
      waveRest: match.line.wrest,
      spectrum: labels.value[index] ?? '',
    },
  ]
  touch()
  say(
    t('editor.multispec.status.identified', {
      name: match.line.name,
      wave: formatWave(match.waveObs),
      dv: match.deltaKms.toFixed(0),
    }),
  )
}

function quickId(key: string): void {
  const x = cursor.value.x
  const match = quickIdRedshift(key, x)
  if (!match) return
  setZ(
    match.z,
    t('editor.multispec.status.quick_id', { species: match.species, z: formatZabs(match.z) }),
  )
}

// --- quick fits ------------------------------------------------------------------------------------

const fitMode = ref<'gaussian' | 'com' | null>(null)
const anchor = ref<{ x: number; y: number } | null>(null)
const fit = ref<QuickFit | null>(null)
const fitPanel = ref(0)
const fitError = ref<string | null>(null)

function armFit(kind: 'gaussian' | 'com'): void {
  fitMode.value = fitMode.value === kind ? null : kind
  anchor.value = null
  fitError.value = null
  say(fitMode.value ? t('editor.multispec.status.fit_armed') : '')
}

/** rb_multispec's `g`+`g` / `c`+`c`: the first press anchors, the second fits. */
function fitKey(kind: 'gaussian' | 'com'): void {
  const { x, y } = cursor.value
  if (!Number.isFinite(x)) return
  if (fitMode.value !== kind || !anchor.value) {
    fitMode.value = kind
    anchor.value = { x, y }
    fitError.value = null
    say(t('editor.multispec.status.fit_anchor', { wave: formatWave(x) }))
    return
  }
  runFit(kind, anchor.value, { x, y }, activePanel.value)
}

function onPanelClick(index: number, x: number, y: number): void {
  activePanel.value = index
  if (!fitMode.value) {
    identify(x, index)
    return
  }
  if (!anchor.value) {
    anchor.value = { x, y }
    say(t('editor.multispec.status.fit_anchor', { wave: formatWave(x) }))
    return
  }
  runFit(fitMode.value, anchor.value, { x, y }, index)
}

function runFit(
  kind: 'gaussian' | 'com',
  a: { x: number; y: number },
  b: { x: number; y: number },
  index: number,
): void {
  const series = panelSeries(index)
  anchor.value = null
  fitMode.value = null
  if (!series) return
  try {
    fit.value = kind === 'gaussian' ? fitGaussian(series, a, b) : fitCom(series, a, b)
    fitPanel.value = index
    fitError.value = null
    say(t('editor.multispec.status.fit_done', { wave: formatWave(fit.value.centroid) }))
  } catch (err) {
    fit.value = null
    fitError.value = err instanceof Error ? err.message : String(err)
  }
}

/** A horizontal drag fits between the flux values at the two edges (no second click needed). */
function onPanelSelect(index: number, lo: number, hi: number): void {
  const series = panelSeries(index)
  if (!series) return
  const kind = fitMode.value ?? 'gaussian'
  runFit(kind, { x: lo, y: fluxAt(series, lo) }, { x: hi, y: fluxAt(series, hi) }, index)
}

function fluxAt(series: SpectrumSeries, x: number): number {
  let best = 0
  let bestDelta = Number.POSITIVE_INFINITY
  for (let i = 0; i < series.wave.length; i += 1) {
    const w = series.wave[i]
    const f = series.flux[i]
    if (w === undefined || f === undefined || !Number.isFinite(f)) continue
    const delta = Math.abs(w - x)
    if (delta < bestDelta) {
      bestDelta = delta
      best = f
    }
  }
  return best
}

function identifyFit(): void {
  const current = fit.value
  if (!current) return
  identify(current.centroid, fitPanel.value)
}

// --- velocity stack --------------------------------------------------------------------------------

const showVStack = ref(false)
const showHelp = ref(false)
const vstack = computed(() => {
  const series = panelSeries(activePanel.value)
  if (!showVStack.value || !series) return []
  return velocityPanels(series, overlayLines.value, z.value, -1000, 1000, 12)
})

function vstackPath(panel: { velocity: number[]; flux: number[] }): string {
  let lo = Number.POSITIVE_INFINITY
  let hi = Number.NEGATIVE_INFINITY
  for (const f of panel.flux) {
    if (!Number.isFinite(f)) continue
    if (f < lo) lo = f
    if (f > hi) hi = f
  }
  if (!(lo < hi)) return ''
  const parts: string[] = []
  for (let i = 0; i < panel.velocity.length; i += 1) {
    const x = (((panel.velocity[i] ?? 0) + 1000) / 2000) * 200
    const y = 32 - ((((panel.flux[i] ?? lo) - lo) / (hi - lo)) * 30 + 1)
    parts.push(`${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`)
  }
  return parts.join(' ')
}

// --- keyboard --------------------------------------------------------------------------------------

function onKey(event: KeyboardEvent): void {
  const target = event.target as HTMLElement | null
  if (target && ['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName)) return
  const key = event.key
  const handlers: Record<string, () => void> = {
    r: resetView,
    R: clearOverlays,
    x: () => setXLimit('min'),
    X: () => setXLimit('max'),
    t: () => setYLimit('max'),
    b: () => setYLimit('min'),
    a: () => autoscale(true),
    A: addAbsorber,
    '[': () => page(-1),
    ']': () => page(1),
    o: zoomOut,
    S: () => smoothBy(SMOOTH_STEP),
    U: () => smoothBy(-SMOOTH_STEP),
    L: () => {
      showLabels.value = !showLabels.value
      touch()
    },
    Z: swapZ,
    v: () => {
      showVStack.value = !showVStack.value
    },
    g: () => fitKey('gaussian'),
    c: () => fitKey('com'),
    '?': () => {
      showHelp.value = !showHelp.value
    },
    h: () => {
      showHelp.value = !showHelp.value
    },
  }
  const handler = handlers[key]
  if (handler) {
    event.preventDefault()
    handler()
    return
  }
  if (quickIdRedshift(key, cursor.value.x)) {
    event.preventDefault()
    quickId(key)
  }
}

const root = ref<HTMLDivElement | null>(null)
let stackObserver: ResizeObserver | null = null
onMounted(() => {
  root.value?.focus()
  const el = stackEl.value
  if (el && typeof ResizeObserver !== 'undefined') {
    stackHeight.value = el.clientHeight
    stackObserver = new ResizeObserver(() => {
      stackHeight.value = el.clientHeight
    })
    stackObserver.observe(el)
  }
})
onBeforeUnmount(() => {
  stackObserver?.disconnect()
  for (const name of requested) execution.clearTag(listKey(name), listTag(name))
})

// --- apply -----------------------------------------------------------------------------------------

function apply(): void {
  if (!node.value) return
  workflow.setParams(props.nodeId, {
    z: z.value,
    linelist: linelist.value,
    catalog: absorbers.value.map((row) => ({
      zabs: row.zabs,
      linelist: row.linelist,
      color: row.color,
      visible: row.visible,
      label: row.label,
    })),
    identifications: identified.value.map((row) => ({
      name: row.name,
      wave_obs: row.waveObs,
      zabs: row.zabs,
      wave_rest: row.waveRest,
      spectrum: row.spectrum,
    })),
    display: {
      wave_min: waveWindow.value?.[0] ?? null,
      wave_max: waveWindow.value?.[1] ?? null,
      smooth_pixels: smoothPixels.value,
      show_error: showError.value,
      show_labels: showLabels.value,
    },
  })
  emit('close')
}

function onLinelist(event: Event): void {
  linelist.value = (event.target as HTMLSelectElement).value
  touch()
}

function onZInput(event: Event): void {
  const value = Number.parseFloat((event.target as HTMLInputElement).value)
  if (Number.isFinite(value)) setZ(value)
}
</script>

<template>
  <div
    ref="root"
    class="flex h-full min-h-0 flex-col gap-2 outline-none"
    data-testid="editor-multispec"
    :data-panels="panels.length"
    tabindex="0"
    @keydown="onKey"
  >
    <div class="flex flex-wrap items-center gap-2 text-xs">
      <label class="flex items-center gap-1">
        <span class="text-muted-foreground">z</span>
        <input
          type="number"
          step="0.0001"
          class="h-7 w-28 rounded border bg-background px-1 font-mono"
          data-testid="multispec-z"
          :value="z"
          @change="onZInput"
        />
      </label>
      <input
        type="range"
        class="w-40"
        min="0"
        max="5"
        step="0.0001"
        data-testid="multispec-z-slider"
        :value="z"
        @input="onZInput"
      />
      <Button
        v-if="upstreamZ !== null"
        size="sm"
        variant="outline"
        data-testid="multispec-snap"
        @click="snapRedshift"
      >
        {{ t('editor.multispec.snap', { z: formatZabs(upstreamZ) }) }}
      </Button>
      <select
        class="h-7 rounded border bg-background px-1"
        data-testid="multispec-linelist"
        :value="linelist"
        @change="onLinelist"
      >
        <option v-for="name in listOptions" :key="name" :value="name">{{ name }}</option>
      </select>
      <Button size="sm" variant="outline" data-testid="multispec-add-absorber" @click="addAbsorber">
        {{ t('editor.multispec.add_absorber') }}
      </Button>
      <Button
        size="sm"
        :variant="fitMode === 'gaussian' ? 'default' : 'outline'"
        data-testid="multispec-fit-gaussian"
        @click="armFit('gaussian')"
      >
        {{ t('editor.multispec.fit_gaussian') }}
      </Button>
      <Button
        size="sm"
        :variant="fitMode === 'com' ? 'default' : 'outline'"
        data-testid="multispec-fit-com"
        @click="armFit('com')"
      >
        {{ t('editor.multispec.fit_com') }}
      </Button>
      <Button size="sm" variant="ghost" data-testid="multispec-reset" @click="resetView">
        {{ t('editor.multispec.reset') }}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        data-testid="multispec-vstack"
        :aria-pressed="showVStack"
        @click="showVStack = !showVStack"
      >
        {{ t('editor.multispec.vstack') }}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        data-testid="multispec-help"
        :aria-pressed="showHelp"
        @click="showHelp = !showHelp"
      >
        {{ t('editor.multispec.help') }}
      </Button>
      <span class="ml-auto font-mono text-muted-foreground" data-testid="multispec-status">
        {{ status }}
      </span>
    </div>

    <div class="grid min-h-0 flex-1 grid-cols-[1fr_21rem] gap-3">
      <div ref="stackEl" class="min-h-0 overflow-auto pr-1" data-testid="multispec-stack">
        <MultispecPanel
          v-for="(panel, index) in panels"
          :key="index"
          :series="panel"
          :markers="allMarkers"
          :model="fit && fitPanel === index ? fit.model : null"
          :x-range="xRange"
          :y-range="yRanges[index] ?? null"
          :show-error="showError"
          :show-labels="showLabels"
          :height="panelHeight"
          :show-axis="index === panels.length - 1"
          :label="labels[index]"
          @hover="(x, y) => onHover(index, x, y)"
          @click="(x, y) => onPanelClick(index, x, y)"
          @select="(lo, hi) => onPanelSelect(index, lo, hi)"
        />
        <p v-if="!panels.length" class="p-4 text-xs text-muted-foreground">
          {{ spectra.source.value ? t('editor.waiting_upstream') : t('editor.no_input') }}
        </p>
        <p
          v-else-if="stack.count > panels.length"
          class="p-1 text-[10px] text-muted-foreground"
          data-testid="multispec-truncated"
        >
          {{ t('editor.multispec.truncated', { shown: panels.length, total: stack.count }) }}
        </p>
      </div>

      <aside class="flex min-h-0 flex-col gap-3 overflow-auto text-xs">
        <section v-if="showHelp" data-testid="multispec-shortcuts">
          <h3 class="mb-1 text-[10px] font-medium text-muted-foreground uppercase">
            {{ t('editor.multispec.shortcuts') }}
          </h3>
          <dl class="grid grid-cols-[6rem_1fr] gap-x-2">
            <template v-for="row in SHORTCUTS" :key="row.id">
              <dt class="font-mono">{{ row.keys }}</dt>
              <dd class="text-muted-foreground">{{ t(`editor.multispec.keys.${row.id}`) }}</dd>
            </template>
          </dl>
        </section>

        <section>
          <h3 class="mb-1 text-[10px] font-medium text-muted-foreground uppercase">
            {{ t('editor.multispec.absorbers') }}
          </h3>
          <table
            v-if="absorbers.length"
            class="w-full"
            data-testid="multispec-absorbers"
            :data-count="absorbers.length"
          >
            <tbody>
              <tr v-for="(row, index) in absorbers" :key="index" data-testid="multispec-absorber">
                <td>
                  <input
                    type="checkbox"
                    :checked="row.visible"
                    :aria-label="t('editor.multispec.visible')"
                    data-testid="multispec-absorber-visible"
                    @change="
                      updateAbsorber(index, {
                        visible: ($event.target as HTMLInputElement).checked,
                      })
                    "
                  />
                </td>
                <td class="font-mono" :data-zabs="row.zabs">{{ formatZabs(row.zabs) }}</td>
                <td>
                  <select
                    class="h-6 w-24 rounded border bg-background"
                    :value="row.linelist"
                    data-testid="multispec-absorber-list"
                    @change="
                      updateAbsorber(index, {
                        linelist: ($event.target as HTMLSelectElement).value,
                      })
                    "
                  >
                    <option v-for="name in LINE_LIST_OPTIONS" :key="name" :value="name">
                      {{ name }}
                    </option>
                  </select>
                </td>
                <td>
                  <span
                    class="inline-block h-3 w-3 rounded-full align-middle"
                    :style="{ background: cssColor(row.color) }"
                    :title="row.color"
                  />
                </td>
                <td class="text-right">
                  <button
                    type="button"
                    class="text-muted-foreground hover:text-destructive"
                    :aria-label="t('editor.multispec.remove')"
                    data-testid="multispec-absorber-remove"
                    @click="removeAbsorber(index)"
                  >
                    x
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else class="text-muted-foreground">{{ t('editor.multispec.no_absorbers') }}</p>
        </section>

        <section class="min-h-0">
          <h3 class="mb-1 text-[10px] font-medium text-muted-foreground uppercase">
            {{ t('editor.multispec.identified') }}
          </h3>
          <table
            v-if="identified.length"
            class="w-full"
            data-testid="multispec-lines"
            :data-count="identified.length"
          >
            <thead class="text-left text-[10px] text-muted-foreground">
              <tr>
                <th>{{ t('editor.multispec.line') }}</th>
                <th class="text-right">{{ t('editor.axis_wavelength') }}</th>
                <th class="text-right">z</th>
                <th />
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in identified" :key="index" data-testid="multispec-line">
                <td class="max-w-[7rem] truncate" :title="row.name">{{ row.name }}</td>
                <td class="text-right font-mono">{{ formatWave(row.waveObs) }}</td>
                <td class="text-right font-mono">{{ formatZabs(row.zabs) }}</td>
                <td class="text-right">
                  <button
                    type="button"
                    class="text-muted-foreground hover:text-destructive"
                    :aria-label="t('editor.multispec.remove')"
                    data-testid="multispec-line-remove"
                    @click="removeLine(index)"
                  >
                    x
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else class="text-muted-foreground">{{ t('editor.multispec.no_lines') }}</p>
        </section>

        <section v-if="fit || fitError" data-testid="multispec-fit">
          <h3 class="mb-1 text-[10px] font-medium text-muted-foreground uppercase">
            {{ t('editor.multispec.fit') }}
          </h3>
          <p v-if="fitError" class="text-destructive">{{ fitError }}</p>
          <template v-else-if="fit">
            <p class="font-mono" :data-centroid="fit.centroid">
              {{ formatWave(fit.centroid) }} A - {{ fit.fwhmAng.toFixed(3) }} A /
              {{ fit.fwhmKms.toFixed(0) }} km/s
            </p>
            <p class="text-muted-foreground">
              {{
                t(`editor.multispec.direction.${fit.direction === 1 ? 'emission' : 'absorption'}`)
              }}
              · {{ fit.kind }} · {{ t('editor.multispec.pixels', { n: fit.nPixels }) }}
              <span v-if="fit.asymmetric"> · {{ t('editor.multispec.asymmetric') }}</span>
            </p>
            <Button
              size="sm"
              variant="outline"
              class="mt-1"
              data-testid="multispec-fit-identify"
              @click="identifyFit"
            >
              {{ t('editor.multispec.identify_fit') }}
            </Button>
          </template>
        </section>

        <section v-if="showVStack" data-testid="multispec-vstack-panel">
          <h3 class="mb-1 text-[10px] font-medium text-muted-foreground uppercase">
            {{ t('editor.multispec.vstack_title', { z: formatZabs(z) }) }}
          </h3>
          <p v-if="!vstack.length" class="text-muted-foreground">
            {{ t('editor.multispec.no_vstack') }}
          </p>
          <div
            v-for="panel in vstack"
            :key="panel.wrest"
            class="mb-1"
            data-testid="multispec-vstack-item"
          >
            <div class="flex justify-between text-[10px] text-muted-foreground">
              <span>{{ panel.name }}</span>
              <span class="font-mono">{{ panel.wrest.toFixed(1) }}</span>
            </div>
            <svg viewBox="0 0 200 32" class="block w-full rounded bg-muted/40" height="32">
              <line x1="100" x2="100" y1="0" y2="32" stroke="#F59E0B" stroke-width="0.7" />
              <path :d="vstackPath(panel)" fill="none" stroke="#5B8DEF" stroke-width="0.8" />
            </svg>
          </div>
        </section>
      </aside>
    </div>

    <div class="flex items-center justify-end gap-2 border-t pt-2">
      <span class="mr-auto text-xs text-muted-foreground">
        {{
          t('editor.multispec.summary', {
            absorbers: absorbers.length,
            lines: identified.length,
          })
        }}
      </span>
      <Button size="sm" :disabled="!dirty" data-testid="editor-apply" @click="apply">
        {{ t('editor.apply') }}
      </Button>
    </div>
  </div>
</template>
