/**
 * zscale against astropy's `ZScaleInterval`, plus the tile decode/paint path used by ImageView.
 */
import { describe, expect, it } from 'vitest'

import { colormapLut } from '@/lib/colormaps'
import {
  decodeFloat32Base64,
  decodeTile,
  isTileSummary,
  limitsFor,
  paintTile,
  sampleTile,
  tileFromArray,
} from '@/lib/tile'
import { minmax, percentileLimits, zscale } from '@/lib/zscale'
import reference from '@/lib/__tests__/fixtures/zscale_reference.json'

interface ZRef {
  data: (number | null)[]
  limits: [number, number]
  small: number[]
  small_limits: [number, number]
}

const ref = reference as ZRef

function encodeF32(values: number[]): string {
  const buffer = new ArrayBuffer(values.length * 4)
  const view = new DataView(buffer)
  values.forEach((v, i) => view.setFloat32(i * 4, v, true))
  return btoa(String.fromCharCode(...new Uint8Array(buffer)))
}

describe('zscale', () => {
  it('matches astropy within 3 % of the range on a noisy image with hot pixels', () => {
    const data = Float64Array.from(ref.data.map((v) => (v === null ? Number.NaN : v)))
    const [lo, hi] = zscale(data)
    const span = ref.limits[1] - ref.limits[0]
    expect(Math.abs(lo - ref.limits[0])).toBeLessThan(0.03 * span)
    expect(Math.abs(hi - ref.limits[1])).toBeLessThan(0.03 * span)
    expect(lo).toBeGreaterThan(60)
    expect(hi).toBeLessThan(200) // hot pixels rejected
  })

  it('matches astropy on a small sample and handles degenerate input', () => {
    const [lo, hi] = zscale(Float64Array.from(ref.small))
    const span = ref.small_limits[1] - ref.small_limits[0]
    expect(Math.abs(lo - ref.small_limits[0])).toBeLessThan(0.05 * span)
    expect(Math.abs(hi - ref.small_limits[1])).toBeLessThan(0.05 * span)
    expect(zscale([])).toEqual([0, 1])
    expect(zscale([Number.NaN, Number.NaN])).toEqual([0, 1])
    expect(zscale([3, 3, 3, 3, 3, 3])).toEqual([3, 3])
    expect(zscale([1, 2])).toEqual([1, 2])
    expect(minmax([Number.NaN, 4, -1, 9])).toEqual([-1, 9])
    expect(minmax([Number.NaN])).toEqual([0, 1])
    const [p1, p99] = percentileLimits([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 10, 90)
    expect(p1).toBeCloseTo(1.9)
    expect(p99).toBeCloseTo(9.1)
  })
})

describe('tile decode and paint', () => {
  const values = [0, 1, 2, 3, 4, 5]
  const summary = {
    width: 3,
    height: 2,
    step: 2,
    dtype: 'f4',
    b64: encodeF32(values),
    zscale: [0, 5] as [number, number],
    minmax: [0, 5] as [number, number],
    percentile: [0.1, 4.9] as [number, number],
  }

  it('decodes base64 float32 without JSON', () => {
    expect(Array.from(decodeFloat32Base64(summary.b64))).toEqual(values)
    expect(isTileSummary(summary)).toBe(true)
    expect(isTileSummary({ width: 1 })).toBe(false)
    const tile = decodeTile(summary)
    expect(tile.data).toBeInstanceOf(Float32Array)
    expect(sampleTile(tile, 4, 2)).toBe(5) // data coords / step → column 2, row 1
    expect(sampleTile(tile, 0, 0)).toBe(0)
    expect(Number.isNaN(sampleTile(tile, 99, 0))).toBe(true)
    expect(limitsFor(tile, 'minmax')).toEqual([0, 5])
    expect(limitsFor(tile, 'percentile')).toEqual([0.1, 4.9])
    expect(limitsFor(tile, 'manual', [1, 2])).toEqual([1, 2])
    expect(limitsFor(tile, 'manual')).toEqual([0, 5])
  })

  it('paints bottom row first with the colour map and marks NaN pixels', () => {
    const tile = tileFromArray(Float32Array.from([0, Number.NaN, 5, 5]), 2, 2)
    expect(tile.minmax).toEqual([0, 5])
    const image = { width: 2, height: 2, data: new Uint8ClampedArray(16) } as ImageData
    paintTile(tile, image, { scale: 'minmax', stretch: 'linear', colormap: 'gray' })
    // Row 0 of the ImageData shows data row 1 (top of the image): both 5 → white.
    expect(Array.from(image.data.slice(0, 4))).toEqual([255, 255, 255, 255])
    expect(Array.from(image.data.slice(4, 8))).toEqual([255, 255, 255, 255])
    // Data row 0: value 0 → black, NaN → the NaN colour.
    expect(Array.from(image.data.slice(8, 12))).toEqual([0, 0, 0, 255])
    expect(Array.from(image.data.slice(12, 16))).toEqual([20, 20, 24, 255])
    paintTile(tile, image, { scale: 'minmax', stretch: 'asinh', colormap: 'viridis' })
    const lut = colormapLut('viridis')
    expect(Array.from(image.data.slice(8, 11))).toEqual(Array.from(lut.slice(0, 3)))
    paintTile(tile, image, { scale: 'manual', limits: [4, 6], stretch: 'log', colormap: 'gray' })
    expect(image.data[8]).toBe(0) // 0 clamps below the manual lower limit
    expect(image.data[0]).toBeGreaterThan(100) // 5 within [4, 6] on a log stretch
    paintTile(tile, image, { scale: 'minmax', stretch: 'sqrt', colormap: 'gray' })
    expect(image.data[0]).toBe(255)
  })
})
