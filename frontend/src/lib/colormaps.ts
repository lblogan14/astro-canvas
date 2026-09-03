/**
 * Colour maps as 256-entry RGBA lookup tables. viridis/magma/inferno/plasma use the degree-6
 * polynomial fits of the matplotlib maps (Matt Zucker); gray is linear; cubehelix follows
 * D. A. Green (2011) with the standard parameters.
 */

export type ColormapName = 'viridis' | 'gray' | 'magma' | 'cubehelix' | 'inferno' | 'plasma'

export const COLORMAP_NAMES: readonly ColormapName[] = [
  'viridis',
  'gray',
  'magma',
  'cubehelix',
  'inferno',
  'plasma',
]

type Vec3 = [number, number, number]
type Poly = [Vec3, Vec3, Vec3, Vec3, Vec3, Vec3, Vec3]

const POLYS: Record<'viridis' | 'magma' | 'inferno' | 'plasma', Poly> = {
  viridis: [
    [0.2777273272234177, 0.005407344544966578, 0.3340998053353061],
    [0.1050930431085774, 1.404613529898575, 1.384590162594685],
    [-0.3308618287255563, 0.214847559468213, 0.09509516302823659],
    [-4.634230498983486, -5.799100973351585, -19.33244095627987],
    [6.228269936347081, 14.17993336680509, 56.69055260068105],
    [4.776384997670288, -13.74514537774601, -65.35303263337234],
    [-5.435455855934631, 4.645852612178535, 26.3124352495832],
  ],
  magma: [
    [-0.002136485053939582, -0.000749655052795221, -0.005386127855323933],
    [0.2516605407371642, 0.6775232436837668, 2.494026599312351],
    [8.353717279216625, -3.577719514958484, 0.3144679030132573],
    [-27.66873308576866, 14.26473078096533, -13.64921318813922],
    [52.17613981234068, -27.94360607168351, 12.94416944238394],
    [-50.76852536473588, 29.04658282127291, 4.23415299384598],
    [18.65570506591883, -11.48977351997711, -5.601961508734096],
  ],
  inferno: [
    [0.0002189403691192265, 0.001651004631001012, -0.01948089843709184],
    [0.1065134194856116, 0.5639564367884091, 3.932712388889277],
    [11.60249308247187, -3.972853965665698, -15.9423941062914],
    [-41.70399613139459, 17.43639888205313, 44.35414519872813],
    [77.162935699427, -33.40235894210092, -81.80730925738993],
    [-71.31942824499214, 32.62606426397723, 73.20951985803202],
    [25.13112622477341, -12.24266895238567, -23.07032500287172],
  ],
  plasma: [
    [0.05873234392399702, 0.02333670892565664, 0.5433401826748754],
    [2.176514634195958, 0.2383834171260182, 0.7539604599784036],
    [-2.689460476458034, -7.455851135738909, 3.110799939717086],
    [6.130348345893603, 42.3461881477227, -28.51885465332158],
    [-11.10743619062271, -82.66631109428045, 60.13984767418263],
    [10.02306557647065, 71.41361770095349, -54.07218655560067],
    [-3.658713842777788, -22.93153465461149, 18.19190778539828],
  ],
}

function evalPoly(poly: Poly, t: number): Vec3 {
  const out: Vec3 = [0, 0, 0]
  let power = 1
  for (const coeff of poly) {
    out[0] += coeff[0] * power
    out[1] += coeff[1] * power
    out[2] += coeff[2] * power
    power *= t
  }
  return out
}

function cubehelix(t: number): Vec3 {
  // D. A. Green (2011): start = 0.5, rotations = -1.5, hue = 1, gamma = 1.
  const start = 0.5
  const rotations = -1.5
  const hue = 1
  const angle = 2 * Math.PI * (start / 3 + rotations * t + 1)
  const fract = t
  const amp = (hue * fract * (1 - fract)) / 2
  const cos = Math.cos(angle)
  const sin = Math.sin(angle)
  return [
    fract + amp * (-0.14861 * cos + 1.78277 * sin),
    fract + amp * (-0.29227 * cos - 0.90649 * sin),
    fract + amp * (1.97294 * cos),
  ]
}

function clamp01(value: number): number {
  return value < 0 ? 0 : value > 1 ? 1 : value
}

const cache = new Map<ColormapName, Uint8ClampedArray>()

/** 256 × RGBA bytes for `name` (memoised). */
export function colormapLut(name: ColormapName): Uint8ClampedArray {
  const cached = cache.get(name)
  if (cached) return cached
  const lut = new Uint8ClampedArray(256 * 4)
  for (let i = 0; i < 256; i += 1) {
    const t = i / 255
    let rgb: Vec3
    if (name === 'gray') rgb = [t, t, t]
    else if (name === 'cubehelix') rgb = cubehelix(t)
    else rgb = evalPoly(POLYS[name], t)
    lut[i * 4] = Math.round(clamp01(rgb[0]) * 255)
    lut[i * 4 + 1] = Math.round(clamp01(rgb[1]) * 255)
    lut[i * 4 + 2] = Math.round(clamp01(rgb[2]) * 255)
    lut[i * 4 + 3] = 255
  }
  cache.set(name, lut)
  return lut
}

/** CSS gradient stops for a legend bar. */
export function colormapGradient(name: ColormapName, stops = 12): string {
  const lut = colormapLut(name)
  const parts: string[] = []
  for (let i = 0; i < stops; i += 1) {
    const idx = Math.round((i / (stops - 1)) * 255) * 4
    parts.push(`rgb(${lut[idx]}, ${lut[idx + 1]}, ${lut[idx + 2]})`)
  }
  return `linear-gradient(to right, ${parts.join(', ')})`
}

export function isColormapName(value: unknown): value is ColormapName {
  return typeof value === 'string' && (COLORMAP_NAMES as readonly string[]).includes(value)
}
