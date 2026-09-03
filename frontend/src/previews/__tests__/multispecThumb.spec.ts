import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { i18n } from '@/i18n'
import MultispecThumb from '@/previews/renderers/MultispecThumb.vue'

const MGII_Z = 1.3855

function panel(lo: number, hi: number, n = 20) {
  const wave = Array.from({ length: n }, (_, i) => lo + ((hi - lo) * i) / (n - 1))
  return {
    type: 'astro.Spectrum1D',
    n,
    range: [lo, hi],
    wave,
    // A null pixel breaks the path, as SDSS ivar = 0 columns do.
    flux: wave.map((w, i) => (i === 3 ? null : 10 + Math.sin(w / 30))),
    frame: 'observed',
    z: null,
    v0_wrest: null,
  }
}

const SUMMARY = {
  type: 'rbcodes.MultispecView',
  count: 6,
  labels: ['a', 'b'],
  range: [4000, 8000],
  z: MGII_Z,
  linelist: 'LLS',
  panels: [
    panel(4000, 8000),
    panel(4000, 8000),
    panel(4000, 8000),
    panel(4000, 8000),
    panel(4000, 8000),
  ],
  absorbers: [
    { zabs: MGII_Z, linelist: 'LLS', color: 'sky_blue', visible: true, label: '' },
    { zabs: 9, linelist: 'LLS', color: 'orange', visible: true, label: '' },
  ],
  identified: [
    { name: 'MgII 2796', wave_obs: 6670.7, zabs: MGII_Z, wave_rest: 2796.354, spectrum: 'a' },
  ],
}

function mountThumb(summary: Record<string, unknown>) {
  return mount(MultispecThumb, {
    props: { nodeId: 'viewer', port: 'view', typeId: 'rbcodes.MultispecView', summary, width: 240 },
    global: { plugins: [i18n] },
  })
}

describe('MultispecThumb', () => {
  it('draws at most four panels with absorber and identification ticks', () => {
    const wrapper = mountThumb(SUMMARY)
    const root = wrapper.find('[data-preview="multispec-thumb"]')
    expect(root.attributes('data-panels')).toBe('6')
    expect(root.attributes('data-absorbers')).toBe('2')
    expect(root.attributes('data-lines')).toBe('1')
    expect(wrapper.findAll('path')).toHaveLength(4)
    // One tick per identified line; the systems appear as coloured chips instead.
    expect(wrapper.findAll('[data-marker]')).toHaveLength(1)
    const chips = wrapper.findAll('[data-testid="multispec-thumb-absorber"]')
    expect(chips).toHaveLength(2)
    expect(chips[0]?.text()).toBe('1.385500')
    expect(wrapper.get('[data-testid="multispec-thumb-z"]').text()).toBe('z = 1.385500')
    expect(wrapper.text()).toContain('6 spectra')
    // The null pixel splits the path into two subpaths.
    const d = wrapper.get('path').attributes('d') ?? ''
    expect(d.split('M')).toHaveLength(3)
  })

  it('falls back to the empty state without panels', () => {
    const wrapper = mountThumb({ type: 'rbcodes.MultispecView', panels: [] })
    expect(wrapper.find('svg').exists()).toBe(false)
    expect(wrapper.find('[data-preview="multispec-thumb"]').attributes('data-panels')).toBe('0')
  })

  it('ignores a summary of another type', () => {
    const wrapper = mountThumb({ wave: [1, 2], flux: [1, 2] })
    expect(wrapper.find('svg').exists()).toBe(false)
    expect(wrapper.find('[data-testid="multispec-thumb-z"]').exists()).toBe(false)
  })
})
