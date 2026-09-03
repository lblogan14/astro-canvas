/**
 * Pure helpers for the `z-accept` editor (`rbcodes.zfind.rank`) and the zfind previews: parse
 * `rbcodes.ZFindResult` / `AbsorberResult` summaries, combine the candidates of several scans
 * exactly like the backend's `combine_candidates` (so `accepted` indices agree), and place line
 * ticks on the spectrum at a trial redshift.
 */
import { type SpectrumSeries, seriesFromSummary } from '@/widgets/spectrumSeries'

export type Statistic = 'chi2' | 'score' | 'significance'

export interface ZCurveData {
  label: string
  /** `null` where the scan had no line in range (NaN on the server). */
  values: (number | null)[]
}

export interface SolutionRow {
  z: number
  zErr: number | null
  score: number
  method: string
  templateType: string
  nFeatures: number
}

export interface ZFindSummary {
  type: string
  statistic: Statistic
  n: number
  zRange: [number, number] | null
  z: number[]
  curves: ZCurveData[]
  /** Ranked solutions (emission-mode results); absorber results expose `candidates` instead. */
  solutions: SolutionRow[]
  spectrum: SpectrumSeries | null
  warnings: string[]
  linelist: string | null
}

export interface ZCandidate extends SolutionRow {
  /** Position in the combined table: what `rank.accepted` stores. */
  index: number
  /** Which input port fed it (0 = `results`, 1 = `results_2`, ...). */
  source: number
  /** Rank within its source (0 = that scan's best). */
  rank: number
}

export interface LineEntry {
  wrest: number
  name: string
  kind: 'emission' | 'absorption'
}

export interface LineTick extends LineEntry {
  /** Observed wavelength at the trial redshift. */
  x: number
}

const STATISTICS: ReadonlySet<string> = new Set(['chi2', 'score', 'significance'])

function numberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function numberList(value: unknown): (number | null)[] | null {
  if (!Array.isArray(value)) return null
  return value.map((v) => numberOrNull(v))
}

function solutionRow(raw: unknown, scoreKey: 'chi2_dof' | 'significance'): SolutionRow | null {
  if (typeof raw !== 'object' || raw === null) return null
  const r = raw as Record<string, unknown>
  const z = numberOrNull(r['z'])
  if (z === null) return null
  return {
    z,
    zErr: numberOrNull(r['z_err']),
    score: numberOrNull(r[scoreKey]) ?? Number.NaN,
    method:
      typeof r['method'] === 'string'
        ? r['method']
        : typeof r['linelist_name'] === 'string'
          ? `Absorber:${r['linelist_name']}`
          : '',
    templateType: typeof r['template_type'] === 'string' ? r['template_type'] : 'Unknown',
    nFeatures:
      typeof r['n_features'] === 'number'
        ? r['n_features']
        : typeof r['n_lines'] === 'number'
          ? r['n_lines']
          : 0,
  }
}

/** Parse a `rbcodes.ZFindResult` or `rbcodes.AbsorberResult` summary; `null` when it is neither. */
export function parseZFind(summary: Record<string, unknown> | undefined): ZFindSummary | null {
  if (!summary) return null
  const z = numberList(summary['z'])
  const rawCurves = summary['curves']
  if (!z || !Array.isArray(rawCurves)) return null
  const curves: ZCurveData[] = []
  for (const raw of rawCurves) {
    if (typeof raw !== 'object' || raw === null) continue
    const r = raw as Record<string, unknown>
    const values = numberList(r['values'])
    if (!values || values.length !== z.length) continue
    curves.push({ label: typeof r['label'] === 'string' ? r['label'] : '', values })
  }
  const statistic = summary['statistic']
  const rows = Array.isArray(summary['solutions'])
    ? summary['solutions'].map((s) => solutionRow(s, 'chi2_dof'))
    : Array.isArray(summary['candidates'])
      ? summary['candidates'].map((s) => solutionRow(s, 'significance'))
      : []
  const range = numberList(summary['z_range'])
  const lo = range?.[0]
  const hi = range?.[1]
  const spectrum = summary['spectrum']
  return {
    type: typeof summary['type'] === 'string' ? summary['type'] : '',
    statistic:
      typeof statistic === 'string' && STATISTICS.has(statistic)
        ? (statistic as Statistic)
        : 'chi2',
    n: typeof summary['n'] === 'number' ? summary['n'] : z.length,
    zRange: typeof lo === 'number' && typeof hi === 'number' ? [lo, hi] : null,
    z: z.map((v) => v ?? Number.NaN),
    curves,
    solutions: rows.filter((r): r is SolutionRow => r !== null),
    spectrum:
      typeof spectrum === 'object' && spectrum !== null
        ? seriesFromSummary(spectrum as Record<string, unknown>)
        : null,
    warnings: Array.isArray(summary['warnings']) ? summary['warnings'].map(String) : [],
    linelist: typeof summary['linelist'] === 'string' ? summary['linelist'] : null,
  }
}

/**
 * The candidate table of `rbcodes.zfind.rank`: every source's solutions in order, sources in
 * port order; statistics differ between methods so nothing is re-sorted across sources.
 */
export function combineCandidates(sources: (ZFindSummary | null)[]): ZCandidate[] {
  const out: ZCandidate[] = []
  sources.forEach((source, sourceIndex) => {
    if (!source) return
    source.solutions.forEach((solution, rank) => {
      out.push({ ...solution, index: out.length, source: sourceIndex, rank })
    })
  })
  return out
}

/** The candidate of `source` whose redshift is closest to `z` (a click on the curve). */
export function nearestCandidate(
  candidates: ZCandidate[],
  source: number,
  z: number,
): ZCandidate | null {
  let best: ZCandidate | null = null
  for (const candidate of candidates) {
    if (candidate.source !== source) continue
    if (best === null || Math.abs(candidate.z - z) < Math.abs(best.z - z)) best = candidate
  }
  return best
}

/** `(x, y)` of one curve with gaps as NaN (Plotly breaks the line there). */
export function curveSeries(
  summary: ZFindSummary,
  curveIndex = 0,
): { x: number[]; y: number[]; label: string } | null {
  const curve = summary.curves[curveIndex]
  if (!curve) return null
  return {
    x: summary.z,
    y: curve.values.map((v) => v ?? Number.NaN),
    label: curve.label,
  }
}

/** Parallel arrays of a `LineList` summary into rows (kinds default to emission). */
export function curatedLinesFromSummary(summary: Record<string, unknown> | undefined): LineEntry[] {
  const wrest = summary?.['wrest']
  const name = summary?.['name']
  const kind = summary?.['kind']
  if (!Array.isArray(wrest) || !Array.isArray(name)) return []
  const out: LineEntry[] = []
  for (let i = 0; i < wrest.length; i += 1) {
    const w = wrest[i]
    if (typeof w !== 'number') continue
    const k = Array.isArray(kind) ? kind[i] : undefined
    out.push({
      wrest: w,
      name: String(name[i] ?? ''),
      kind: k === 'absorption' ? 'absorption' : 'emission',
    })
  }
  return out
}

/** Observed positions of `lines` at redshift `z`, restricted to `range` when given. */
export function lineTicks(
  lines: LineEntry[],
  z: number,
  range: [number, number] | null,
): LineTick[] {
  const out: LineTick[] = []
  for (const line of lines) {
    const x = line.wrest * (1 + z)
    if (range && (x < Math.min(range[0], range[1]) || x > Math.max(range[0], range[1]))) continue
    out.push({ ...line, x })
  }
  return out
}

/** `0.00567 ± 0.00007` (digits follow the error) or `0.00567` when no error is known. */
export function formatZ(z: number, zErr: number | null): string {
  if (zErr === null || !(zErr > 0)) return z.toFixed(5)
  const digits = Math.min(6, Math.max(2, Math.ceil(-Math.log10(zErr)) + 1))
  return `${z.toFixed(digits)} ± ${zErr.toFixed(digits)}`
}

/** Compact statistic value: scientific notation for tiny chi-square values. */
export function formatScore(value: number): string {
  if (!Number.isFinite(value)) return '–'
  const magnitude = Math.abs(value)
  if (magnitude !== 0 && (magnitude < 0.01 || magnitude >= 1e5)) return value.toExponential(2)
  return value.toFixed(magnitude >= 100 ? 1 : 3)
}

/** The curated preset names of `rbcodes.zfind.curated_linelist` (fallback when the schema is absent). */
export const CURATED_LINELISTS: readonly string[] = [
  'zfind_em',
  'zfind_stellar',
  'zfind_igm',
  'zfind_galaxy',
  'zfind_qso',
]

/** Map a scan's line-list label to a curated preset for the overlay (else the galaxy preset). */
export function defaultLinelist(linelist: string | null): string {
  return linelist && CURATED_LINELISTS.includes(linelist) ? linelist : 'zfind_galaxy'
}
