import { describe, expect, it } from 'vitest'

import { COLORMAP_NAMES, colormapGradient, colormapLut, isColormapName } from '../colormaps'

describe('colormaps', () => {
  it('produces 256 opaque RGBA entries for every map', () => {
    for (const name of COLORMAP_NAMES) {
      const lut = colormapLut(name)
      expect(lut.length).toBe(1024)
      for (let i = 3; i < lut.length; i += 4) expect(lut[i]).toBe(255)
      expect(colormapLut(name)).toBe(lut) // memoised
    }
  })

  it('matches the matplotlib end points approximately', () => {
    const viridis = colormapLut('viridis')
    expect(Array.from(viridis.slice(0, 3))).toEqual([71, 1, 85])
    expect(viridis[255 * 4]).toBeGreaterThan(240) // yellow end
    expect(viridis[255 * 4 + 2]).toBeLessThan(60)
    const gray = colormapLut('gray')
    expect(Array.from(gray.slice(128 * 4, 128 * 4 + 3))).toEqual([128, 128, 128])
    const magma = colormapLut('magma')
    expect(magma[0]).toBeLessThan(10)
    const helix = colormapLut('cubehelix')
    expect(helix[255 * 4]).toBe(255)
  })

  it('renders a CSS gradient and validates names', () => {
    expect(colormapGradient('gray', 3)).toBe(
      'linear-gradient(to right, rgb(0, 0, 0), rgb(128, 128, 128), rgb(255, 255, 255))',
    )
    expect(isColormapName('viridis')).toBe(true)
    expect(isColormapName('jet')).toBe(false)
  })
})
