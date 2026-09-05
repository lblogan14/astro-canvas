/**
 * The port palette under colour-vision deficiency (phase 13, scope item 3).
 *
 * Wire colour is how a user reads a graph at a glance, so it may not be the *only* channel: every
 * port type also carries a glyph. What is checked here is that
 *
 * 1. the palette's colours stay distinguishable from each other when simulated as protanopia,
 *    deuteranopia and tritanopia — the Okabe–Ito set was chosen for exactly this, and a future
 *    addition to it must not quietly break the property;
 * 2. no two known types collide on colour *and* glyph, so a viewer who cannot separate two of the
 *    colours can still separate the ports.
 *
 * The simulation is the Brettel/Viénot linear model on linear-light sRGB, and the distance is
 * CIE76 in Lab, which is coarse but perfectly adequate for "are these two obviously different".
 */
import { describe, expect, it } from 'vitest'

import { OKABE_ITO, portStyle } from '@/canvas/ports'

type Rgb = [number, number, number]

function fromHex(hex: string): Rgb {
  const value = hex.replace('#', '')
  return [0, 2, 4].map((i) => Number.parseInt(value.slice(i, i + 2), 16) / 255) as Rgb
}

const toLinear = (c: number): number => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)

/** Viénot–Brettel–Mollon dichromacy simulation, applied in linear-light sRGB. */
const MATRICES: Record<'protanopia' | 'deuteranopia' | 'tritanopia', number[][]> = {
  protanopia: [
    [0.1121, 0.8853, -0.0005],
    [0.1127, 0.8897, -0.0001],
    [0.0045, 0.0, 1.0019],
  ],
  deuteranopia: [
    [0.292, 0.7054, -0.0003],
    [0.2934, 0.7089, 0.0],
    [-0.0209, 0.0257, 0.9964],
  ],
  tritanopia: [
    [1.0175, 0.1487, -0.1662],
    [0.0, 0.8672, 0.1327],
    [0.0, 0.8672, 0.1327],
  ],
}

function simulate(rgb: Rgb, kind: keyof typeof MATRICES): Rgb {
  const linear = rgb.map(toLinear) as Rgb
  const m = MATRICES[kind]
  return m.map((row) =>
    Math.min(1, Math.max(0, row[0]! * linear[0] + row[1]! * linear[1] + row[2]! * linear[2])),
  ) as Rgb
}

/** Linear-light sRGB to CIE Lab (D65). */
function toLab(linear: Rgb): Rgb {
  const [r, g, b] = linear
  const x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.9505
  const y = 0.2126 * r + 0.7152 * g + 0.0722 * b
  const z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.089
  const f = (t: number): number => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116)
  return [116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))]
}

function distance(a: Rgb, b: Rgb): number {
  const [la, aa, ba] = toLab(a)
  const [lb, ab, bb] = toLab(b)
  return Math.hypot(la - lb, aa - ab, ba - bb)
}

/** Colours used for *wires*; grey and black are reserved for scalars and `astro.Any`. */
const WIRE_COLOURS = [
  OKABE_ITO.orange,
  OKABE_ITO.skyBlue,
  OKABE_ITO.green,
  OKABE_ITO.yellow,
  OKABE_ITO.blue,
  OKABE_ITO.vermillion,
  OKABE_ITO.purple,
] as const

/**
 * CIE76 thresholds. Fifteen Lab units apart is unmistakable side by side, and the Okabe–Ito set
 * clears that for normal vision and for both red-green deficiencies — which is what it was
 * designed for and what all but a fraction of a percent of colour-vision deficiency is.
 *
 * Tritanopia is the exception: orange/purple (11.5), sky blue/green (13.4) and green/blue (10.6)
 * come closer together, so the threshold there is 10 and the *glyph* is what carries the type.
 * That is why the glyph exists, and why the collision test below matters more than this one.
 */
const MIN_DISTANCE = 15
const MIN_DISTANCE_TRITAN = 10

describe('port palette under colour-vision deficiency', () => {
  it('keeps every wire colour distinguishable in normal vision', () => {
    const failures: string[] = []
    for (let i = 0; i < WIRE_COLOURS.length; i += 1) {
      for (let j = i + 1; j < WIRE_COLOURS.length; j += 1) {
        const a = WIRE_COLOURS[i]!
        const b = WIRE_COLOURS[j]!
        const d = distance(fromHex(a).map(toLinear) as Rgb, fromHex(b).map(toLinear) as Rgb)
        if (d < MIN_DISTANCE) failures.push(`${a} vs ${b}: ${d.toFixed(1)}`)
      }
    }
    expect(failures).toEqual([])
  })

  it.each([
    ['protanopia', MIN_DISTANCE],
    ['deuteranopia', MIN_DISTANCE],
    ['tritanopia', MIN_DISTANCE_TRITAN],
  ] as const)('keeps every wire colour distinguishable under %s', (kind, threshold) => {
    const failures: string[] = []
    for (let i = 0; i < WIRE_COLOURS.length; i += 1) {
      for (let j = i + 1; j < WIRE_COLOURS.length; j += 1) {
        const a = WIRE_COLOURS[i]!
        const b = WIRE_COLOURS[j]!
        const d = distance(simulate(fromHex(a), kind), simulate(fromHex(b), kind))
        if (d < threshold) failures.push(`${a} vs ${b}: ${d.toFixed(1)}`)
      }
    }
    expect(failures).toEqual([])
  })

  it('gives every core type a colour/glyph pair of its own', () => {
    // Scalars deliberately share grey + circle: they are interchangeable in the UI.
    const scalars = new Set(['astro.Float', 'astro.Int', 'astro.Str', 'astro.Bool'])
    const types = [
      'astro.Json',
      'astro.Any',
      'astro.File',
      'astro.Spectrum1D',
      'astro.SpectrumCollection',
      'astro.Table',
      'astro.Image2D',
      'astro.Cube3D',
      'astro.LineList',
      'astro.Transition',
      'astro.Redshift',
      'astro.Continuum',
      'astro.RangeMask',
      'astro.Region2D',
      'astro.EWMeasurement',
      'astro.Figure',
      ...scalars,
    ]
    const seen = new Map<string, string>()
    const collisions: string[] = []
    for (const id of types) {
      if (scalars.has(id)) continue
      const { color, glyph } = portStyle(id)
      const key = `${color}/${glyph}`
      const previous = seen.get(key)
      if (previous) collisions.push(`${previous} and ${id} are both ${key}`)
      else seen.set(key, id)
    }
    expect(collisions).toEqual([])
  })

  it('separates types that share a colour by glyph', () => {
    const orange = ['astro.File', 'astro.LineList', 'astro.Transition']
    for (const id of orange) expect(portStyle(id).color).toBe(OKABE_ITO.orange)
    expect(new Set(orange.map((id) => portStyle(id).glyph)).size).toBe(orange.length)
  })
})
