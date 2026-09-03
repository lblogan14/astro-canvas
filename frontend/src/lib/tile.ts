/**
 * Image tiles as the backend ships them in summaries (`image_tile` in the core pack): base64
 * little-endian float32 rows plus display statistics. This module decodes them and paints them
 * onto a Canvas2D `ImageData` with a scaling, a stretch and a colour map.
 */
import { type ColormapName, colormapLut } from './colormaps'
import { minmax, percentileLimits, zscale } from './zscale'

export interface TileSummary {
  width: number
  height: number
  step: number
  dtype: string
  b64: string
  zscale: [number, number]
  minmax: [number, number]
  percentile: [number, number]
}

export interface DecodedTile {
  width: number
  height: number
  step: number
  data: Float32Array
  zscale: [number, number]
  minmax: [number, number]
  percentile: [number, number]
}

export type ScaleMode = 'zscale' | 'minmax' | 'percentile' | 'manual'
export type Stretch = 'linear' | 'asinh' | 'log' | 'sqrt'

export interface RenderOptions {
  scale: ScaleMode
  stretch: Stretch
  colormap: ColormapName
  /** Used when `scale === 'manual'`. */
  limits?: [number, number]
  /** Paint NaNs with this RGBA (default transparent dark). */
  nan?: [number, number, number, number]
}

export const DEFAULT_RENDER: RenderOptions = {
  scale: 'zscale',
  stretch: 'linear',
  colormap: 'viridis',
}

/** Decode base64 float32 (little-endian) into a `Float32Array` without `JSON.parse` of arrays. */
export function decodeFloat32Base64(b64: string, count?: number): Float32Array {
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  const length = count ?? Math.floor(bytes.byteLength / 4)
  const view = new DataView(bytes.buffer)
  const out = new Float32Array(length)
  for (let i = 0; i < length; i += 1) out[i] = view.getFloat32(i * 4, true)
  return out
}

export function isTileSummary(value: unknown): value is TileSummary {
  if (typeof value !== 'object' || value === null) return false
  const tile = value as Partial<TileSummary>
  return (
    typeof tile.width === 'number' &&
    typeof tile.height === 'number' &&
    typeof tile.b64 === 'string'
  )
}

export function decodeTile(tile: TileSummary): DecodedTile {
  return {
    width: tile.width,
    height: tile.height,
    step: tile.step,
    data: decodeFloat32Base64(tile.b64, tile.width * tile.height),
    zscale: tile.zscale,
    minmax: tile.minmax,
    percentile: tile.percentile,
  }
}

/** A decoded tile from a raw float array (full-resolution data from a binary frame). */
export function tileFromArray(
  data: Float32Array | Float64Array,
  width: number,
  height: number,
): DecodedTile {
  const floats = data instanceof Float32Array ? data : Float32Array.from(data)
  return {
    width,
    height,
    step: 1,
    data: floats,
    zscale: zscale(floats),
    minmax: minmax(floats),
    percentile: percentileLimits(floats),
  }
}

/** Display limits for a tile under `mode`. */
export function limitsFor(
  tile: DecodedTile,
  mode: ScaleMode,
  manual?: [number, number],
): [number, number] {
  switch (mode) {
    case 'minmax':
      return tile.minmax
    case 'percentile':
      return tile.percentile
    case 'manual':
      return manual ?? tile.zscale
    default:
      return tile.zscale
  }
}

function stretchFn(stretch: Stretch): (t: number) => number {
  switch (stretch) {
    case 'asinh': {
      const norm = Math.asinh(10)
      return (t) => Math.asinh(t * 10) / norm
    }
    case 'log':
      return (t) => Math.log10(t * 1000 + 1) / 3
    case 'sqrt':
      return (t) => Math.sqrt(t)
    default:
      return (t) => t
  }
}

/**
 * Paint `tile` into `target` (an `ImageData` of the tile's size). Row 0 of the data is the bottom
 * of the image (FITS convention), so rows are flipped while painting.
 */
export function paintTile(tile: DecodedTile, target: ImageData, options: RenderOptions): void {
  const lut = colormapLut(options.colormap)
  const [lo, hi] = limitsFor(tile, options.scale, options.limits)
  const span = hi - lo || 1
  const stretch = stretchFn(options.stretch)
  const nan = options.nan ?? [20, 20, 24, 255]
  const { width, height, data } = tile
  const out = target.data
  for (let row = 0; row < height; row += 1) {
    const srcRow = height - 1 - row
    for (let col = 0; col < width; col += 1) {
      const value = data[srcRow * width + col] ?? Number.NaN
      const o = (row * width + col) * 4
      if (!Number.isFinite(value)) {
        out[o] = nan[0]
        out[o + 1] = nan[1]
        out[o + 2] = nan[2]
        out[o + 3] = nan[3]
        continue
      }
      let t = (value - lo) / span
      t = t < 0 ? 0 : t > 1 ? 1 : t
      const idx = Math.round(stretch(t) * 255) * 4
      out[o] = lut[idx] ?? 0
      out[o + 1] = lut[idx + 1] ?? 0
      out[o + 2] = lut[idx + 2] ?? 0
      out[o + 3] = 255
    }
  }
}

/** Value at data coordinates (0-based, FITS x right / y up), or `NaN` outside. */
export function sampleTile(tile: DecodedTile, x: number, y: number): number {
  const col = Math.floor(x / tile.step)
  const row = Math.floor(y / tile.step)
  if (col < 0 || row < 0 || col >= tile.width || row >= tile.height) return Number.NaN
  return tile.data[row * tile.width + col] ?? Number.NaN
}
