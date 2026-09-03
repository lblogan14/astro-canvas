/**
 * Pure helpers for the `aperture-editor` (`rbcodes.ifu.aperture_extract`): the aperture shapes,
 * hit testing, drag handles and the ds9 text format.
 *
 * Geometry mirrors `astro.Region` exactly — 0-based pixel coordinates, `circle [cx, cy, r]`,
 * `annulus [cx, cy, r_in, r_out]`, `box [cx, cy, w, h, angle]`, `polygon [x1, y1, ...]` — so what
 * the editor edits is what `Apply` writes and what the node rasterizes. Nothing here touches the
 * DOM or a store: the editor component owns all of that.
 */

export type ApertureShape = 'circle' | 'box' | 'annulus' | 'polygon'
export type ApertureRole = 'source' | 'background'

export interface Aperture {
  shape: ApertureShape
  /** Pixel geometry, laid out per shape (see the module docstring). */
  pixel: number[]
  /** Sky geometry (degrees, sizes in arcsec) when the node last computed one. */
  sky: number[] | null
  label: string | null
  role: ApertureRole
}

export interface Point {
  x: number
  y: number
}

export const SHAPES: readonly ApertureShape[] = ['circle', 'box', 'annulus', 'polygon']
const MIN_SIZE = 0.5

/** A region row from a param value or a `Region2D` summary, defaults filled in. */
export function toAperture(value: unknown): Aperture | null {
  if (typeof value !== 'object' || value === null) return null
  const row = value as Record<string, unknown>
  const shape = row['shape']
  if (typeof shape !== 'string' || !SHAPES.includes(shape as ApertureShape)) return null
  const pixel = numbers(row['pixel'])
  if (!pixel.length) return null
  const role = row['role'] === 'background' ? 'background' : 'source'
  const label = typeof row['label'] === 'string' && row['label'] ? row['label'] : null
  const sky = numbers(row['sky'])
  return { shape: shape as ApertureShape, pixel, sky: sky.length ? sky : null, label, role }
}

/** Every aperture in a `regions` param value or an `astro.Region2D` summary. */
export function aperturesFrom(value: unknown): Aperture[] {
  const rows = Array.isArray(value)
    ? value
    : typeof value === 'object' && value !== null
      ? (value as Record<string, unknown>)['regions']
      : null
  if (!Array.isArray(rows)) return []
  return rows.map(toAperture).filter((r): r is Aperture => r !== null)
}

/** The `regions` param payload (drop the sky block: the node recomputes it from the WCS). */
export function toParam(apertures: Aperture[]): Record<string, unknown>[] {
  return apertures.map((a) => ({
    shape: a.shape,
    pixel: a.pixel.map(round4),
    sky: a.sky,
    label: a.label,
    role: a.role,
  }))
}

function numbers(value: unknown): number[] {
  if (!Array.isArray(value)) return []
  const out: number[] = []
  for (const item of value) {
    const n = typeof item === 'number' ? item : Number(item)
    if (!Number.isFinite(n)) return []
    out.push(n)
  }
  return out
}

function round4(value: number): number {
  return Math.round(value * 1e4) / 1e4
}

// --- construction ------------------------------------------------------------------------------

/** A new aperture of `shape`, sized from the drag between `from` and `to`. */
export function apertureFromDrag(
  shape: ApertureShape,
  from: Point,
  to: Point,
  role: ApertureRole = 'source',
): Aperture {
  const dx = to.x - from.x
  const dy = to.y - from.y
  const pixel = (() => {
    switch (shape) {
      case 'circle':
        return [from.x, from.y, Math.max(MIN_SIZE, Math.hypot(dx, dy))]
      case 'annulus': {
        const outer = Math.max(MIN_SIZE * 2, Math.hypot(dx, dy))
        return [from.x, from.y, outer * 0.6, outer]
      }
      case 'box':
        return [
          (from.x + to.x) / 2,
          (from.y + to.y) / 2,
          Math.max(MIN_SIZE, Math.abs(dx)),
          Math.max(MIN_SIZE, Math.abs(dy)),
          0,
        ]
      default:
        return [from.x, from.y, to.x, from.y, to.x, to.y, from.x, to.y]
    }
  })()
  return { shape, pixel, sky: null, label: null, role }
}

/** Default label for an unnamed aperture (`circle 2`), matching what the node generates. */
export function defaultLabel(aperture: Aperture, index: number): string {
  return aperture.label || `${aperture.shape} ${index + 1}`
}

// --- geometry ----------------------------------------------------------------------------------

export function center(aperture: Aperture): Point {
  const p = aperture.pixel
  if (aperture.shape === 'polygon') {
    const xs = p.filter((_, i) => i % 2 === 0)
    const ys = p.filter((_, i) => i % 2 === 1)
    if (!xs.length) return { x: 0, y: 0 }
    return { x: mean(xs), y: mean(ys) }
  }
  return { x: p[0] ?? 0, y: p[1] ?? 0 }
}

function mean(values: number[]): number {
  return values.reduce((a, b) => a + b, 0) / values.length
}

/** The outer radius of a shape, used for hit testing and the resize handle. */
export function outerRadius(aperture: Aperture): number {
  const p = aperture.pixel
  switch (aperture.shape) {
    case 'circle':
      return p[2] ?? 0
    case 'annulus':
      return p[3] ?? 0
    case 'box':
      return Math.hypot((p[2] ?? 0) / 2, (p[3] ?? 0) / 2)
    default: {
      const c = center(aperture)
      let max = 0
      for (let i = 0; i + 1 < p.length; i += 2) {
        max = Math.max(max, Math.hypot((p[i] ?? 0) - c.x, (p[i + 1] ?? 0) - c.y))
      }
      return max
    }
  }
}

/** Is the data pixel `point` inside `aperture`? (The same predicate the kernels rasterize.) */
export function contains(aperture: Aperture, point: Point): boolean {
  const p = aperture.pixel
  const dx = point.x - (p[0] ?? 0)
  const dy = point.y - (p[1] ?? 0)
  switch (aperture.shape) {
    case 'circle':
      return dx * dx + dy * dy <= (p[2] ?? 0) ** 2
    case 'annulus': {
      const r2 = dx * dx + dy * dy
      return r2 >= (p[2] ?? 0) ** 2 && r2 <= (p[3] ?? 0) ** 2
    }
    case 'box': {
      const angle = ((p[4] ?? 0) * Math.PI) / 180
      const ca = Math.cos(angle)
      const sa = Math.sin(angle)
      const xr = dx * ca + dy * sa
      const yr = -dx * sa + dy * ca
      return Math.abs(xr) <= (p[2] ?? 0) / 2 && Math.abs(yr) <= (p[3] ?? 0) / 2
    }
    default:
      return insidePolygon(p, point)
  }
}

/** Even-odd crossing count, the rasterizer's rule. */
export function insidePolygon(flat: number[], point: Point): boolean {
  let inside = false
  const n = Math.floor(flat.length / 2)
  for (let i = 0, j = n - 1; i < n; j = i, i += 1) {
    const xi = flat[i * 2] ?? 0
    const yi = flat[i * 2 + 1] ?? 0
    const xj = flat[j * 2] ?? 0
    const yj = flat[j * 2 + 1] ?? 0
    if (yi === yj) continue
    if (yi > point.y !== yj > point.y) {
      const crossing = ((xj - xi) * (point.y - yi)) / (yj - yi) + xi
      if (point.x < crossing) inside = !inside
    }
  }
  return inside
}

/** Index of the top-most aperture under `point`, or `-1`. */
export function pick(apertures: Aperture[], point: Point): number {
  for (let i = apertures.length - 1; i >= 0; i -= 1) {
    const aperture = apertures[i]
    if (aperture && contains(aperture, point)) return i
  }
  return -1
}

/** Move an aperture so its centre lands on `to`. */
export function moveTo(aperture: Aperture, to: Point): Aperture {
  const from = center(aperture)
  const dx = to.x - from.x
  const dy = to.y - from.y
  if (aperture.shape === 'polygon') {
    return {
      ...aperture,
      pixel: aperture.pixel.map((v, i) => (i % 2 === 0 ? v + dx : v + dy)),
    }
  }
  return {
    ...aperture,
    pixel: [aperture.pixel[0]! + dx, aperture.pixel[1]! + dy, ...aperture.pixel.slice(2)],
  }
}

/** Resize so the outer edge passes through `to` (polygons scale about their centre). */
export function resizeTo(aperture: Aperture, to: Point): Aperture {
  const c = center(aperture)
  const distance = Math.max(MIN_SIZE, Math.hypot(to.x - c.x, to.y - c.y))
  const p = aperture.pixel
  switch (aperture.shape) {
    case 'circle':
      return { ...aperture, pixel: [p[0]!, p[1]!, distance] }
    case 'annulus': {
      const ratio = (p[2] ?? 1) / Math.max(p[3] ?? 1, MIN_SIZE)
      return { ...aperture, pixel: [p[0]!, p[1]!, distance * ratio, distance] }
    }
    case 'box': {
      const width = Math.max(MIN_SIZE, Math.abs(to.x - c.x) * 2)
      const height = Math.max(MIN_SIZE, Math.abs(to.y - c.y) * 2)
      return { ...aperture, pixel: [p[0]!, p[1]!, width, height, p[4] ?? 0] }
    }
    default: {
      const scale = distance / Math.max(outerRadius(aperture), MIN_SIZE)
      return {
        ...aperture,
        pixel: p.map((v, i) => (i % 2 === 0 ? c.x + (v - c.x) * scale : c.y + (v - c.y) * scale)),
      }
    }
  }
}

/** Clamp every coordinate into `[0, nx)` / `[0, ny)` so an aperture cannot leave the field. */
export function clampToField(aperture: Aperture, ny: number, nx: number): Aperture {
  const c = center(aperture)
  if (c.x >= 0 && c.y >= 0 && c.x < nx && c.y < ny) return aperture
  const x = Math.min(nx - 1, Math.max(0, c.x))
  const y = Math.min(ny - 1, Math.max(0, c.y))
  return moveTo(aperture, { x, y })
}

// --- ds9 ---------------------------------------------------------------------------------------

/**
 * ds9 region text in `image` coordinates, byte-for-byte what `kernels/ds9.py::to_ds9` writes, so a
 * file exported here and one written by the node are interchangeable.
 */
export function toDs9(apertures: Aperture[]): string {
  const lines = [
    '# Region file format: DS9 version 4.1',
    'global color=green dashlist=8 3 width=1 font="helvetica 10 normal roman" ' +
      'select=1 highlite=1 dash=0 fixed=0 edit=1 move=1 delete=1 include=1 source=1',
    'image',
  ]
  for (const aperture of apertures) {
    const p = aperture.pixel.map((v) => v)
    const parts: string[] = []
    if (aperture.label) parts.push(`text={${aperture.label}}`)
    if (aperture.role !== 'source') parts.push(`tag={${aperture.role}}`)
    const comment = parts.length ? ` # ${parts.join(' ')}` : ''
    lines.push(shapeLine(aperture.shape, p) + comment)
  }
  return `${lines.join('\n')}\n`
}

function shapeLine(shape: ApertureShape, p: number[]): string {
  const f = (value: number) => value.toFixed(4)
  switch (shape) {
    case 'circle':
      return `circle(${f(p[0]! + 1)},${f(p[1]! + 1)},${f(p[2] ?? 0)})`
    case 'annulus':
      return `annulus(${f(p[0]! + 1)},${f(p[1]! + 1)},${f(p[2] ?? 0)},${f(p[3] ?? 0)})`
    case 'box':
      return `box(${f(p[0]! + 1)},${f(p[1]! + 1)},${f(p[2] ?? 0)},${f(p[3] ?? 0)},${f(p[4] ?? 0)})`
    default:
      return `polygon(${p.map((v) => f(v + 1)).join(',')})`
  }
}

const SHAPE_RE = /(\w+)\s*\(([^)]+)\)/
const TEXT_RE = /text\s*=\s*\{([^}]*)\}/i
const TAG_RE = /tag\s*=\s*\{([^}]*)\}/i
const SKY_SYSTEMS = ['fk5', 'fk4', 'icrs', 'galactic', 'ecliptic', 'wcs']

/**
 * Parse ds9 region text in *image* coordinates. Sky-coordinate files are the node's job
 * (`rbcodes.ifu.regions_from_ds9`): converting degrees back to pixels needs the full WCS, which
 * only the server has.
 */
export function fromDs9(text: string): { apertures: Aperture[]; skipped: number } {
  const apertures: Aperture[] = []
  let skipped = 0
  let sky = false
  for (const raw of text.split(/\r?\n/)) {
    let line = raw.trim()
    if (!line || line.startsWith('#') || line.toLowerCase().startsWith('global')) continue
    const lowered = line.toLowerCase()
    if (SKY_SYSTEMS.includes(lowered)) {
      sky = true
      continue
    }
    if (['image', 'physical', 'linear'].includes(lowered)) {
      sky = false
      continue
    }
    let comment = ''
    const hash = line.indexOf('#')
    if (hash >= 0) {
      comment = line.slice(hash + 1).trim()
      line = line.slice(0, hash).trim()
    }
    if (line.startsWith('-')) continue
    const match = SHAPE_RE.exec(line)
    if (!match) continue
    const shape = (match[1] ?? '').toLowerCase() as ApertureShape
    if (!SHAPES.includes(shape)) continue
    if (sky) {
      skipped += 1
      continue
    }
    const values = (match[2] ?? '')
      .split(',')
      .map((a) => Number.parseFloat(a.replace(/[^\d.eE+-]/g, '')))
    if (values.some((v) => !Number.isFinite(v))) continue
    const pixel =
      shape === 'polygon'
        ? values.map((v) => v - 1)
        : [values[0]! - 1, values[1]! - 1, ...values.slice(2)]
    if (shape === 'box' && pixel.length === 4) pixel.push(0)
    const label = TEXT_RE.exec(comment)?.[1]?.trim() ?? ''
    const tag = TAG_RE.exec(comment)?.[1]?.trim().toLowerCase()
    apertures.push({
      shape,
      pixel,
      sky: null,
      label: label || null,
      role: tag === 'background' ? 'background' : 'source',
    })
  }
  return { apertures, skipped }
}

// --- readout -----------------------------------------------------------------------------------

/** A one-line description of an aperture's size, for the list and the readout bar. */
export function describe(aperture: Aperture, arcsecPerPixel: number | null): string {
  const p = aperture.pixel
  const size = (value: number) =>
    arcsecPerPixel ? `${(value * arcsecPerPixel).toFixed(2)}″` : `${value.toFixed(1)} px`
  switch (aperture.shape) {
    case 'circle':
      return `r ${size(p[2] ?? 0)}`
    case 'annulus':
      return `${size(p[2] ?? 0)} – ${size(p[3] ?? 0)}`
    case 'box':
      return `${size(p[2] ?? 0)} × ${size(p[3] ?? 0)}`
    default:
      return `${Math.floor(p.length / 2)} vertices`
  }
}
