import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/i18n'

const { FakeUPlot, instances } = vi.hoisted(() => {
  class FakeUPlot {
    opts: Record<string, unknown>
    data: unknown[]
    destroyed = false
    size: { width: number; height: number } | null = null
    select = { left: 0, top: 0, width: 0, height: 0 }
    constructor(opts: Record<string, unknown>, data: unknown[], _target: HTMLElement) {
      this.opts = opts
      this.data = data
      instances.push(this)
    }
    setSize(size: { width: number; height: number }): void {
      this.size = size
    }
    destroy(): void {
      this.destroyed = true
    }
    posToVal(pos: number, _scale: string): number {
      return pos * 10
    }
    setSelect(): void {
      this.select = { left: 0, top: 0, width: 0, height: 0 }
    }
  }
  const instances: FakeUPlot[] = []
  return { FakeUPlot, instances }
})
type FakeUPlot = InstanceType<typeof FakeUPlot>

vi.mock('uplot', () => ({ default: FakeUPlot }))
vi.mock('uplot/dist/uPlot.min.css', () => ({}))

import UPlotLine from '../uPlotLine.vue'
import {
  axisLabel,
  fluxRange,
  seriesFromFrame,
  seriesFromSummary,
  toVelocity,
  type SpectrumSeries,
} from '../spectrumSeries'

function series(n = 50, withError = true): SpectrumSeries {
  const wave = Array.from({ length: n }, (_, i) => 4000 + i)
  const flux = wave.map((w) => Math.sin(w / 5) + 2)
  return {
    wave,
    flux,
    error: withError ? wave.map(() => 0.1) : null,
    continuum: wave.map(() => 2),
    waveUnit: 'Angstrom',
    fluxUnit: 'erg / (s cm2 Angstrom)',
    frame: 'observed',
    z: null,
    v0Wrest: null,
    n,
    range: [4000, 4000 + n - 1],
  }
}

describe('spectrumSeries', () => {
  it('builds a series from a summary payload and rejects other payloads', () => {
    const summary = {
      type: 'astro.Spectrum1D',
      n: 3,
      range: [1, 3],
      wave: [1, 2, 3],
      flux: [1, null, 3],
      error: [0.1, 0.1, 0.1],
      wave_unit: 'Angstrom',
      flux_unit: 'Jy',
      frame: 'rest',
      z: 0.5,
      v0_wrest: null,
    }
    const s = seriesFromSummary(summary)
    expect(s).not.toBeNull()
    expect(s?.frame).toBe('rest')
    expect(s?.z).toBe(0.5)
    expect(Number.isNaN(s ? (s.flux as number[])[1] : 0)).toBe(true)
    expect(s?.range).toEqual([1, 3])
    expect(seriesFromSummary({ type: 'astro.Float', data: { value: 1 } })).toBeNull()
    expect(seriesFromSummary({ wave: [1, 2], flux: [1] })).toBeNull()
  })

  it('builds a series from a binary frame without copying typed arrays', () => {
    const wave = new Float64Array([1, 2, 3])
    const flux = new Float64Array([4, 5, 6])
    const frame = {
      msgType: 1,
      header: {
        node_id: 'n',
        port: 'out',
        type_id: 'astro.Spectrum1D',
        data: { wave_unit: 'nm', flux_unit: 'x', frame: 'observed', z: null },
        arrays: [],
      },
      arrays: {
        wave: { dtype: 'f8', shape: [3], view: wave },
        flux: { dtype: 'f8', shape: [3], view: flux },
      },
    }
    const s = seriesFromFrame(frame)
    expect(s?.wave).toBe(wave)
    expect(s?.waveUnit).toBe('nm')
    expect(s?.range).toEqual([1, 3])
    expect(
      seriesFromFrame({ ...frame, header: { ...frame.header, type_id: 'astro.Table' } }),
    ).toBeNull()
  })

  it('computes velocity axes, labels and flux ranges', () => {
    const v = toVelocity([1215.67 * 2, 1215.67 * 2 * 1.001], 1215.67, 1.0)
    expect(v[0]).toBeCloseTo(0, 6)
    expect(v[1]).toBeCloseTo(299.79, 1)
    expect(axisLabel({ frame: 'velocity', waveUnit: 'km / s' })).toBe('v (km/s)')
    expect(axisLabel({ frame: 'rest', waveUnit: 'Angstrom' })).toBe('λ rest (Angstrom)')
    expect(fluxRange(series(10))[0]).toBeLessThan(1.6)
    expect(fluxRange({ ...series(3), flux: [Number.NaN, Number.NaN, Number.NaN] })).toEqual([0, 1])
    expect(fluxRange({ ...series(2), flux: [2, 2] })).toEqual([1, 3])
  })
})

describe('UPlotLine', () => {
  beforeEach(() => {
    instances.length = 0
  })

  it('renders flux, an error band and the continuum as aligned series', () => {
    const wrapper = mount(UPlotLine, {
      props: { series: series(20), height: 70 },
      global: { plugins: [i18n] },
    })
    expect(instances).toHaveLength(1)
    const chart = instances[0] as FakeUPlot
    expect(chart.data).toHaveLength(5) // x, flux, +σ, −σ, continuum
    expect((chart.data[2] as number[])[0]).toBeCloseTo(((chart.data[1] as number[])[0] ?? 0) + 0.1)
    expect((chart.opts['bands'] as unknown[]).length).toBe(1)
    expect((chart.opts['series'] as unknown[]).length).toBe(5)
    expect(chart.opts['height']).toBe(70)
    expect(wrapper.attributes('data-points')).toBe('20')
    wrapper.unmount()
    expect(chart.destroyed).toBe(true)
  })

  it('re-renders when the series changes and hides the band without errors', async () => {
    const wrapper = mount(UPlotLine, {
      props: { series: series(10, false), showContinuum: false },
      global: { plugins: [i18n] },
    })
    expect(instances[0]?.data).toHaveLength(2)
    await wrapper.setProps({ series: series(30) })
    expect(instances).toHaveLength(2)
    expect(instances[0]?.destroyed).toBe(true)
    expect(instances[1]?.data).toHaveLength(4) // continuum stays hidden
    await wrapper.setProps({ series: null })
    expect(wrapper.attributes('data-points')).toBe('0')
  })

  it('uses a velocity axis when a rest wavelength is given and emits view changes', async () => {
    const wrapper = mount(UPlotLine, {
      props: { series: series(10), velocityWrest: 4000, axes: true },
      global: { plugins: [i18n] },
    })
    const chart = instances[0] as FakeUPlot
    expect((chart.data[0] as number[])[0]).toBeCloseTo(0)
    const axes = chart.opts['axes'] as { label?: string }[]
    expect(axes[0]?.label).toBe('v (km/s)')
    const hooks = chart.opts['hooks'] as { setSelect: ((u: FakeUPlot) => void)[] }
    chart.select = { left: 10, top: 0, width: 20, height: 10 }
    hooks.setSelect[0]?.(chart)
    expect(wrapper.emitted('view-change')?.[0]).toEqual([[100, 300]])
    await wrapper.trigger('dblclick')
    expect(wrapper.emitted('view-change')?.[1]).toEqual([null])
  })
})
