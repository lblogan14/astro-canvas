import { describe, expect, it } from 'vitest'

import { Wcs2D, formatDec, formatRa, separationArcsec, wcsFromDict, type WcsDict } from '../wcs'
import reference from './fixtures/wcs_reference.json'

interface Case {
  name: string
  wcs: WcsDict
  samples: { pixel: number[]; world: number[]; back: number[] }[]
}

const cases = reference as Case[]

describe('Wcs2D against astropy', () => {
  for (const testCase of cases) {
    it(`${testCase.name}: pixel → world within 0.1" and back within 0.01 px`, () => {
      const wcs = new Wcs2D(testCase.wcs)
      for (const sample of testCase.samples) {
        const [x, y] = sample.pixel as [number, number]
        // astropy returns world values in axis order; map them onto lon/lat by the lon axis.
        const [w0, w1] = sample.world as [number, number]
        const [lon, lat] = wcs.lonAxis === 1 ? [w1, w0] : [w0, w1]
        const world = wcs.pixelToWorld(x, y)
        // Celestial: angular separation in arcsec; linear: plain distance in axis units.
        const error = wcs.celestial
          ? separationArcsec(world, { lon, lat })
          : Math.hypot(world.lon - lon, world.lat - lat)
        expect(error).toBeLessThan(wcs.celestial ? 0.1 : 1e-9)
        const back = wcs.worldToPixel(lon, lat)
        expect(back.x).toBeCloseTo(x, 2)
        expect(back.y).toBeCloseTo(y, 2)
      }
    })
  }

  it('classifies projections and axis order', () => {
    const byName = Object.fromEntries(cases.map((c) => [c.name, new Wcs2D(c.wcs)]))
    expect(byName['synthetic_image.fits']?.projection).toBe('tan')
    expect(byName['synthetic_image.fits']?.lonAxis).toBe(0)
    expect(byName['pc-swapped-axes']?.lonAxis).toBe(1)
    expect(byName['linear']?.projection).toBe('linear')
    expect(byName['linear']?.celestial).toBe(false)
    expect(byName['synthetic_kcwi_icubes.fits']?.celestial).toBe(true)
    const scale = byName['synthetic_image.fits']?.pixelScale() ?? [0, 0]
    expect(scale[0] * 3600).toBeCloseTo(0.09, 3)
  })

  it('rejects unusable dicts and formats sexagesimal', () => {
    expect(wcsFromDict(null)).toBeNull()
    expect(
      wcsFromDict({ naxis: 1, ctype: ['WAVE'], crval: [1], crpix: [1], cdelt: [1] }),
    ).toBeNull()
    expect(
      wcsFromDict({
        naxis: 2,
        ctype: ['RA---TAN', 'DEC--TAN'],
        crval: [0, 0],
        crpix: [1, 1],
        cdelt: [0, 0],
      }),
    ).toBeNull()
    expect(formatRa(150.1234)).toBe('10:00:29.62')
    expect(formatDec(-5.3911)).toBe('-05:23:28.0')
    expect(formatDec(2.5678, 2)).toBe('+02:34:04.08')
    expect(formatRa(-15)).toBe('23:00:00.00')
  })

  it('handles the pole and the reference pixel', () => {
    const wcs = new Wcs2D({
      naxis: 2,
      ctype: ['RA---TAN', 'DEC--TAN'],
      crval: [10, 89.9],
      crpix: [50, 50],
      cdelt: [-0.001, 0.001],
    })
    const centre = wcs.pixelToWorld(49, 49)
    expect(centre.lon).toBeCloseTo(10, 6)
    expect(centre.lat).toBeCloseTo(89.9, 6)
    expect(wcs.lonpole).toBe(180)
    const roundTrip = wcs.worldToPixel(centre.lon, centre.lat)
    expect(roundTrip.x).toBeCloseTo(49, 6)
    expect(roundTrip.y).toBeCloseTo(49, 6)
  })
})
