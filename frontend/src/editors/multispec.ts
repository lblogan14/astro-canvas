/**
 * Pure helpers for the `multispec-viewer` editor (`rbcodes.multispec.view`) and the
 * `multispec-thumb` preview: parse the node's tables and its `rbcodes.MultispecView` summary,
 * place line ticks at a redshift, identify the nearest transition of a list, run the quick fits
 * in the browser and slice velocity panels for the vStack side panel.
 *
 * The quick fits mirror `kernels/line_fit.py` (rbcodes' `LineFitter`) so the overlay the editor
 * draws matches what `rbcodes.multispec.quick_fit` computes on the server.
 */
import type { LineEntry } from '@/editors/zAccept'
import { type SpectrumSeries, seriesFromSummary } from '@/widgets/spectrumSeries'

/** `LineFitter`'s speed of light (it writes 2.998e5, not rbcodes' 2.9979e5). */
export const C_FIT = 2.998e5
/** `LineFitter`'s Gaussian FWHM factor. */
export const FWHM_PER_SIGMA = 2.3548
const ASYMMETRY_FRACTION = 0.2

export interface AbsorberRow {
  zabs: number
  linelist: string
  color: string
  visible: boolean
  label: string
}

export interface IdentifiedRow {
  name: string
  waveObs: number
  zabs: number
  waveRest: number
  spectrum: string
}

export interface MultispecSummary {
  count: number
  labels: string[]
  range: [number, number] | null
  z: number
  linelist: string
  panels: SpectrumSeries[]
  absorbers: AbsorberRow[]
  identified: IdentifiedRow[]
}

/** rb_multispec's absorber colour names mapped to CSS colours (`rb_utility.rb_set_color`). */
export const ABSORBER_COLORS: Readonly<Record<string, string>> = {
  sky_blue: '#56B4E9',
  orange: '#E69F00',
  light_lime_green: '#99FF99',
  vermillion: '#D55E00',
  reddish_purple: '#CC79A7',
  cyan: '#00FFFF',
  gold: '#FFD700',
  coral: '#FF804F',
  lavender: '#B3B3FF',
  mint: '#AAFFD1',
  slate_gray: '#708090',
  rose: '#FF66B3',
  blue2: '#0072B2',
  bluish_green: '#009E73',
  yellow: '#F0E442',
  dark_orange: '#FF8033',
  purple_wordle: '#CC00FF',
  light_purple: '#E771FF',
  orange2: '#D96E00',
  light_orange: '#E9AC37',
  teal: '#3E85B5',
  pale_red: '#FF766E',
  pale_cyan: '#85F9FF',
  pale_lime_green: '#C8FFC8',
  dark_red: '#640000',
  dark_green: '#006400',
  dark_blue: '#000064',
  gray: '#808080',
  red: '#FF0000',
  green: '#00FF00',
  blue: '#0000FF',
}

/** The colour names in the order `reconcile_linelists` and the viewer cycle through them. */
export const COLOR_NAMES: readonly string[] = Object.keys(ABSORBER_COLORS)

/** rb_multispec's per-absorber line-list options (`line_options.conf`). */
export const LINE_LIST_OPTIONS: readonly string[] = [
  'None',
  'LLS',
  'LLS Small',
  'DLA',
  'LBG',
  'Gal',
  'Eiger_Strong',
  'AGN',
  'Gal_Abs',
  'Gal_Em',
  'Gal_long',
  'HI_recomb_light',
  'HI_recomb',
  'HI',
  'EUV',
  'LLS_EUV',
  'atom',
]

/**
 * rb_multispec's keys that make sense in a browser, shown in the editor's help panel; the
 * descriptions live in `editor.multispec.keys.*`.
 */
export const SHORTCUTS: ReadonlyArray<{ keys: string; id: string }> = [
  { keys: 'r', id: 'reset' },
  { keys: 'x / X', id: 'xlim' },
  { keys: 't / b', id: 'ylim' },
  { keys: 'a / A', id: 'autoscale' },
  { keys: '[ / ]', id: 'page' },
  { keys: 'o', id: 'zoomout' },
  { keys: 'S / U', id: 'smooth' },
  { keys: 'L', id: 'labels' },
  { keys: 'Z', id: 'lastz' },
  { keys: 'A', id: 'absorber' },
  { keys: 'v', id: 'vstack' },
  { keys: 'g g / c c', id: 'fit' },
  { keys: '1 2 4 6 8 C M F', id: 'quickid' },
  { keys: 'R', id: 'clear' },
  { keys: '?', id: 'help' },
]

export function cssColor(name: string): string {
  return ABSORBER_COLORS[name] ?? name
}

export function nextColor(used: number): string {
  return COLOR_NAMES[used % COLOR_NAMES.length] ?? 'sky_blue'
}

function num(value: unknown, fallback = Number.NaN): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function absorberRow(raw: unknown): AbsorberRow | null {
  if (typeof raw !== 'object' || raw === null) return null
  const r = raw as Record<string, unknown>
  const zabs = num(r['zabs'] ?? r['Zabs'])
  if (!Number.isFinite(zabs)) return null
  return {
    zabs,
    linelist: String(r['linelist'] ?? r['LineList'] ?? 'LLS'),
    color: String(r['color'] ?? r['Color'] ?? 'sky_blue'),
    visible: (r['visible'] ?? r['Visible'] ?? true) !== false,
    label: String(r['label'] ?? r['Label'] ?? ''),
  }
}

function identifiedRow(raw: unknown): IdentifiedRow | null {
  if (typeof raw !== 'object' || raw === null) return null
  const r = raw as Record<string, unknown>
  const waveObs = num(r['wave_obs'] ?? r['Wave_obs'])
  const zabs = num(r['zabs'] ?? r['Zabs'], 0)
  if (!Number.isFinite(waveObs)) return null
  const rest = num(r['wave_rest'] ?? r['Wave_rest'], waveObs / (1 + zabs))
  return {
    name: String(r['name'] ?? r['Name'] ?? ''),
    waveObs,
    zabs,
    waveRest: rest,
    spectrum: String(r['spectrum'] ?? r['Spectrum'] ?? ''),
  }
}

/** Parse a `rbcodes.MultispecView` summary; `null` when the payload is not one. */
export function parseView(summary: Record<string, unknown> | undefined): MultispecSummary | null {
  if (!summary || !Array.isArray(summary['panels'])) return null
  const panels: SpectrumSeries[] = []
  for (const raw of summary['panels']) {
    if (typeof raw !== 'object' || raw === null) continue
    const series = seriesFromSummary(raw as Record<string, unknown>)
    if (series) panels.push(series)
  }
  const range = summary['range']
  return {
    count: typeof summary['count'] === 'number' ? summary['count'] : panels.length,
    labels: Array.isArray(summary['labels']) ? summary['labels'].map(String) : [],
    range:
      Array.isArray(range) && range.length === 2
        ? [num(range[0], 0), num(range[1], 1)]
        : panelsRange(panels),
    z: num(summary['z'], 0),
    linelist: typeof summary['linelist'] === 'string' ? summary['linelist'] : 'LLS',
    panels,
    absorbers: rowsOf(summary['absorbers'], absorberRow),
    identified: rowsOf(summary['identified'], identifiedRow),
  }
}

function rowsOf<T>(raw: unknown, parse: (value: unknown) => T | null): T[] {
  if (!Array.isArray(raw)) return []
  const out: T[] = []
  for (const value of raw) {
    const row = parse(value)
    if (row) out.push(row)
  }
  return out
}

/** Panels of a `SpectrumCollection` summary (the editor's `spectra` input). */
export function panelsFromCollection(summary: Record<string, unknown> | undefined): {
  panels: SpectrumSeries[]
  labels: string[]
  count: number
} {
  const items = summary?.['items']
  const panels: SpectrumSeries[] = []
  if (Array.isArray(items)) {
    for (const raw of items) {
      if (typeof raw !== 'object' || raw === null) continue
      const series = seriesFromSummary(raw as Record<string, unknown>)
      if (series) panels.push(series)
    }
  }
  const labels = Array.isArray(summary?.['labels']) ? summary['labels'].map(String) : []
  const count = typeof summary?.['count'] === 'number' ? summary['count'] : panels.length
  return { panels, labels, count }
}

/** The `head` block of a `Table` summary as rows of objects. */
export function tableRows(summary: Record<string, unknown> | undefined): Record<string, unknown>[] {
  const head = summary?.['head']
  if (typeof head !== 'object' || head === null) return []
  const columns = Object.entries(head as Record<string, unknown>).filter(([, v]) =>
    Array.isArray(v),
  ) as [string, unknown[]][]
  const length = columns.reduce((n, [, values]) => Math.max(n, values.length), 0)
  const rows: Record<string, unknown>[] = []
  for (let i = 0; i < length; i += 1) {
    const row: Record<string, unknown> = {}
    for (const [name, values] of columns) row[name] = values[i]
    rows.push(row)
  }
  return rows
}

export function absorbersFromTable(summary: Record<string, unknown> | undefined): AbsorberRow[] {
  return rowsOf(tableRows(summary), absorberRow)
}

export function identifiedFromTable(summary: Record<string, unknown> | undefined): IdentifiedRow[] {
  return rowsOf(tableRows(summary), identifiedRow)
}

function panelsRange(panels: SpectrumSeries[]): [number, number] | null {
  let lo = Number.POSITIVE_INFINITY
  let hi = Number.NEGATIVE_INFINITY
  for (const panel of panels) {
    if (!panel.range) continue
    lo = Math.min(lo, panel.range[0])
    hi = Math.max(hi, panel.range[1])
  }
  return lo <= hi ? [lo, hi] : null
}

/** The widest window covering every panel (the editor's default x range). */
export function overallRange(panels: SpectrumSeries[]): [number, number] | null {
  return panelsRange(panels)
}

// --- line identification ---------------------------------------------------------------------

export interface Identification {
  line: LineEntry
  /** Observed wavelength of the matched line at `z`. */
  waveObs: number
  /** Offset of the click from that position, in km/s. */
  deltaKms: number
}

/** The transition of `lines` whose observed position at `z` is closest to `x`. */
export function identifyAt(lines: LineEntry[], x: number, z: number): Identification | null {
  let best: Identification | null = null
  for (const line of lines) {
    const waveObs = line.wrest * (1 + z)
    const deltaKms = ((x - waveObs) / waveObs) * C_FIT
    if (best === null || Math.abs(deltaKms) < Math.abs(best.deltaKms)) {
      best = { line, waveObs, deltaKms }
    }
  }
  return best
}

/** rb_multispec's quick-identification keys: the clicked feature *is* this transition. */
export const QUICK_IDS: ReadonlyArray<{
  key: string
  species: string
  wrest: number
  partner: number
}> = [
  { key: '1', species: 'HI Lya', wrest: 1215.6701, partner: 1025.7223 },
  { key: '2', species: 'HI Lyb', wrest: 1025.7223, partner: 1215.6701 },
  { key: '4', species: 'SiIV', wrest: 1393.76018, partner: 1402.77291 },
  { key: '6', species: 'OVI', wrest: 1031.9261, partner: 1037.6167 },
  { key: '8', species: 'NeVIII', wrest: 770.409, partner: 780.324 },
  { key: 'C', species: 'CIV', wrest: 1548.2049, partner: 1550.77845 },
  { key: 'M', species: 'MgII', wrest: 2796.354, partner: 2803.5314853 },
  { key: 'F', species: 'FeII', wrest: 2600.1724835, partner: 2586.6495659 },
]

/** The redshift implied by reading `x` as the quick-id species (`check_lineid`). */
export function quickIdRedshift(key: string, x: number): { species: string; z: number } | null {
  const entry = QUICK_IDS.find((q) => q.key === key)
  if (!entry || !(x > 0)) return null
  return { species: entry.species, z: x / entry.wrest - 1 }
}

// --- quick fits ------------------------------------------------------------------------------

export interface FitAnchor {
  x: number
  y: number
}

export interface QuickFit {
  kind: 'gaussian' | 'com'
  centroid: number
  fwhmAng: number
  fwhmKms: number
  sigmaAng: number
  amplitude: number
  direction: 1 | -1
  asymmetric: boolean
  nPixels: number
  window: [number, number]
  /** Model curve for the overlay (empty for `com`). */
  model: { x: number[]; y: number[] }
}

function orderAnchors(a: FitAnchor, b: FitAnchor): [FitAnchor, FitAnchor] {
  return a.x <= b.x ? [a, b] : [b, a]
}

function continuumAt(x: number, left: FitAnchor, right: FitAnchor): number {
  return left.y + ((right.y - left.y) / (right.x - left.x)) * (x - left.x)
}

interface Window {
  x: number[]
  residual: number[]
  direction: 1 | -1
}

function fitWindow(
  series: Pick<SpectrumSeries, 'wave' | 'flux'>,
  left: FitAnchor,
  right: FitAnchor,
  minimum: number,
): Window {
  const x: number[] = []
  const residual: number[] = []
  for (let i = 0; i < series.wave.length; i += 1) {
    const w = series.wave[i]
    const f = series.flux[i]
    if (w === undefined || f === undefined) continue
    if (w < left.x || w > right.x || !Number.isFinite(f)) continue
    x.push(w)
    residual.push(f - continuumAt(w, left, right))
  }
  if (x.length < minimum) {
    throw new Error(`only ${x.length} pixels in the window, need at least ${minimum}`)
  }
  const sum = residual.reduce((total, v) => total + v, 0)
  return { x, residual, direction: sum < 0 ? -1 : 1 }
}

function asymmetric(centroid: number, left: number, right: number): boolean {
  const width = right - left
  return (
    centroid - left < ASYMMETRY_FRACTION * width || right - centroid < ASYMMETRY_FRACTION * width
  )
}

/**
 * Centre-of-mass centroid between two anchors — the exact formula of `LineFitter.fit_com`
 * (weights are the continuum-subtracted residuals clipped at zero).
 */
export function fitCom(
  series: Pick<SpectrumSeries, 'wave' | 'flux'>,
  a: FitAnchor,
  b: FitAnchor,
): QuickFit {
  const [left, right] = orderAnchors(a, b)
  const { x, residual, direction } = fitWindow(series, left, right, 3)
  const weights = residual.map((v) => Math.max(direction * v, 0))
  const total = weights.reduce((sum, w) => sum + w, 0)
  if (total === 0) throw new Error('no signal above the continuum in the window')
  let centroid = 0
  for (let i = 0; i < x.length; i += 1) centroid += (weights[i] ?? 0) * (x[i] ?? 0)
  centroid /= total
  let variance = 0
  for (let i = 0; i < x.length; i += 1) {
    variance += (weights[i] ?? 0) * ((x[i] ?? 0) - centroid) ** 2
  }
  const sigma = Math.sqrt(variance / total)
  const fwhmAng = FWHM_PER_SIGMA * sigma
  return {
    kind: 'com',
    centroid,
    fwhmAng,
    fwhmKms: centroid > 0 ? (fwhmAng / centroid) * C_FIT : 0,
    sigmaAng: sigma,
    amplitude: direction * Math.max(...weights),
    direction,
    asymmetric: asymmetric(centroid, left.x, right.x),
    nPixels: x.length,
    window: [left.x, right.x],
    model: { x: [], y: [] },
  }
}

/**
 * Least-squares Gaussian on `flux - continuum`, the browser twin of `LineFitter.fit_gaussian`.
 * Gauss-Newton with the same initial guess as scipy's `curve_fit`; the amplitude and width are
 * kept positive and the centroid inside the window, as upstream's bounds do.
 */
export function fitGaussian(
  series: Pick<SpectrumSeries, 'wave' | 'flux'>,
  a: FitAnchor,
  b: FitAnchor,
): QuickFit {
  const [left, right] = orderAnchors(a, b)
  const { x, residual, direction } = fitWindow(series, left, right, 5)
  const data = residual.map((v) => direction * v)
  let peak = -Infinity
  let centroid = x[0] ?? left.x
  for (let i = 0; i < x.length; i += 1) {
    const v = data[i] ?? 0
    if (v > peak) {
      peak = v
      centroid = x[i] ?? centroid
    }
  }
  let amplitude = peak > 0 ? peak : Math.max(...residual.map(Math.abs))
  let sigma = (right.x - left.x) / 4

  for (let step = 0; step < 60; step += 1) {
    // Normal equations of the 3-parameter Gaussian (amplitude, centre, sigma).
    let m00 = 0
    let m01 = 0
    let m02 = 0
    let m11 = 0
    let m12 = 0
    let m22 = 0
    let r0 = 0
    let r1 = 0
    let r2 = 0
    for (let i = 0; i < x.length; i += 1) {
      const d = ((x[i] ?? 0) - centroid) / sigma
      const e = Math.exp(-0.5 * d * d)
      const j0 = e
      const j1 = (amplitude * e * d) / sigma
      const j2 = (amplitude * e * d * d) / sigma
      const r = (data[i] ?? 0) - amplitude * e
      m00 += j0 * j0
      m01 += j0 * j1
      m02 += j0 * j2
      m11 += j1 * j1
      m12 += j1 * j2
      m22 += j2 * j2
      r0 += j0 * r
      r1 += j1 * r
      r2 += j2 * r
    }
    // Levenberg damping keeps the step stable on flat windows.
    const delta = solve3(
      [m00 * 1.001 + 1e-12, m01, m02, m01, m11 * 1.001 + 1e-12, m12, m02, m12, m22 * 1.001 + 1e-12],
      [r0, r1, r2],
    )
    if (!delta) break
    const [dAmp, dCen, dSig] = delta
    amplitude = Math.max(0, amplitude + dAmp)
    centroid = Math.min(right.x, Math.max(left.x, centroid + dCen))
    sigma = Math.min(right.x - left.x, Math.max(1e-3, sigma + dSig))
    if (Math.abs(dCen) < 1e-7 && Math.abs(dSig) < 1e-7) break
  }

  const fwhmAng = FWHM_PER_SIGMA * sigma
  const model = { x: [] as number[], y: [] as number[] }
  for (let i = 0; i < 300; i += 1) {
    const xi = left.x + ((right.x - left.x) * i) / 299
    const d = (xi - centroid) / sigma
    model.x.push(xi)
    model.y.push(continuumAt(xi, left, right) + direction * amplitude * Math.exp(-0.5 * d * d))
  }
  return {
    kind: 'gaussian',
    centroid,
    fwhmAng,
    fwhmKms: centroid > 0 ? (fwhmAng / centroid) * C_FIT : 0,
    sigmaAng: sigma,
    amplitude: direction * amplitude,
    direction,
    asymmetric: asymmetric(centroid, left.x, right.x),
    nPixels: x.length,
    window: [left.x, right.x],
    model,
  }
}

/** Gauss-Jordan elimination on a 3x3 system; `null` when it is singular. */
function solve3(m: number[], v: number[]): [number, number, number] | null {
  const a = [
    [m[0] ?? 0, m[1] ?? 0, m[2] ?? 0, v[0] ?? 0],
    [m[3] ?? 0, m[4] ?? 0, m[5] ?? 0, v[1] ?? 0],
    [m[6] ?? 0, m[7] ?? 0, m[8] ?? 0, v[2] ?? 0],
  ]
  for (let col = 0; col < 3; col += 1) {
    let pivot = col
    for (let row = col + 1; row < 3; row += 1) {
      if (Math.abs(a[row]?.[col] ?? 0) > Math.abs(a[pivot]?.[col] ?? 0)) pivot = row
    }
    const pivotRow = a[pivot]
    const target = a[col]
    if (!pivotRow || !target) return null
    a[pivot] = target
    a[col] = pivotRow
    const head = a[col]?.[col] ?? 0
    if (Math.abs(head) < 1e-18) return null
    for (let row = 0; row < 3; row += 1) {
      if (row === col) continue
      const factor = (a[row]?.[col] ?? 0) / head
      for (let k = col; k < 4; k += 1) {
        const source = a[col]?.[k] ?? 0
        const line = a[row]
        if (line) line[k] = (line[k] ?? 0) - factor * source
      }
    }
  }
  return [
    (a[0]?.[3] ?? 0) / (a[0]?.[0] ?? 1),
    (a[1]?.[3] ?? 0) / (a[1]?.[1] ?? 1),
    (a[2]?.[3] ?? 0) / (a[2]?.[2] ?? 1),
  ]
}

// --- velocity stack --------------------------------------------------------------------------

export interface VelocityPanel {
  name: string
  wrest: number
  velocity: number[]
  flux: number[]
}

/** rbcodes' speed of light, used everywhere except `LineFitter`. */
export const C_RB = 2.9979e5

/**
 * One velocity panel per transition of `lines` that falls inside the spectrum at `z`
 * (`rbcodes.multispec.vstack` in the browser, for the editor's side panel).
 */
export function velocityPanels(
  series: Pick<SpectrumSeries, 'wave' | 'flux' | 'range'>,
  lines: LineEntry[],
  z: number,
  vmin: number,
  vmax: number,
  maxPanels = 12,
): VelocityPanel[] {
  const range = series.range
  if (!range) return []
  const out: VelocityPanel[] = []
  for (const line of [...lines].sort((a, b) => a.wrest - b.wrest)) {
    const centre = line.wrest * (1 + z)
    if (!(centre > range[0] && centre < range[1])) continue
    const velocity: number[] = []
    const flux: number[] = []
    for (let i = 0; i < series.wave.length; i += 1) {
      const w = series.wave[i]
      const f = series.flux[i]
      if (w === undefined || f === undefined) continue
      const v = ((w - centre) / centre) * C_RB
      if (v < vmin || v > vmax) continue
      velocity.push(v)
      flux.push(f)
    }
    if (velocity.length < 2) continue
    out.push({ name: line.name, wrest: line.wrest, velocity, flux })
    if (out.length >= maxPanels) break
  }
  return out
}

// --- formatting ------------------------------------------------------------------------------

/** `1.385500` — rb_multispec prints six decimals for redshifts everywhere. */
export function formatZabs(z: number): string {
  return Number.isFinite(z) ? z.toFixed(6) : '-'
}

export function formatWave(wave: number): string {
  return Number.isFinite(wave) ? wave.toFixed(4) : '-'
}
