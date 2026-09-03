import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/i18n'

const { FakeUPlot, instances } = vi.hoisted(() => {
  interface Hooks {
    draw?: ((u: unknown) => void)[]
    setCursor?: ((u: unknown) => void)[]
    setSelect?: ((u: unknown) => void)[]
  }
  const strokes: { x: number; dash: number[] }[] = []
  const labels: string[] = []
  class FakeUPlot {
    static strokes = strokes
    static labels = labels
    opts: { hooks?: Hooks; scales?: Record<string, unknown>; series?: unknown[] } & Record<
      string,
      unknown
    >
    data: unknown[]
    destroyed = false
    redrawn = 0
    scales: Record<string, unknown> = {}
    select = { left: 0, top: 0, width: 0, height: 0 }
    cursor: { left?: number; top?: number } = {}
    bbox = { left: 0, top: 0, width: 100, height: 50 }
    root = document.createElement('div')
    ctx = {
      save: () => undefined,
      restore: () => undefined,
      beginPath: () => undefined,
      rect: () => undefined,
      clip: () => undefined,
      moveTo: (x: number) => strokes.push({ x, dash: this.dash }),
      lineTo: () => undefined,
      stroke: () => undefined,
      fillText: (text: string) => labels.push(text),
      translate: () => undefined,
      rotate: () => undefined,
      setLineDash: (dash: number[]) => {
        this.dash = dash
      },
      font: '',
      textAlign: '',
      textBaseline: '',
      strokeStyle: '',
      fillStyle: '',
      lineWidth: 0,
    }
    dash: number[] = []
    constructor(opts: Record<string, unknown>, data: unknown[]) {
      this.opts = opts as FakeUPlot['opts']
      this.data = data
      instances.push(this)
    }
    valToPos(value: number): number {
      return value
    }
    posToVal(pos: number): number {
      return pos
    }
    setSize(): void {}
    setScale(name: string, range: unknown): void {
      this.scales[name] = range
    }
    setSelect(): void {
      this.select = { left: 0, top: 0, width: 0, height: 0 }
    }
    redraw(): void {
      this.redrawn += 1
    }
    destroy(): void {
      this.destroyed = true
    }
  }
  const instances: FakeUPlot[] = []
  return { FakeUPlot, instances }
})
type FakeUPlot = InstanceType<typeof FakeUPlot>

vi.mock('uplot', () => ({ default: FakeUPlot }))
vi.mock('uplot/dist/uPlot.min.css', () => ({}))

import MultispecPanel from '@/editors/MultispecPanel.vue'
import type { SpectrumSeries } from '@/widgets/spectrumSeries'

function series(n = 40): SpectrumSeries {
  const wave = Array.from({ length: n }, (_, i) => 4000 + i * 10)
  return {
    wave,
    flux: wave.map((w) => 10 + Math.sin(w / 30)),
    error: wave.map(() => 0.4),
    continuum: null,
    waveUnit: 'Angstrom',
    fluxUnit: '',
    frame: 'observed',
    z: null,
    v0Wrest: null,
    n,
    range: [wave[0] ?? 0, wave[n - 1] ?? 0],
  }
}

describe('MultispecPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    instances.length = 0
    FakeUPlot.strokes.length = 0
    FakeUPlot.labels.length = 0
  })

  function mountPanel(props: Record<string, unknown> = {}) {
    return mount(MultispecPanel, {
      props: { series: series(), ...props },
      global: { plugins: [i18n] },
    })
  }

  it('builds the flux line with an error band and a shared x scale', () => {
    const wrapper = mountPanel({ xRange: [4100, 4200], label: 'sdss1.fits' })
    const chart = instances[0]!
    // x, flux, +sigma, -sigma
    expect(chart.data).toHaveLength(4)
    expect(chart.opts.series).toHaveLength(4)
    const xScale = (chart.opts.scales as Record<string, { range?: () => number[] }>)['x']
    expect(xScale?.range?.()).toEqual([4100, 4200])
    expect(wrapper.attributes('data-label')).toBe('sdss1.fits')
    expect(wrapper.text()).toContain('sdss1.fits')
  })

  it('omits the error band when it is switched off', () => {
    mountPanel({ showError: false })
    expect(instances[0]!.data).toHaveLength(2)
  })

  it('draws the markers with labels and the fit model', () => {
    mountPanel({
      markers: [
        { x: 20, label: 'MgII 2796', color: '#f00' },
        { x: 40, label: 'MgII 2803', color: '#0f0', dash: true },
        { x: 5000, label: 'off screen' },
      ],
      model: { x: [10, 20, 30], y: [1, 2, 1] },
    })
    const chart = instances[0]!
    chart.opts.hooks?.draw?.[0]?.(chart)
    // Two markers inside the 0-100 bbox plus the model curve's first point.
    expect(FakeUPlot.strokes.map((s) => s.x)).toEqual([20, 40, 10])
    expect(FakeUPlot.strokes[1]?.dash).toEqual([4, 3])
    expect(FakeUPlot.labels).toEqual(['MgII 2796', 'MgII 2803'])
  })

  it('hides the labels when asked', () => {
    mountPanel({ markers: [{ x: 20, label: 'MgII 2796' }], showLabels: false })
    const chart = instances[0]!
    chart.opts.hooks?.draw?.[0]?.(chart)
    expect(FakeUPlot.labels).toEqual([])
  })

  it('emits hover, click and select in data coordinates', async () => {
    const wrapper = mountPanel()
    const chart = instances[0]!
    chart.cursor = { left: 4321, top: 12 }
    chart.opts.hooks?.setCursor?.[0]?.(chart)
    expect(wrapper.emitted('hover')?.[0]).toEqual([4321, 12])

    await wrapper.trigger('click')
    expect(wrapper.emitted('click')?.[0]).toEqual([4321, 12])

    chart.select = { left: 100, top: 0, width: 60, height: 10 }
    chart.opts.hooks?.setSelect?.[0]?.(chart)
    expect(wrapper.emitted('select')?.[0]).toEqual([100, 160])
    // A stray click (no drag) is ignored.
    chart.select = { left: 100, top: 0, width: 1, height: 10 }
    chart.opts.hooks?.setSelect?.[0]?.(chart)
    expect(wrapper.emitted('select')).toHaveLength(1)
  })

  it('redraws in place when only the markers change and destroys the chart on unmount', async () => {
    const wrapper = mountPanel()
    const chart = instances[0]!
    await wrapper.setProps({ markers: [{ x: 4100 }] })
    expect(instances).toHaveLength(1)
    expect(chart.redrawn).toBeGreaterThan(0)
    // A new series rebuilds the chart.
    await wrapper.setProps({ series: series(10) })
    expect(instances).toHaveLength(2)
    expect(chart.destroyed).toBe(true)
    wrapper.unmount()
    expect(instances[1]!.destroyed).toBe(true)
  })

  it('renders nothing without a series', () => {
    mountPanel({ series: null })
    expect(instances).toHaveLength(0)
  })
})
