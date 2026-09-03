import { describe, expect, it } from 'vitest'

import {
  addMask,
  bicRows,
  continuumOverlay,
  formatMask,
  maskAt,
  masksEqual,
  masksFromParam,
  paramsFromSettings,
  removeMask,
  removeMaskAt,
  settingsEqual,
  settingsFromParams,
  sortMasks,
} from '@/editors/continuumMask'

describe('continuum mask ranges', () => {
  it('parses param values leniently and orders each pair', () => {
    expect(masksFromParam(undefined)).toEqual([])
    expect(masksFromParam('nope')).toEqual([])
    expect(masksFromParam([[250, -300], [500, 1000], [1, 'x'], [3], null])).toEqual([
      [-300, 250],
      [500, 1000],
    ])
    expect(
      sortMasks([
        [500, 1000],
        [-300, 250],
      ]),
    ).toEqual([
      [-300, 250],
      [500, 1000],
    ])
  })

  it('adds ranges and merges overlaps or touching neighbours', () => {
    const one = addMask([], 100, -100)
    expect(one).toEqual([[-100, 100]])
    const two = addMask(one, 400, 600)
    expect(two).toEqual([
      [-100, 100],
      [400, 600],
    ])
    // Overlapping both existing ranges collapses everything into one.
    expect(addMask(two, 50, 450)).toEqual([[-100, 600]])
    // Touching at the edge merges too.
    expect(addMask(two, 600, 700)).toEqual([
      [-100, 100],
      [400, 700],
    ])
  })

  it('removes by index or by position', () => {
    const masks: [number, number][] = [
      [-300, 250],
      [500, 1000],
    ]
    expect(removeMask(masks, 0)).toEqual([[500, 1000]])
    expect(maskAt(masks, 600)).toBe(1)
    expect(maskAt(masks, 300)).toBe(-1)
    expect(removeMaskAt(masks, 0)).toEqual([[500, 1000]])
    expect(removeMaskAt(masks, 300)).toBe(masks)
    expect(
      masksEqual(masks, [
        [-300, 250],
        [500, 1000],
      ]),
    ).toBe(true)
    expect(masksEqual(masks, [[-300, 250]])).toBe(false)
    expect(formatMask([-300.4, 250])).toBe('-300 to 250')
  })

  it('maps node params to editor settings and back', () => {
    const settings = settingsFromParams({
      method: 'spline',
      order: 4.2,
      optimize_order: false,
      masks: [[10, 20]],
    })
    expect(settings).toEqual({
      method: 'spline',
      order: 4,
      optimizeOrder: false,
      masks: [[10, 20]],
    })
    expect(settingsFromParams({})).toEqual({
      method: 'polynomial',
      order: 3,
      optimizeOrder: true,
      masks: [],
    })
    expect(settingsFromParams({ method: 'bogus', order: 'x' }).method).toBe('polynomial')
    expect(paramsFromSettings(settings)).toEqual({
      method: 'spline',
      order: 4,
      optimize_order: false,
      masks: [[10, 20]],
    })
    expect(settingsEqual(settings, settingsFromParams(paramsFromSettings(settings)))).toBe(true)
    expect(settingsEqual(settings, { ...settings, order: 5 })).toBe(false)
  })
})

describe('continuum summary readers', () => {
  const summary = {
    type: 'astro.Continuum',
    n: 4,
    index: [0, 1, 2, 3],
    cont: [1, 2, 3, 4],
    order: 1,
    params: {
      bic_results: [
        [0, -10],
        [1, -12.5],
        [2, -11],
        ['x', 1],
      ],
    },
  }

  it('lists BIC rows and marks the fitted order as best', () => {
    const rows = bicRows(summary)
    expect(rows.map((r) => r.order)).toEqual([0, 1, 2])
    expect(rows.find((r) => r.best)?.order).toBe(1)
    // Without an explicit order the lowest BIC wins.
    const noOrder = bicRows({ ...summary, order: undefined })
    expect(noOrder.find((r) => r.best)?.order).toBe(1)
    expect(bicRows(undefined)).toEqual([])
    expect(bicRows({ params: {} })).toEqual([])
  })

  it('aligns the continuum with the spectrum grid through index', () => {
    const overlay = continuumOverlay(summary, [-3, -1, 1, 3])
    expect(overlay).toEqual({ x: [-3, -1, 1, 3], y: [1, 2, 3, 4] })
    const strided = continuumOverlay({ cont: [10, 30], index: [0, 2] }, [-3, -1, 1, 3])
    expect(strided).toEqual({ x: [-3, 1], y: [10, 30] })
    expect(continuumOverlay({ cont: [1, 2], index: [0, 9] }, [-3, -1])).toEqual({ x: [-3], y: [1] })
    expect(continuumOverlay(undefined, [1])).toBeNull()
    expect(continuumOverlay({ cont: 'x' }, [1])).toBeNull()
  })
})
