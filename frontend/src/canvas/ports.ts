/**
 * Port presentation: colour-blind-safe Okabe–Ito colours plus a shape glyph per type family
 * (design §10.3). Well-known core types get fixed assignments; unknown types are hashed onto the
 * palette so a pack's custom type is stable across sessions.
 */

export const OKABE_ITO = {
  orange: '#E69F00',
  skyBlue: '#56B4E9',
  green: '#009E73',
  yellow: '#F0E442',
  blue: '#0072B2',
  vermillion: '#D55E00',
  purple: '#CC79A7',
  grey: '#999999',
  black: '#000000',
} as const

export type PortGlyph = 'circle' | 'diamond' | 'square' | 'hexagon' | 'ring' | 'triangle'

export interface PortStyle {
  color: string
  glyph: PortGlyph
}

const PALETTE: readonly string[] = [
  OKABE_ITO.orange,
  OKABE_ITO.skyBlue,
  OKABE_ITO.green,
  OKABE_ITO.yellow,
  OKABE_ITO.blue,
  OKABE_ITO.vermillion,
  OKABE_ITO.purple,
]

const KNOWN: Readonly<Record<string, PortStyle>> = {
  'astro.Float': { color: OKABE_ITO.grey, glyph: 'circle' },
  'astro.Int': { color: OKABE_ITO.grey, glyph: 'circle' },
  'astro.Str': { color: OKABE_ITO.grey, glyph: 'circle' },
  'astro.Bool': { color: OKABE_ITO.grey, glyph: 'circle' },
  'astro.Json': { color: OKABE_ITO.purple, glyph: 'ring' },
  'astro.Any': { color: OKABE_ITO.black, glyph: 'ring' },
  'astro.File': { color: OKABE_ITO.orange, glyph: 'square' },
  'astro.Spectrum1D': { color: OKABE_ITO.blue, glyph: 'diamond' },
  'astro.SpectrumCollection': { color: OKABE_ITO.skyBlue, glyph: 'diamond' },
  'astro.Table': { color: OKABE_ITO.green, glyph: 'square' },
  'astro.Image2D': { color: OKABE_ITO.vermillion, glyph: 'hexagon' },
  'astro.Cube3D': { color: OKABE_ITO.purple, glyph: 'hexagon' },
  'astro.LineList': { color: OKABE_ITO.orange, glyph: 'triangle' },
  'astro.Transition': { color: OKABE_ITO.orange, glyph: 'triangle' },
  'astro.Redshift': { color: OKABE_ITO.yellow, glyph: 'triangle' },
  'astro.Continuum': { color: OKABE_ITO.green, glyph: 'diamond' },
  'astro.RangeMask': { color: OKABE_ITO.green, glyph: 'triangle' },
  'astro.Region2D': { color: OKABE_ITO.skyBlue, glyph: 'hexagon' },
  'astro.EWMeasurement': { color: OKABE_ITO.blue, glyph: 'square' },
  'astro.Figure': { color: OKABE_ITO.purple, glyph: 'square' },
}

function hash(text: string): number {
  let h = 2166136261
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

const GLYPHS: readonly PortGlyph[] = ['circle', 'diamond', 'square', 'hexagon', 'triangle']

/** Colour and glyph for a port type id. */
export function portStyle(typeId: string): PortStyle {
  const known = KNOWN[typeId]
  if (known) return known
  const h = hash(typeId)
  return {
    color: PALETTE[h % PALETTE.length] ?? OKABE_ITO.grey,
    glyph: GLYPHS[(h >>> 8) % GLYPHS.length] ?? 'circle',
  }
}

/** Short label for a type id (`astro.Spectrum1D` → `Spectrum1D`). */
export function typeLabel(typeId: string): string {
  const dot = typeId.lastIndexOf('.')
  return dot === -1 ? typeId : typeId.slice(dot + 1)
}
