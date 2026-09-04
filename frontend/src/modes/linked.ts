/**
 * Linked selection between dashboard views (design 8.4: "glue/Jdaviz-like linked views").
 *
 * Two views are linked when they **share an upstream node** — the same spectrum feeding a curve
 * and a table means a wavelength range picked on one is a row filter on the other. The functions
 * here are the pure half: who is linked to whom, what the x axis of a summary spans, and which
 * rows of a table fall in a range. `stores/linked.ts` holds the one live selection.
 */
import type { EdgeDoc } from '@/api/types'

/** The node itself plus every node upstream of it (cycles are impossible: the graph is a DAG). */
export function upstreamNodes(
  nodeId: string,
  edges: Readonly<Record<string, EdgeDoc>>,
): Set<string> {
  const incoming = new Map<string, string[]>()
  for (const edge of Object.values(edges)) {
    const to = String(edge.to[0])
    const from = String(edge.from[0])
    incoming.set(to, [...(incoming.get(to) ?? []), from])
  }
  const seen = new Set<string>([nodeId])
  const queue = [nodeId]
  while (queue.length > 0) {
    const current = queue.pop() as string
    for (const source of incoming.get(current) ?? []) {
      if (seen.has(source)) continue
      seen.add(source)
      queue.push(source)
    }
  }
  return seen
}

export function intersects(a: Iterable<string>, b: ReadonlySet<string>): boolean {
  for (const value of a) if (b.has(value)) return true
  return false
}

// --- reading a summary ---------------------------------------------------------------------------

function numbers(value: unknown): number[] | null {
  if (!Array.isArray(value)) return null
  const out: number[] = []
  for (const item of value) {
    if (typeof item !== 'number' || !Number.isFinite(item)) continue
    out.push(item)
  }
  return out.length > 0 ? out : null
}

/** Column names that carry the x axis of a table, best match first. */
const AXIS_COLUMNS = ['wave', 'wavelength', 'lambda', 'wrest', 'wobs', 'z', 'x', 'vel', 'velocity']

/** What a curve-like summary spans on its x axis, or `null` when it has no usable axis. */
export function xDomain(summary: Record<string, unknown>): [number, number] | null {
  const range = summary['range']
  if (Array.isArray(range) && range.length === 2) {
    const [lo, hi] = range as [unknown, unknown]
    if (typeof lo === 'number' && typeof hi === 'number' && hi > lo) return [lo, hi]
  }
  for (const key of ['wave', 'z', 'x']) {
    const values = numbers(summary[key])
    if (values) {
      const lo = Math.min(...values)
      const hi = Math.max(...values)
      if (hi > lo) return [lo, hi]
    }
  }
  return null
}

/** What the x axis of a summary is called, for the selection label. */
export function axisName(summary: Record<string, unknown>): string {
  if (Array.isArray(summary['wave'])) return 'wave'
  if (Array.isArray(summary['z'])) return 'z'
  return 'x'
}

export interface RowAxis {
  column: string
  values: number[]
}

/**
 * The column of a table-like summary that a range applies to: an axis-shaped name when there is
 * one, else the first numeric column. Reads both the `{columns, head}` table shape and the
 * `{rows: [...]}` shape the candidate tables use.
 */
export function rowAxis(summary: Record<string, unknown>): RowAxis | null {
  const head = summary['head']
  const columns = summary['columns']
  if (Array.isArray(columns) && head && typeof head === 'object') {
    const cells = head as Record<string, unknown>
    const names = (columns as unknown[]).filter((name): name is string => typeof name === 'string')
    const ordered = [
      ...names.filter((name) => AXIS_COLUMNS.includes(name.toLowerCase())),
      ...names.filter((name) => !AXIS_COLUMNS.includes(name.toLowerCase())),
    ]
    for (const name of ordered) {
      const values = numbers(cells[name])
      if (values) return { column: name, values }
    }
    return null
  }
  const rows = summary['rows']
  if (Array.isArray(rows) && rows.length > 0) {
    const first = rows[0]
    if (typeof first === 'object' && first !== null) {
      const keys = Object.keys(first as Record<string, unknown>)
      const ordered = [
        ...keys.filter((name) => AXIS_COLUMNS.includes(name.toLowerCase())),
        ...keys.filter((name) => !AXIS_COLUMNS.includes(name.toLowerCase())),
      ]
      for (const name of ordered) {
        const values = rows.map((row) => (row as Record<string, unknown>)[name])
        if (values.every((value) => typeof value === 'number' && Number.isFinite(value))) {
          return { column: name, values: values as number[] }
        }
      }
    }
  }
  return null
}

/** Indices of the table rows whose axis value falls inside `[lo, hi]`. */
export function rowsInRange(
  summary: Record<string, unknown>,
  lo: number,
  hi: number,
): { column: string; rows: number[] } | null {
  const axis = rowAxis(summary)
  if (!axis) return null
  const min = Math.min(lo, hi)
  const max = Math.max(lo, hi)
  const rows: number[] = []
  axis.values.forEach((value, index) => {
    if (value >= min && value <= max) rows.push(index)
  })
  return { column: axis.column, rows }
}

/** The axis values of the given rows (a table selection projected onto a curve). */
export function valuesOfRows(summary: Record<string, unknown>, rows: readonly number[]): number[] {
  const axis = rowAxis(summary)
  if (!axis) return []
  return rows
    .map((index) => axis.values[index])
    .filter((value): value is number => typeof value === 'number')
}

/** Fraction along `[lo, hi]` clamped to the domain (pixel ↔ data mapping for the drag layer). */
export function fractionOf(value: number, domain: readonly [number, number]): number {
  const [lo, hi] = domain
  if (hi <= lo) return 0
  return Math.min(1, Math.max(0, (value - lo) / (hi - lo)))
}

export function valueAt(fraction: number, domain: readonly [number, number]): number {
  const [lo, hi] = domain
  return lo + Math.min(1, Math.max(0, fraction)) * (hi - lo)
}
