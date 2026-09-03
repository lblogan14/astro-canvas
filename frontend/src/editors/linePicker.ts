/**
 * Pure helpers for the `line-picker` editor (`rbcodes.absorption.set_transition`): nearest
 * transitions of a line list to a clicked wavelength, and doublet partners for hints.
 */

export interface LineEntry {
  name: string
  wrest: number
  fval: number
}

export interface Candidate extends LineEntry {
  /** Offset from the clicked wavelength (Angstrom) and in km/s. */
  delta: number
  deltaKms: number
}

const C_RB = 2.9979e5

/** Parallel arrays of a `LineList` summary into rows. */
export function linesFromSummary(summary: Record<string, unknown> | undefined): LineEntry[] {
  const wrest = summary?.['wrest']
  const name = summary?.['name']
  const fval = summary?.['fval']
  if (!Array.isArray(wrest) || !Array.isArray(name)) return []
  const out: LineEntry[] = []
  for (let i = 0; i < wrest.length; i += 1) {
    const w = wrest[i]
    if (typeof w !== 'number') continue
    const f = Array.isArray(fval) ? fval[i] : 0
    out.push({ name: String(name[i] ?? ''), wrest: w, fval: typeof f === 'number' ? f : 0 })
  }
  return out
}

/** The `count` transitions closest to `wavelength`, nearest first. */
export function nearestTransitions(lines: LineEntry[], wavelength: number, count = 8): Candidate[] {
  return lines
    .map((line) => ({
      ...line,
      delta: line.wrest - wavelength,
      deltaKms: ((line.wrest - wavelength) * C_RB) / wavelength,
    }))
    .sort((a, b) => Math.abs(a.delta) - Math.abs(b.delta))
    .slice(0, count)
}

/** Well-known resonance doublets (rest wavelengths in Angstrom, blue member first). */
export const DOUBLETS: ReadonlyArray<readonly [number, number, string]> = [
  [1031.9261, 1037.6167, 'OVI'],
  [1238.821, 1242.804, 'NV'],
  [1393.755, 1402.77, 'SiIV'],
  [1548.204, 1550.781, 'CIV'],
  [1854.716, 1862.79, 'AlIII'],
  [2796.352, 2803.531, 'MgII'],
  [2586.65, 2600.173, 'FeII'],
]

export interface DoubletHint {
  species: string
  partner: number
  /** Velocity offset of the partner relative to the picked line (km/s). */
  offsetKms: number
}

/** The doublet partner of `wrest` when it is a member of a known doublet (within 0.5 A). */
export function doubletPartner(wrest: number): DoubletHint | null {
  for (const [a, b, species] of DOUBLETS) {
    if (Math.abs(wrest - a) < 0.5) {
      return { species, partner: b, offsetKms: ((b - a) * C_RB) / a }
    }
    if (Math.abs(wrest - b) < 0.5) {
      return { species, partner: a, offsetKms: ((a - b) * C_RB) / b }
    }
  }
  return null
}

/** Rest wavelength of a clicked plot position given the spectrum frame and redshift. */
export function toRestWavelength(
  x: number,
  frame: 'observed' | 'rest' | 'velocity',
  z: number | null,
  v0Wrest: number | null,
): number | null {
  if (frame === 'rest') return x
  if (frame === 'observed') return x / (1 + (z ?? 0))
  if (v0Wrest === null) return null
  return v0Wrest * (1 + x / C_RB)
}

/** Observed wavelength where a rest-frame `wrest` falls for a spectrum in `frame`. */
export function toPlotX(
  wrest: number,
  frame: 'observed' | 'rest' | 'velocity',
  z: number | null,
  v0Wrest: number | null,
): number | null {
  if (frame === 'rest') return wrest
  if (frame === 'observed') return wrest * (1 + (z ?? 0))
  if (v0Wrest === null) return null
  return ((wrest - v0Wrest) * C_RB) / v0Wrest
}
