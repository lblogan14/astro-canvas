/**
 * IRAF/ds9 zscale display limits (the algorithm astropy's `ZScaleInterval` implements): sample the
 * image, sort, fit a line through the sorted values with iterative sigma rejection, and expand the
 * slope around the median by `1 / contrast`.
 */

export interface ZScaleOptions {
  nsamples?: number
  contrast?: number
  maxReject?: number
  minNpixels?: number
  krej?: number
  maxIterations?: number
}

const DEFAULTS: Required<ZScaleOptions> = {
  nsamples: 1000,
  contrast: 0.25,
  maxReject: 0.5,
  minNpixels: 5,
  krej: 2.5,
  maxIterations: 5,
}

function finiteSample(values: ArrayLike<number>, nsamples: number): number[] {
  const n = values.length
  const stride = Math.max(1, Math.floor(n / nsamples))
  const out: number[] = []
  for (let i = 0; i < n && out.length < nsamples; i += stride) {
    const v = values[i]
    if (v !== undefined && Number.isFinite(v)) out.push(v)
  }
  if (out.length < Math.min(nsamples, n) / 2) {
    // The stride skipped too many NaNs: fall back to every finite value.
    out.length = 0
    for (let i = 0; i < n; i += 1) {
      const v = values[i]
      if (v !== undefined && Number.isFinite(v)) out.push(v)
    }
  }
  return out
}

/** Display limits `[lo, hi]` for `values` (NaNs ignored). */
export function zscale(values: ArrayLike<number>, options: ZScaleOptions = {}): [number, number] {
  const opts = { ...DEFAULTS, ...options }
  const samples = finiteSample(values, opts.nsamples).sort((a, b) => a - b)
  const npix = samples.length
  if (npix === 0) return [0, 1]
  let vmin = samples[0] ?? 0
  let vmax = samples[npix - 1] ?? vmin
  if (npix < opts.minNpixels || vmin === vmax) return [vmin, vmax]

  const minpix = Math.max(opts.minNpixels, Math.floor(npix * opts.maxReject))
  const x = samples.map((_, i) => i)
  const ngrow = Math.max(1, Math.floor(npix * 0.01))
  const badpix = new Uint8Array(npix)
  let ngoodpix = npix
  let lastNgoodpix = npix + 1
  let slope = 0
  let intercept = 0

  for (let iter = 0; iter < opts.maxIterations; iter += 1) {
    if (ngoodpix >= lastNgoodpix || ngoodpix < minpix) break
    // Least squares line through the good pixels.
    let sx = 0
    let sy = 0
    let sxx = 0
    let sxy = 0
    for (let i = 0; i < npix; i += 1) {
      if (badpix[i]) continue
      const xi = x[i] ?? 0
      const yi = samples[i] ?? 0
      sx += xi
      sy += yi
      sxx += xi * xi
      sxy += xi * yi
    }
    const denom = ngoodpix * sxx - sx * sx
    slope = denom === 0 ? 0 : (ngoodpix * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / ngoodpix
    // Residuals and their robust sigma over the good pixels.
    let sumsq = 0
    const resid = new Float64Array(npix)
    for (let i = 0; i < npix; i += 1) {
      resid[i] = (samples[i] ?? 0) - (intercept + slope * (x[i] ?? 0))
      if (!badpix[i]) sumsq += (resid[i] ?? 0) ** 2
    }
    const sigma = Math.sqrt(sumsq / Math.max(1, ngoodpix))
    const threshold = opts.krej * sigma
    lastNgoodpix = ngoodpix
    const newBad = new Uint8Array(npix)
    for (let i = 0; i < npix; i += 1) {
      if (Math.abs(resid[i] ?? 0) > threshold) newBad[i] = 1
    }
    // Grow rejected pixels by ngrow on each side (convolution with a box kernel).
    for (let i = 0; i < npix; i += 1) {
      if (!newBad[i]) continue
      for (let j = Math.max(0, i - ngrow); j <= Math.min(npix - 1, i + ngrow); j += 1) badpix[j] = 1
    }
    ngoodpix = 0
    for (let i = 0; i < npix; i += 1) if (!badpix[i]) ngoodpix += 1
  }

  if (ngoodpix >= minpix) {
    if (opts.contrast > 0) slope /= opts.contrast
    const center = Math.floor((npix - 1) / 2)
    const median =
      npix % 2 === 1
        ? (samples[center] ?? 0)
        : ((samples[center] ?? 0) + (samples[center + 1] ?? 0)) / 2
    // Same asymmetric bounds as IRAF/astropy (center_pixel - 1 below, npix - center_pixel above).
    vmin = Math.max(vmin, median - (center - 1) * slope)
    vmax = Math.min(vmax, median + (npix - center) * slope)
  }
  return [vmin, vmax]
}

/** Simple min/max over finite values. */
export function minmax(values: ArrayLike<number>): [number, number] {
  let lo = Number.POSITIVE_INFINITY
  let hi = Number.NEGATIVE_INFINITY
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i]
    if (v === undefined || !Number.isFinite(v)) continue
    if (v < lo) lo = v
    if (v > hi) hi = v
  }
  return lo <= hi ? [lo, hi] : [0, 1]
}

/** Percentile limits `[p_lo, p_hi]` over finite values (linear interpolation). */
export function percentileLimits(
  values: ArrayLike<number>,
  lo = 1,
  hi = 99,
  maxSamples = 20000,
): [number, number] {
  const finite = finiteSample(values, maxSamples).sort((a, b) => a - b)
  if (finite.length === 0) return [0, 1]
  const pick = (p: number): number => {
    const idx = ((finite.length - 1) * p) / 100
    const low = Math.floor(idx)
    const high = Math.min(finite.length - 1, low + 1)
    const frac = idx - low
    return (finite[low] ?? 0) * (1 - frac) + (finite[high] ?? 0) * frac
  }
  return [pick(lo), pick(hi)]
}
