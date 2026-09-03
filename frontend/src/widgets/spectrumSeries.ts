/**
 * Spectrum data as the widgets consume it, built from a `node.output.summary` payload
 * (`Spectrum1D.summary`) or from a decoded binary frame (full arrays as typed arrays).
 */
import type { DecodedFrame } from '@/api/frames'

export type Frame = 'observed' | 'rest' | 'velocity'

export interface SpectrumSeries {
  wave: ArrayLike<number>
  flux: ArrayLike<number>
  error?: ArrayLike<number> | null
  continuum?: ArrayLike<number> | null
  waveUnit: string
  fluxUnit: string
  frame: Frame
  z: number | null
  v0Wrest: number | null
  /** Total points in the source spectrum (the series itself may be decimated). */
  n: number
  /** Full axis range of the source spectrum. */
  range: [number, number] | null
}

export const C_KMS = 299792.458

function numbers(value: unknown): number[] | null {
  return Array.isArray(value) && value.every((v) => typeof v === 'number' || v === null)
    ? (value as (number | null)[]).map((v) => (v === null ? Number.NaN : v))
    : null
}

/** Build a series from a `Spectrum1D.summary()` payload; `null` when it is not one. */
export function seriesFromSummary(summary: Record<string, unknown>): SpectrumSeries | null {
  const wave = numbers(summary['wave'])
  const flux = numbers(summary['flux'])
  if (!wave || !flux || wave.length !== flux.length) return null
  const range = numbers(summary['range'])
  return {
    wave,
    flux,
    error: numbers(summary['error']),
    continuum: numbers(summary['continuum']),
    waveUnit: typeof summary['wave_unit'] === 'string' ? summary['wave_unit'] : 'Angstrom',
    fluxUnit: typeof summary['flux_unit'] === 'string' ? summary['flux_unit'] : '',
    frame: (summary['frame'] as Frame | undefined) ?? 'observed',
    z: typeof summary['z'] === 'number' ? summary['z'] : null,
    v0Wrest: typeof summary['v0_wrest'] === 'number' ? summary['v0_wrest'] : null,
    n: typeof summary['n'] === 'number' ? summary['n'] : wave.length,
    range: range && range.length === 2 ? [range[0] ?? 0, range[1] ?? 0] : null,
  }
}

/** Build a series from a decoded `astro.Spectrum1D` binary frame (typed arrays, no copies). */
export function seriesFromFrame(frame: DecodedFrame): SpectrumSeries | null {
  if (frame.header.type_id !== 'astro.Spectrum1D') return null
  const wave = frame.arrays['wave']?.view
  const flux = frame.arrays['flux']?.view
  if (!wave || !flux || wave.length !== flux.length) return null
  const data = frame.header.data
  const asNumbers = (view: ArrayLike<number> | undefined): ArrayLike<number> | null =>
    view && view.length === wave.length ? view : null
  return {
    wave: wave as ArrayLike<number>,
    flux: flux as ArrayLike<number>,
    error: asNumbers(frame.arrays['error']?.view as ArrayLike<number> | undefined),
    continuum: asNumbers(frame.arrays['continuum']?.view as ArrayLike<number> | undefined),
    waveUnit: typeof data['wave_unit'] === 'string' ? data['wave_unit'] : 'Angstrom',
    fluxUnit: typeof data['flux_unit'] === 'string' ? data['flux_unit'] : '',
    frame: (data['frame'] as Frame | undefined) ?? 'observed',
    z: typeof data['z'] === 'number' ? data['z'] : null,
    v0Wrest: typeof data['v0_wrest'] === 'number' ? data['v0_wrest'] : null,
    n: wave.length,
    range: wave.length ? [Number(wave[0] ?? 0), Number(wave[wave.length - 1] ?? 0)] : null,
  }
}

/** Velocity axis (km/s) relative to `wrest` at redshift `z` (rbcodes convention). */
export function toVelocity(wave: ArrayLike<number>, wrest: number, z: number | null): Float64Array {
  const center = wrest * (1 + (z ?? 0))
  const out = new Float64Array(wave.length)
  for (let i = 0; i < wave.length; i += 1) out[i] = C_KMS * ((wave[i] ?? 0) / center - 1)
  return out
}

/** Axis label for the current frame/unit. */
export function axisLabel(series: Pick<SpectrumSeries, 'frame' | 'waveUnit'>): string {
  if (series.frame === 'velocity') return 'v (km/s)'
  return series.frame === 'rest' ? `λ rest (${series.waveUnit})` : `λ (${series.waveUnit})`
}

/** Finite min/max of the flux (used for tight axes). */
export function fluxRange(series: SpectrumSeries): [number, number] {
  let lo = Number.POSITIVE_INFINITY
  let hi = Number.NEGATIVE_INFINITY
  const { flux } = series
  for (let i = 0; i < flux.length; i += 1) {
    const v = flux[i]
    if (v === undefined || !Number.isFinite(v)) continue
    if (v < lo) lo = v
    if (v > hi) hi = v
  }
  if (!(lo <= hi)) return [0, 1]
  if (lo === hi) return [lo - 1, hi + 1]
  const pad = (hi - lo) * 0.05
  return [lo - pad, hi + pad]
}
