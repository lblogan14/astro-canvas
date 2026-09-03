/**
 * A tiny WCS for image readouts: linear axes and the celestial TAN (gnomonic) projection with a
 * `CD`, `PC × CDELT` or `CROTA2` linear part (Calabretta & Greisen 2002). Pixel coordinates are
 * 0-based (astropy's `origin=0`). Anything else (SIN, other projections, distortions) degrades to
 * the linear part with `projection === 'linear'`.
 *
 * The input is the plain-dict WCS the backend attaches to `astro.Image2D` / `astro.Cube3D`
 * (`packs/core/.../io/fits_meta.py: wcs_dict`).
 */

export interface WcsDict {
  naxis: number
  shape?: number[]
  ctype: string[]
  crval: number[]
  crpix: number[]
  cdelt: number[]
  cunit?: string[]
  cd?: number[][]
  pc?: number[][]
  crota2?: number
  lonpole?: number
  latpole?: number
  radesys?: string
  equinox?: number
}

export interface WorldPoint {
  /** Longitude (RA) or the linear x-axis value. */
  lon: number
  /** Latitude (Dec) or the linear y-axis value. */
  lat: number
}

export type Projection = 'tan' | 'linear'

const DEG = Math.PI / 180
const RAD = 180 / Math.PI
const LON_TYPES = ['RA--', 'GLON', 'ELON', 'HLON', 'SLON']
const LAT_TYPES = ['DEC-', 'GLAT', 'ELAT', 'HLAT', 'SLAT']

function celestialKind(ctype: string): 'lon' | 'lat' | null {
  const head = ctype.slice(0, 4).toUpperCase()
  if (LON_TYPES.includes(head)) return 'lon'
  if (LAT_TYPES.includes(head)) return 'lat'
  return null
}

function projectionCode(ctype: string): string {
  const parts = ctype.split('-').filter(Boolean)
  return parts.length > 1 ? (parts[parts.length - 1]?.toUpperCase() ?? '') : ''
}

function wrap360(value: number): number {
  const wrapped = value % 360
  return wrapped < 0 ? wrapped + 360 : wrapped
}

/** 2×2 celestial (or generic 2-axis) WCS built from the first two axes of a header dict. */
export class Wcs2D {
  readonly projection: Projection
  readonly celestial: boolean
  /** Index (0 or 1) of the longitude axis inside the 2-axis system; `null` for linear WCS. */
  readonly lonAxis: 0 | 1 | null
  readonly ctype: [string, string]
  readonly cunit: [string, string]
  readonly crval: [number, number]
  readonly crpix: [number, number]
  /** Linear part: intermediate world = M · (p − crpix), with p 1-based. */
  readonly matrix: [number, number, number, number]
  readonly inverse: [number, number, number, number]
  readonly lonpole: number

  constructor(dict: WcsDict) {
    if (!dict || dict.naxis < 2 || !dict.ctype || dict.ctype.length < 2) {
      throw new Error('a 2-axis WCS is required')
    }
    this.ctype = [dict.ctype[0] ?? '', dict.ctype[1] ?? '']
    this.cunit = [dict.cunit?.[0] ?? '', dict.cunit?.[1] ?? '']
    this.crval = [dict.crval[0] ?? 0, dict.crval[1] ?? 0]
    this.crpix = [dict.crpix[0] ?? 1, dict.crpix[1] ?? 1]
    const cdelt: [number, number] = [dict.cdelt?.[0] ?? 1, dict.cdelt?.[1] ?? 1]

    let m: [number, number, number, number]
    // A cube written with CDELT1/2 for the sky and CD3_3 for the wavelength leaves the spatial 2x2
    // block of `cd` empty; falling through to CDELT is what astropy and rbcodes both do.
    const cd = dict.cd && dict.cd.length >= 2 ? dict.cd : null
    const spatialCd = cd
      ? ([cd[0]?.[0] ?? 0, cd[0]?.[1] ?? 0, cd[1]?.[0] ?? 0, cd[1]?.[1] ?? 0] as const)
      : null
    if (spatialCd && spatialCd[0] * spatialCd[3] - spatialCd[1] * spatialCd[2] !== 0) {
      m = [spatialCd[0], spatialCd[1], spatialCd[2], spatialCd[3]]
    } else if (dict.pc && dict.pc.length >= 2) {
      m = [
        cdelt[0] * (dict.pc[0]?.[0] ?? 1),
        cdelt[0] * (dict.pc[0]?.[1] ?? 0),
        cdelt[1] * (dict.pc[1]?.[0] ?? 0),
        cdelt[1] * (dict.pc[1]?.[1] ?? 1),
      ]
    } else if (typeof dict.crota2 === 'number' && dict.crota2 !== 0) {
      const rot = dict.crota2 * DEG
      m = [
        cdelt[0] * Math.cos(rot),
        -cdelt[1] * Math.sin(rot),
        cdelt[0] * Math.sin(rot),
        cdelt[1] * Math.cos(rot),
      ]
    } else {
      m = [cdelt[0], 0, 0, cdelt[1]]
    }
    this.matrix = m
    const det = m[0] * m[3] - m[1] * m[2]
    if (!Number.isFinite(det) || det === 0) throw new Error('singular WCS matrix')
    this.inverse = [m[3] / det, -m[1] / det, -m[2] / det, m[0] / det]

    const kinds = [celestialKind(this.ctype[0]), celestialKind(this.ctype[1])]
    const codes = [projectionCode(this.ctype[0]), projectionCode(this.ctype[1])]
    this.celestial =
      (kinds[0] === 'lon' && kinds[1] === 'lat') || (kinds[0] === 'lat' && kinds[1] === 'lon')
    this.lonAxis = this.celestial ? (kinds[0] === 'lon' ? 0 : 1) : null
    this.projection = this.celestial && codes[0] === 'TAN' && codes[1] === 'TAN' ? 'tan' : 'linear'
    const latAxis = this.lonAxis === 0 ? 1 : 0
    const defaultLonpole = this.crval[latAxis] >= 90 ? 0 : 180
    this.lonpole = typeof dict.lonpole === 'number' ? dict.lonpole : defaultLonpole
  }

  /** Intermediate world coordinates (degrees or axis units) of a 0-based pixel. */
  intermediate(x: number, y: number): [number, number] {
    const dx = x + 1 - this.crpix[0]
    const dy = y + 1 - this.crpix[1]
    const m = this.matrix
    return [m[0] * dx + m[1] * dy, m[2] * dx + m[3] * dy]
  }

  /** World coordinates (RA/Dec in degrees for celestial TAN; axis values otherwise). */
  pixelToWorld(x: number, y: number): WorldPoint {
    const [ix, iy] = this.intermediate(x, y)
    if (this.projection !== 'tan' || this.lonAxis === null) {
      return { lon: this.crval[0] + ix, lat: this.crval[1] + iy }
    }
    const xs = this.lonAxis === 0 ? ix : iy
    const ys = this.lonAxis === 0 ? iy : ix
    const r = Math.hypot(xs, ys)
    const phi = r === 0 ? 0 : Math.atan2(xs, -ys)
    const theta = r === 0 ? Math.PI / 2 : Math.atan(RAD / r)
    const alphaP = this.crval[this.lonAxis] * DEG
    const deltaP = this.crval[this.lonAxis === 0 ? 1 : 0] * DEG
    const phiP = this.lonpole * DEG
    const dphi = phi - phiP
    const sinDelta =
      Math.sin(theta) * Math.sin(deltaP) + Math.cos(theta) * Math.cos(deltaP) * Math.cos(dphi)
    const ya = -Math.cos(theta) * Math.sin(dphi)
    const xa =
      Math.sin(theta) * Math.cos(deltaP) - Math.cos(theta) * Math.sin(deltaP) * Math.cos(dphi)
    // atan2 keeps full precision near the pole where asin(sinDelta) would not.
    const delta = Math.atan2(sinDelta, Math.hypot(xa, ya))
    const alpha = alphaP + Math.atan2(ya, xa)
    return { lon: wrap360(alpha * RAD), lat: delta * RAD }
  }

  /** Inverse of `pixelToWorld` (0-based pixel coordinates). */
  worldToPixel(lon: number, lat: number): { x: number; y: number } {
    let ix: number
    let iy: number
    if (this.projection !== 'tan' || this.lonAxis === null) {
      ix = lon - this.crval[0]
      iy = lat - this.crval[1]
    } else {
      const alphaP = this.crval[this.lonAxis] * DEG
      const deltaP = this.crval[this.lonAxis === 0 ? 1 : 0] * DEG
      const phiP = this.lonpole * DEG
      const alpha = lon * DEG
      const delta = lat * DEG
      const dalpha = alpha - alphaP
      const yp = -Math.cos(delta) * Math.sin(dalpha)
      const xp =
        Math.sin(delta) * Math.cos(deltaP) - Math.cos(delta) * Math.sin(deltaP) * Math.cos(dalpha)
      const phi = phiP + Math.atan2(yp, xp)
      const sinTheta =
        Math.sin(delta) * Math.sin(deltaP) + Math.cos(delta) * Math.cos(deltaP) * Math.cos(dalpha)
      // cos(theta) is the length of the atan2 arguments: exact where asin would lose digits.
      const cosTheta = Math.hypot(xp, yp)
      const r = sinTheta === 0 ? Number.POSITIVE_INFINITY : (RAD * cosTheta) / sinTheta
      const xs = r * Math.sin(phi)
      const ys = -r * Math.cos(phi)
      ix = this.lonAxis === 0 ? xs : ys
      iy = this.lonAxis === 0 ? ys : xs
    }
    const inv = this.inverse
    return {
      x: inv[0] * ix + inv[1] * iy + this.crpix[0] - 1,
      y: inv[2] * ix + inv[3] * iy + this.crpix[1] - 1,
    }
  }

  /** Approximate pixel scale along each axis, in the world unit per pixel (degrees for celestial). */
  pixelScale(): [number, number] {
    const m = this.matrix
    return [Math.hypot(m[0], m[2]), Math.hypot(m[1], m[3])]
  }
}

/** Build a `Wcs2D` from a header dict, or `null` when it is missing or unusable. */
export function wcsFromDict(dict: WcsDict | null | undefined): Wcs2D | null {
  if (!dict) return null
  try {
    return new Wcs2D(dict)
  } catch {
    return null
  }
}

function pad(value: number, width: number): string {
  return String(value).padStart(width, '0')
}

/** Right ascension in degrees as `hh:mm:ss.ss`. */
export function formatRa(deg: number, decimals = 2): string {
  const hours = wrap360(deg) / 15
  const h = Math.floor(hours)
  const m = Math.floor((hours - h) * 60)
  const s = ((hours - h) * 60 - m) * 60
  const sText = s.toFixed(decimals).padStart(decimals + 3, '0')
  return `${pad(h, 2)}:${pad(m, 2)}:${sText}`
}

/** Declination in degrees as `±dd:mm:ss.s`. */
export function formatDec(deg: number, decimals = 1): string {
  const sign = deg < 0 ? '-' : '+'
  const abs = Math.abs(deg)
  const d = Math.floor(abs)
  const m = Math.floor((abs - d) * 60)
  const s = ((abs - d) * 60 - m) * 60
  const sText = s.toFixed(decimals).padStart(decimals + 3, '0')
  return `${sign}${pad(d, 2)}:${pad(m, 2)}:${sText}`
}

/** Angular separation between two celestial points in arcseconds (haversine). */
export function separationArcsec(a: WorldPoint, b: WorldPoint): number {
  const dlat = (b.lat - a.lat) * DEG
  const dlon = (b.lon - a.lon) * DEG
  const h =
    Math.sin(dlat / 2) ** 2 +
    Math.cos(a.lat * DEG) * Math.cos(b.lat * DEG) * Math.sin(dlon / 2) ** 2
  return 2 * Math.asin(Math.min(1, Math.sqrt(h))) * RAD * 3600
}
