/**
 * Pure helpers for the `continuum-mask` editor (`rbcodes.continuum.fit`): mask ranges as
 * `[lo, hi]` pairs in the slice's velocity units, candidate params for live previews, and the
 * BIC table read from the `Continuum` summary.
 */

export type MaskRange = [number, number]

export const CONTINUUM_METHODS = ['polynomial', 'legendre', 'spline', 'flat', 'ransac'] as const
export type ContinuumMethod = (typeof CONTINUUM_METHODS)[number]

export interface ContinuumSettings {
  method: ContinuumMethod
  order: number
  optimizeOrder: boolean
  masks: MaskRange[]
}

/** Coerce an arbitrary param value into ordered `[lo, hi]` pairs (bad entries dropped). */
export function masksFromParam(value: unknown): MaskRange[] {
  if (!Array.isArray(value)) return []
  const out: MaskRange[] = []
  for (const item of value) {
    if (!Array.isArray(item) || item.length !== 2) continue
    const [a, b] = item as [unknown, unknown]
    if (typeof a !== 'number' || typeof b !== 'number' || Number.isNaN(a) || Number.isNaN(b))
      continue
    out.push(a <= b ? [a, b] : [b, a])
  }
  return sortMasks(out)
}

export function sortMasks(masks: MaskRange[]): MaskRange[] {
  return [...masks].sort((p, q) => p[0] - q[0] || p[1] - q[1])
}

/** Add a range, merging it with any range it overlaps or touches. */
export function addMask(masks: MaskRange[], lo: number, hi: number): MaskRange[] {
  let [a, b] = lo <= hi ? [lo, hi] : [hi, lo]
  const rest: MaskRange[] = []
  for (const [mlo, mhi] of masks) {
    if (mhi < a || mlo > b) {
      rest.push([mlo, mhi])
    } else {
      a = Math.min(a, mlo)
      b = Math.max(b, mhi)
    }
  }
  return sortMasks([...rest, [a, b]])
}

/** Remove the range at `index`. */
export function removeMask(masks: MaskRange[], index: number): MaskRange[] {
  return masks.filter((_, i) => i !== index)
}

/** Index of the range containing `x`, or -1. */
export function maskAt(masks: MaskRange[], x: number): number {
  return masks.findIndex(([lo, hi]) => x >= lo && x <= hi)
}

/** Remove the range containing `x` (no-op when none does). */
export function removeMaskAt(masks: MaskRange[], x: number): MaskRange[] {
  const index = maskAt(masks, x)
  return index === -1 ? masks : removeMask(masks, index)
}

export function masksEqual(a: MaskRange[], b: MaskRange[]): boolean {
  if (a.length !== b.length) return false
  return a.every(([lo, hi], i) => b[i]?.[0] === lo && b[i]?.[1] === hi)
}

/** Current editor settings from a node's params (server defaults when absent). */
export function settingsFromParams(params: Record<string, unknown>): ContinuumSettings {
  const method = params['method']
  const order = params['order']
  const optimize = params['optimize_order']
  return {
    method: CONTINUUM_METHODS.includes(method as ContinuumMethod)
      ? (method as ContinuumMethod)
      : 'polynomial',
    order: typeof order === 'number' && Number.isFinite(order) ? Math.max(0, Math.round(order)) : 3,
    optimizeOrder: typeof optimize === 'boolean' ? optimize : true,
    masks: masksFromParam(params['masks']),
  }
}

/** The node params an editor state maps to (what Apply writes and previews send). */
export function paramsFromSettings(settings: ContinuumSettings): Record<string, unknown> {
  return {
    method: settings.method,
    order: settings.order,
    optimize_order: settings.optimizeOrder,
    masks: settings.masks.map(([lo, hi]) => [lo, hi]),
  }
}

export function settingsEqual(a: ContinuumSettings, b: ContinuumSettings): boolean {
  return (
    a.method === b.method &&
    a.order === b.order &&
    a.optimizeOrder === b.optimizeOrder &&
    masksEqual(a.masks, b.masks)
  )
}

export interface BicRow {
  order: number
  bic: number
  best: boolean
}

/** `[order, bic]` rows from a `Continuum` summary (`params.bic_results`), best first marked. */
export function bicRows(summary: Record<string, unknown> | undefined): BicRow[] {
  const params = summary?.['params']
  const raw =
    typeof params === 'object' && params !== null
      ? (params as Record<string, unknown>)['bic_results']
      : undefined
  if (!Array.isArray(raw)) return []
  const rows: BicRow[] = []
  for (const item of raw) {
    if (!Array.isArray(item) || item.length !== 2) continue
    const [order, bic] = item as [unknown, unknown]
    if (typeof order !== 'number' || typeof bic !== 'number') continue
    rows.push({ order, bic, best: false })
  }
  const bestOrder = typeof summary?.['order'] === 'number' ? (summary['order'] as number) : null
  let minIndex = -1
  let min = Number.POSITIVE_INFINITY
  rows.forEach((row, i) => {
    if (row.bic < min) {
      min = row.bic
      minIndex = i
    }
  })
  rows.forEach((row, i) => {
    row.best = bestOrder !== null ? row.order === bestOrder : i === minIndex
  })
  return rows
}

/** Continuum values aligned to a spectrum of `n` points from a `Continuum` summary. */
export function continuumOverlay(
  summary: Record<string, unknown> | undefined,
  x: ArrayLike<number>,
): { x: number[]; y: number[] } | null {
  const cont = summary?.['cont']
  const index = summary?.['index']
  if (!Array.isArray(cont)) return null
  const xs: number[] = []
  const ys: number[] = []
  const idx = Array.isArray(index) ? (index as number[]) : null
  for (let i = 0; i < cont.length; i += 1) {
    const at = idx ? idx[i] : i
    if (at === undefined || at >= x.length) continue
    const xv = x[at]
    const yv = cont[i]
    if (typeof xv !== 'number' || typeof yv !== 'number') continue
    xs.push(xv)
    ys.push(yv)
  }
  return xs.length ? { x: xs, y: ys } : null
}

/** Human-readable `lo – hi` label for a mask. */
export function formatMask([lo, hi]: MaskRange, decimals = 0): string {
  return `${lo.toFixed(decimals)} to ${hi.toFixed(decimals)}`
}
