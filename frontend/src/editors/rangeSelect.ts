/**
 * Pure helpers for the `range-select` editor (`rbcodes.absorption.slice`, `compute_ew`):
 * velocity axes, clamping and the view window around a transition.
 */
import type { SpectrumSeries } from '@/widgets'

/** rbcodes' rounded speed of light; the nodes use it, so the editors do too. */
export const C_RB = 2.9979e5

export interface RangeParams {
  vmin: number
  vmax: number
}

/** `[vmin, vmax]` from arbitrary param values, with defaults and ordering fixed. */
export function readRange(
  params: Record<string, unknown>,
  defaults: RangeParams = { vmin: -200, vmax: 200 },
): [number, number] {
  const lo = typeof params['vmin'] === 'number' ? params['vmin'] : defaults.vmin
  const hi = typeof params['vmax'] === 'number' ? params['vmax'] : defaults.vmax
  return lo <= hi ? [lo, hi] : [hi, lo]
}

/** Order the pair, keep both inside `bounds` and at least `minWidth` apart. */
export function clampRange(
  lo: number,
  hi: number,
  bounds: [number, number] | null,
  minWidth = 1,
): [number, number] {
  let a = Math.min(lo, hi)
  let b = Math.max(lo, hi)
  if (bounds) {
    a = Math.max(bounds[0], Math.min(bounds[1], a))
    b = Math.max(bounds[0], Math.min(bounds[1], b))
  }
  if (b - a < minWidth) {
    const mid = (a + b) / 2
    a = mid - minWidth / 2
    b = mid + minWidth / 2
  }
  return [a, b]
}

/** Round to a sensible number of decimals for a param field. */
export function roundVelocity(value: number, decimals = 1): number {
  const factor = 10 ** decimals
  return Math.round(value * factor) / factor
}

/** Velocity of every pixel relative to `wrest` (km/s) with rbcodes' constant. */
export function velocityAxis(
  wave: ArrayLike<number>,
  frame: SpectrumSeries['frame'],
  wrest: number,
  z: number | null,
): Float64Array {
  const out = new Float64Array(wave.length)
  if (frame === 'velocity') {
    for (let i = 0; i < wave.length; i += 1) out[i] = wave[i] ?? Number.NaN
    return out
  }
  const center = frame === 'observed' ? wrest * (1 + (z ?? 0)) : wrest
  for (let i = 0; i < wave.length; i += 1) {
    out[i] = (((wave[i] ?? Number.NaN) - center) * C_RB) / center
  }
  return out
}

/** A comfortable x window around the range: the range widened by `pad` on each side. */
export function viewWindow(
  range: [number, number],
  bounds: [number, number] | null,
  pad = 0.5,
): [number, number] {
  const width = range[1] - range[0]
  const lo = range[0] - width * pad
  const hi = range[1] + width * pad
  if (!bounds) return [lo, hi]
  return [Math.max(bounds[0], lo), Math.min(bounds[1], hi)]
}

/** Min/max of a numeric array ignoring NaNs (`null` when empty). */
export function extent(values: ArrayLike<number>): [number, number] | null {
  let lo = Number.POSITIVE_INFINITY
  let hi = Number.NEGATIVE_INFINITY
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i]
    if (v === undefined || Number.isNaN(v)) continue
    if (v < lo) lo = v
    if (v > hi) hi = v
  }
  return lo <= hi ? [lo, hi] : null
}
