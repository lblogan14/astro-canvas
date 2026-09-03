import { describe, expect, it } from 'vitest'

import {
  C_RB,
  clampRange,
  extent,
  readRange,
  roundVelocity,
  velocityAxis,
  viewWindow,
} from '@/editors/rangeSelect'

describe('range-select helpers', () => {
  it('reads vmin/vmax from params with defaults and ordering', () => {
    expect(readRange({ vmin: -150, vmax: 150 })).toEqual([-150, 150])
    expect(readRange({ vmin: 150, vmax: -150 })).toEqual([-150, 150])
    expect(readRange({})).toEqual([-200, 200])
    expect(readRange({ vmin: 'x' }, { vmin: -1500, vmax: 1500 })).toEqual([-1500, 1500])
  })

  it('clamps to the data bounds and keeps a minimum width', () => {
    expect(clampRange(300, -300, [-1000, 1000])).toEqual([-300, 300])
    expect(clampRange(-5000, 5000, [-1000, 1000])).toEqual([-1000, 1000])
    expect(clampRange(10, 10, null, 20)).toEqual([0, 20])
    expect(clampRange(-5, 5, null)).toEqual([-5, 5])
    expect(roundVelocity(12.3456)).toBe(12.3)
    expect(roundVelocity(12.3456, 2)).toBe(12.35)
  })

  it('builds velocity axes with rbcodes constant for every frame', () => {
    const wrest = 2796.352
    const rest = velocityAxis([wrest, wrest * (1 + 100 / C_RB)], 'rest', wrest, null)
    expect(rest[0]).toBeCloseTo(0, 9)
    expect(rest[1]).toBeCloseTo(100, 6)
    const observed = velocityAxis([wrest * 2.3855], 'observed', wrest, 1.3855)
    expect(observed[0]).toBeCloseTo(0, 6)
    const velocity = velocityAxis([-10, 10], 'velocity', wrest, null)
    expect(Array.from(velocity)).toEqual([-10, 10])
  })

  it('pads the view around the range inside the data extent', () => {
    expect(viewWindow([-200, 200], null)).toEqual([-400, 400])
    expect(viewWindow([-200, 200], [-300, 1000])).toEqual([-300, 400])
    expect(extent([3, Number.NaN, -1, 7])).toEqual([-1, 7])
    expect(extent([])).toBeNull()
    expect(extent([Number.NaN])).toBeNull()
  })
})
