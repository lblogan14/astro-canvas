import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import { i18n } from '@/i18n'
import MomentThumbs from '@/previews/renderers/MomentThumbs.vue'
import { previewBudget, rendererFor, rendererFromSummary } from '@/previews/registry'

function tile(width = 8, height = 6, base = 0) {
  const values = new Float32Array(width * height)
  for (let i = 0; i < values.length; i += 1) values[i] = base + (i % 5)
  let binary = ''
  for (const byte of new Uint8Array(values.buffer)) binary += String.fromCharCode(byte)
  return {
    width,
    height,
    step: 1,
    dtype: 'f4',
    b64: btoa(binary),
    zscale: [base, base + 4],
    minmax: [base, base + 4],
    percentile: [base, base + 4],
  }
}

const SUMMARY = {
  type: 'rbcodes.MomentMaps',
  shape: [6, 8],
  unit: 'erg / (s cm2)',
  lambda_rest: 5007,
  window: [4980, 5035],
  wcs: null,
  maps: [
    { key: 'm0', unit: 'erg / (s cm2)', tile: tile() },
    { key: 'm1', unit: 'km/s', tile: tile(8, 6, -120) },
    { key: 'm2', unit: 'km/s', tile: tile(8, 6, 40) },
  ],
}

function render(summary: Record<string, unknown>) {
  return mount(MomentThumbs, {
    props: { nodeId: 'maps', port: 'out', typeId: 'rbcodes.MomentMaps', summary, width: 240 },
    global: { plugins: [i18n] },
  })
}

describe('moment-thumbs', () => {
  it('renders one thumbnail per map with its own limits', () => {
    const wrapper = render(SUMMARY)
    expect(wrapper.attributes('data-maps')).toBe('3')
    const figures = wrapper.findAll('figure')
    expect(figures).toHaveLength(3)
    expect(figures.map((f) => f.attributes('data-map'))).toEqual(['m0', 'm1', 'm2'])
    expect(figures[0]?.text()).toContain('M0')
    expect(figures[1]?.text()).toContain('km/s')
    // Each map keeps its own scaling: the velocity map's range is negative.
    expect(figures[1]?.text()).toContain('-120')
  })

  it('shows the line window and the field size', () => {
    const text = render(SUMMARY).text()
    expect(text).toContain('4980')
    expect(text).toContain('6 × 8 px')
  })

  it('survives a summary with no maps', () => {
    const wrapper = render({ type: 'rbcodes.MomentMaps', shape: [6, 8], maps: [] })
    expect(wrapper.attributes('data-maps')).toBe('0')
    expect(wrapper.text()).toContain('No output yet')
  })

  it('drops map entries without a tile', () => {
    const wrapper = render({ ...SUMMARY, maps: [{ key: 'm0' }, SUMMARY.maps[1]] })
    expect(wrapper.attributes('data-maps')).toBe('1')
  })

  it('is chosen by the renderer registry', () => {
    expect(rendererFromSummary(SUMMARY)).toBe('moment-thumbs')
    expect(rendererFor(undefined, { summary_renderer: 'moment-thumbs' } as never, undefined)).toBe(
      'moment-thumbs',
    )
    // A cube summary still resolves to the cube renderer, not this one.
    expect(rendererFromSummary({ shape: [2, 3, 4], tile: tile() })).toBe('cube-thumb')
  })

  it('asks for a third of the node width per tile', () => {
    expect(previewBudget('moment-thumbs', 300)).toBe(100)
    expect(previewBudget('moment-thumbs', 30)).toBe(48)
    expect(previewBudget('moment-thumbs', 3000)).toBe(256)
  })
})
