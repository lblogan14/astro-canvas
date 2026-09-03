import { describe, expect, it } from 'vitest'

import {
  DOUBLETS,
  doubletPartner,
  linesFromSummary,
  nearestTransitions,
  toPlotX,
  toRestWavelength,
} from '@/editors/linePicker'

const SUMMARY = {
  type: 'astro.LineList',
  n: 4,
  wrest: [1215.6701, 2796.352, 2803.531, 2852.96],
  name: ['HI 1215', 'MgII 2796', 'MgII 2803', 'MgI 2852'],
  fval: [0.4164, 0.6123, 0.3054, 1.83],
}

describe('line picker helpers', () => {
  it('reads parallel arrays from a LineList summary', () => {
    const lines = linesFromSummary(SUMMARY)
    expect(lines).toHaveLength(4)
    expect(lines[1]).toEqual({ name: 'MgII 2796', wrest: 2796.352, fval: 0.6123 })
    expect(linesFromSummary(undefined)).toEqual([])
    expect(linesFromSummary({ wrest: [1, 'x'], name: ['a', 'b'] })).toEqual([
      { name: 'a', wrest: 1, fval: 0 },
    ])
  })

  it('ranks the nearest transitions with wavelength and velocity offsets', () => {
    const lines = linesFromSummary(SUMMARY)
    const near = nearestTransitions(lines, 2800, 2)
    expect(near.map((c) => c.name)).toEqual(['MgII 2803', 'MgII 2796'])
    expect(near[0]?.delta).toBeCloseTo(3.531, 6)
    expect(near[0]?.deltaKms).toBeCloseTo((3.531 * 2.9979e5) / 2800, 3)
    expect(nearestTransitions(lines, 2800)).toHaveLength(4)
  })

  it('knows the common resonance doublets both ways', () => {
    expect(DOUBLETS.length).toBeGreaterThan(5)
    const blue = doubletPartner(2796.35)
    expect(blue?.species).toBe('MgII')
    expect(blue?.partner).toBeCloseTo(2803.531)
    expect(blue?.offsetKms).toBeCloseTo(769.7, 0)
    const red = doubletPartner(2803.53)
    expect(red?.partner).toBeCloseTo(2796.352)
    expect(red?.offsetKms).toBeLessThan(0)
    expect(doubletPartner(1215.67)).toBeNull()
  })

  it('converts between plot positions and rest wavelengths per frame', () => {
    expect(toRestWavelength(2796.352, 'rest', null, null)).toBe(2796.352)
    expect(toRestWavelength(2796.352 * 2.3855, 'observed', 1.3855, null)).toBeCloseTo(2796.352, 6)
    expect(toRestWavelength(0, 'velocity', null, 2796.352)).toBe(2796.352)
    expect(toRestWavelength(0, 'velocity', null, null)).toBeNull()
    expect(toPlotX(2796.352, 'rest', null, null)).toBe(2796.352)
    expect(toPlotX(2796.352, 'observed', 1.3855, null)).toBeCloseTo(2796.352 * 2.3855, 6)
    expect(toPlotX(2803.531, 'velocity', null, 2796.352)).toBeCloseTo(769.7, 0)
    expect(toPlotX(2803.531, 'velocity', null, null)).toBeNull()
  })
})
