import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'

import type { NodeSpec } from '@/api/types'
import { WsClient } from '@/api/ws'
import MultispecViewerEditor from '@/editors/MultispecViewerEditor.vue'
import {
  ABSORBER_COLORS,
  LINE_LIST_OPTIONS,
  SHORTCUTS,
  absorbersFromTable,
  cssColor,
  fitCom,
  fitGaussian,
  formatWave,
  formatZabs,
  identifiedFromTable,
  identifyAt,
  nextColor,
  overallRange,
  panelsFromCollection,
  parseView,
  quickIdRedshift,
  tableRows,
  velocityPanels,
} from '@/editors/multispec'
import { i18n } from '@/i18n'
import { useExecutionStore } from '@/stores/execution'
import { useSessionStore } from '@/stores/session'
import { mathChain } from '@/stores/__tests__/fixtures'
import { useWorkflowStore } from '@/stores/workflow'

vi.mock('@/editors/MultispecPanel.vue', () => ({
  default: {
    name: 'MultispecPanel',
    props: ['series', 'markers', 'model', 'xRange', 'yRange', 'showAxis', 'label'],
    emits: ['hover', 'click', 'select'],
    template:
      '<div data-testid="multispec-panel" :data-label="label" :data-markers="markers.length" :data-points="series ? series.wave.length : 0" @click="$emit(\'click\', 6670.7, 2)" @mouseenter="$emit(\'hover\', 6670.7, 2)" @dblclick="$emit(\'select\', 6600, 6740)" />',
  },
}))

class FakeSocket {
  static last: FakeSocket | null = null
  binaryType = 'blob'
  onopen: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  sent: string[] = []
  constructor() {
    FakeSocket.last = this
  }
  send(data: string): void {
    this.sent.push(data)
  }
  close(): void {
    // no-op
  }
}

const MGII_Z = 1.3855

function spectrum(label: string, lo = 4000, hi = 8000, n = 200) {
  const wave = Array.from({ length: n }, (_, i) => lo + ((hi - lo) * i) / (n - 1))
  return {
    type: 'astro.Spectrum1D',
    n,
    range: [lo, hi],
    wave,
    flux: wave.map((w) => 10 + Math.sin(w / 40)),
    error: wave.map(() => 0.5),
    frame: 'observed',
    z: null,
    v0_wrest: null,
    wave_unit: 'Angstrom',
    flux_unit: '',
    meta: { source: label },
  }
}

const COLLECTION = {
  type: 'astro.SpectrumCollection',
  count: 3,
  labels: ['sdss1.fits', 'sdss2.fits', 'galaxy.fits'],
  items: [spectrum('sdss1.fits'), spectrum('sdss2.fits'), spectrum('galaxy.fits')],
}

const LLS_LINES = {
  type: 'astro.LineList',
  n: 3,
  source: 'LLS',
  wrest: [1215.6701, 2796.354, 2803.5315],
  name: ['HI 1215', 'MgII 2796', 'MgII 2803'],
  fval: [0.4164, 0.6155, 0.3058],
}

const VIEW_SUMMARY = {
  type: 'rbcodes.MultispecView',
  count: 3,
  labels: ['sdss1.fits', 'sdss2.fits', 'galaxy.fits'],
  range: [4000, 8000],
  z: MGII_Z,
  linelist: 'LLS',
  panels: [spectrum('sdss1.fits', 4000, 8000, 30), spectrum('sdss2.fits', 4000, 8000, 30)],
  absorbers: [
    { zabs: MGII_Z, linelist: 'LLS', color: 'sky_blue', visible: true, label: 'z=1.3855 (LLS)' },
  ],
  identified: [
    {
      name: 'MgII 2796',
      wave_obs: 6670.7,
      zabs: MGII_Z,
      wave_rest: 2796.354,
      spectrum: 'sdss1.fits',
    },
  ],
}

// --- helpers ------------------------------------------------------------------------------------

describe('multispec helpers', () => {
  it('parses a MultispecView summary', () => {
    const view = parseView(VIEW_SUMMARY)
    expect(view).not.toBeNull()
    expect(view?.count).toBe(3)
    expect(view?.panels).toHaveLength(2)
    expect(view?.range).toEqual([4000, 8000])
    expect(view?.z).toBe(MGII_Z)
    expect(view?.absorbers[0]).toEqual({
      zabs: MGII_Z,
      linelist: 'LLS',
      color: 'sky_blue',
      visible: true,
      label: 'z=1.3855 (LLS)',
    })
    expect(view?.identified[0]).toMatchObject({ name: 'MgII 2796', waveObs: 6670.7 })
    expect(parseView(undefined)).toBeNull()
    expect(parseView({ wave: [1], flux: [1] })).toBeNull()
    // Missing metadata falls back to the panels' own extent.
    const bare = parseView({ panels: [spectrum('a', 100, 200, 10)] })
    expect(bare?.range).toEqual([100, 200])
    expect(bare?.linelist).toBe('LLS')
  })

  it('parses spectrum collections and table summaries in either column convention', () => {
    const { panels, labels, count } = panelsFromCollection(COLLECTION)
    expect(panels).toHaveLength(3)
    expect(labels).toEqual(['sdss1.fits', 'sdss2.fits', 'galaxy.fits'])
    expect(count).toBe(3)
    expect(panelsFromCollection(undefined).panels).toEqual([])
    expect(overallRange(panels)).toEqual([4000, 8000])
    expect(overallRange([])).toBeNull()

    const table = {
      n_rows: 2,
      columns: ['Zabs', 'LineList', 'Color'],
      head: { Zabs: [1.3855, 0.5], LineList: ['LLS', 'DLA'], Color: ['sky_blue', 'orange'] },
    }
    expect(tableRows(table)).toHaveLength(2)
    expect(tableRows(undefined)).toEqual([])
    const absorbers = absorbersFromTable(table)
    expect(absorbers.map((a) => a.linelist)).toEqual(['LLS', 'DLA'])
    expect(absorbers[0]?.visible).toBe(true)
    // The lower-case convention of the node's own parameters parses too.
    expect(absorbersFromTable({ head: { zabs: [2.0], color: ['cyan'] } })[0]).toMatchObject({
      zabs: 2,
      color: 'cyan',
      linelist: 'LLS',
    })
    const lines = identifiedFromTable({
      head: { Name: ['MgII 2796'], Wave_obs: [6670.7], Zabs: [MGII_Z] },
    })
    expect(lines[0]?.waveRest).toBeCloseTo(2796.35, 1)
    expect(identifiedFromTable({ head: { Name: ['x'] } })).toEqual([])
  })

  it('maps rbcodes colour names and cycles through them', () => {
    expect(cssColor('sky_blue')).toBe(ABSORBER_COLORS['sky_blue'])
    expect(cssColor('#123456')).toBe('#123456')
    expect(nextColor(0)).toBe('sky_blue')
    expect(nextColor(1)).toBe('orange')
    expect(nextColor(Object.keys(ABSORBER_COLORS).length)).toBe('sky_blue')
    expect(LINE_LIST_OPTIONS).toContain('atom')
    expect(SHORTCUTS.map((s) => s.id)).toContain('quickid')
  })

  it('identifies the nearest transition at a redshift', () => {
    const lines = [
      { wrest: 2796.354, name: 'MgII 2796', kind: 'absorption' as const },
      { wrest: 2803.5315, name: 'MgII 2803', kind: 'absorption' as const },
    ]
    const match = identifyAt(lines, 6671.5, MGII_Z)
    expect(match?.line.name).toBe('MgII 2796')
    expect(match?.waveObs).toBeCloseTo(2796.354 * (1 + MGII_Z), 3)
    expect(Math.abs(match?.deltaKms ?? 0)).toBeLessThan(60)
    expect(identifyAt(lines, 6690, MGII_Z)?.line.name).toBe('MgII 2803')
    expect(identifyAt([], 6671, MGII_Z)).toBeNull()
  })

  it('turns a quick-identification key into a redshift', () => {
    expect(quickIdRedshift('M', 6670.7)?.species).toBe('MgII')
    expect(quickIdRedshift('M', 6670.7)?.z).toBeCloseTo(MGII_Z, 4)
    expect(quickIdRedshift('1', 4000)?.species).toBe('HI Lya')
    expect(quickIdRedshift('q', 4000)).toBeNull()
    expect(quickIdRedshift('M', Number.NaN)).toBeNull()
  })

  it('slices velocity panels around the transitions in range', () => {
    const series = panelsFromCollection(COLLECTION).panels[0]!
    const lines = [
      { wrest: 2796.354, name: 'MgII 2796', kind: 'absorption' as const },
      { wrest: 2803.5315, name: 'MgII 2803', kind: 'absorption' as const },
      { wrest: 1215.6701, name: 'HI 1215', kind: 'absorption' as const },
    ]
    const panels = velocityPanels(series, lines, MGII_Z, -4000, 4000)
    // HI 1215 lands at 2900 A, outside the 4000-8000 A spectrum.
    expect(panels.map((p) => p.name)).toEqual(['MgII 2796', 'MgII 2803'])
    expect(Math.min(...(panels[0]?.velocity ?? []))).toBeGreaterThanOrEqual(-4000)
    expect(velocityPanels(series, lines, MGII_Z, -4000, 4000, 1)).toHaveLength(1)
    expect(velocityPanels({ ...series, range: null }, lines, MGII_Z, -100, 100)).toEqual([])
  })

  it('formats redshifts and wavelengths the way rb_multispec does', () => {
    expect(formatZabs(1.3855)).toBe('1.385500')
    expect(formatZabs(Number.NaN)).toBe('-')
    expect(formatWave(6670.70249)).toBe('6670.7025')
    expect(formatWave(Number.NaN)).toBe('-')
  })
})

// --- quick fits ---------------------------------------------------------------------------------

function gaussianSpectrum(direction = 1, sigma = 2, centre = 6600) {
  const wave: number[] = []
  const flux: number[] = []
  for (let w = 6500; w < 6700; w += 0.5) {
    wave.push(w)
    flux.push(
      10 + 0.05 * (w - 6500) + direction * 30 * Math.exp(-0.5 * ((w - centre) / sigma) ** 2),
    )
  }
  return { wave, flux }
}

function anchorAt(series: { wave: number[]; flux: number[] }, x: number) {
  let best = 0
  let delta = Infinity
  series.wave.forEach((w, i) => {
    if (Math.abs(w - x) < delta) {
      delta = Math.abs(w - x)
      best = i
    }
  })
  return { x, y: series.flux[best] ?? 0 }
}

describe('browser quick fits (LineFitter port)', () => {
  it('recovers the centroid and width of an emission line', () => {
    const series = gaussianSpectrum()
    const fit = fitGaussian(series, anchorAt(series, 6580), anchorAt(series, 6620))
    expect(fit.kind).toBe('gaussian')
    expect(fit.direction).toBe(1)
    expect(fit.centroid).toBeCloseTo(6600, 2)
    expect(fit.sigmaAng).toBeCloseTo(2, 2)
    expect(fit.fwhmAng).toBeCloseTo(2.3548 * 2, 2)
    expect(fit.fwhmKms).toBeCloseTo((fit.fwhmAng / fit.centroid) * 2.998e5, 6)
    expect(fit.amplitude).toBeCloseTo(30, 1)
    expect(fit.asymmetric).toBe(false)
    expect(fit.nPixels).toBe(81)
    expect(fit.model.x).toHaveLength(300)
  })

  it('handles absorption, reversed anchors and truncated profiles', () => {
    const series = gaussianSpectrum(-1)
    const fit = fitGaussian(series, anchorAt(series, 6620), anchorAt(series, 6580))
    expect(fit.direction).toBe(-1)
    expect(fit.amplitude).toBeCloseTo(-30, 1)
    expect(fit.window).toEqual([6580, 6620])
    const truncated = fitGaussian(series, anchorAt(series, 6596), anchorAt(series, 6620))
    expect(truncated.asymmetric).toBe(true)
  })

  it('centres of mass agree with the Gaussian centroid and clip the wrong-sign wing', () => {
    const series = gaussianSpectrum()
    const fit = fitCom(series, anchorAt(series, 6580), anchorAt(series, 6620))
    expect(fit.kind).toBe('com')
    expect(fit.centroid).toBeCloseTo(6600, 1)
    expect(fit.sigmaAng).toBeGreaterThan(2)
    expect(fit.model.x).toHaveLength(0)
  })

  it('refuses windows without enough pixels or signal', () => {
    const series = gaussianSpectrum()
    expect(() => fitGaussian(series, { x: 6600, y: 10 }, { x: 6601, y: 10 })).toThrow(/at least 5/)
    expect(() => fitCom(series, { x: 6600, y: 10 }, { x: 6600.6, y: 10 })).toThrow(/at least 3/)
    const flat = { wave: series.wave, flux: series.wave.map(() => 0) }
    expect(() => fitCom(flat, { x: 6520, y: 0 }, { x: 6560, y: 0 })).toThrow(/no signal/)
  })
})

// --- the editor ---------------------------------------------------------------------------------

const VIEW_SPEC: NodeSpec = {
  id: 'rbcodes.multispec.view',
  name: 'Multi-Spectrum Viewer',
  category: 'rbcodes/Multispec',
  version: '1.0.0',
  cost: 'cheap',
  inputs: [
    {
      name: 'spectra',
      type: 'astro.SpectrumCollection',
      description: '',
      required: true,
      lazy: false,
    },
    { name: 'absorber_seed', type: 'astro.Table', description: '', required: false, lazy: false },
    { name: 'line_seed', type: 'astro.Table', description: '', required: false, lazy: false },
    { name: 'extra_lines', type: 'astro.LineList', description: '', required: false, lazy: false },
    {
      name: 'extra_lines_2',
      type: 'astro.LineList',
      description: '',
      required: false,
      lazy: false,
    },
    { name: 'redshift', type: 'astro.Redshift', description: '', required: false, lazy: false },
  ],
  params: [],
  outputs: [
    { name: 'absorbers', type: 'astro.Table', description: '', required: true, lazy: false },
    { name: 'identified_lines', type: 'astro.Table', description: '', required: true, lazy: false },
    { name: 'view', type: 'rbcodes.MultispecView', description: '', required: true, lazy: false },
  ],
  description: '',
  param_docs: {},
  icon: null,
  preview: null,
  editor: 'multispec-viewer',
  pack: 'rbcodes',
  module: '',
  deprecated: false,
  experimental: false,
  expand: false,
  fingerprint: false,
  is_async: false,
}

function sentOf(socket: FakeSocket, type: string): Record<string, unknown>[] {
  return socket.sent
    .map((s) => JSON.parse(s) as Record<string, unknown>)
    .filter((m) => m['type'] === type)
}

describe('MultispecViewerEditor', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('WebSocket', FakeSocket as unknown as typeof WebSocket)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function summary(
    nodeId: string,
    typeId: string,
    payload: Record<string, unknown>,
    tag = 'editor',
    port = 'out',
  ) {
    return {
      type: 'node.output.summary',
      workflow_id: 'wf-ms',
      node_id: nodeId,
      port,
      type_id: typeId,
      tag,
      ts: 1,
      summary: payload,
    } as never
  }

  async function setup(params: Record<string, unknown> = {}) {
    const workflow = useWorkflowStore()
    workflow.load({
      ...mathChain(),
      id: 'wf-ms',
      name: 'wf-ms',
      nodes: {
        stack: { type: 'core.list.collect', params: {}, disabled: false, notes: '' },
        seed: {
          type: 'rbcodes.multispec.absorber_catalog',
          params: {},
          disabled: false,
          notes: '',
        },
        rank: { type: 'rbcodes.zfind.rank', params: {}, disabled: false, notes: '' },
        viewer: {
          type: 'rbcodes.multispec.view',
          params: { z: 0, linelist: 'LLS', catalog: [], identifications: [], ...params },
          disabled: false,
          notes: '',
        },
      },
      edges: {
        e1: { from: ['stack', 'out'], to: ['viewer', 'spectra'] },
        e2: { from: ['seed', 'out'], to: ['viewer', 'absorber_seed'] },
        e3: { from: ['rank', 'redshift'], to: ['viewer', 'redshift'] },
      },
    })
    const session = useSessionStore()
    session.connect(
      () =>
        new WsClient({
          url: () => 'ws://test',
          factory: () => new FakeSocket() as unknown as WebSocket,
          pingIntervalMs: 0,
        }),
    )
    const socket = FakeSocket.last!
    socket.onopen?.()
    const execution = useExecutionStore()
    execution.applyMessage(summary('stack', 'astro.SpectrumCollection', COLLECTION))
    execution.applyMessage(
      summary('seed', 'astro.Table', {
        type: 'astro.Table',
        n_rows: 1,
        columns: ['Zabs', 'LineList', 'Color', 'Visible'],
        head: { Zabs: [0.5], LineList: ['DLA'], Color: ['orange'], Visible: [true] },
      }),
    )
    execution.applyMessage(
      summary(
        'rank',
        'astro.Redshift',
        { type: 'astro.Redshift', data: { z: MGII_Z } },
        'editor',
        'redshift',
      ),
    )
    execution.applyMessage(
      summary('type:rbcodes.lines.line_list', 'astro.LineList', LLS_LINES, 'editor-list:LLS'),
    )
    const wrapper = mount(MultispecViewerEditor, {
      props: { nodeId: 'viewer', spec: VIEW_SPEC },
      global: { plugins: [i18n] },
      attachTo: document.body,
    })
    await flushPromises()
    return { wrapper, workflow, socket, execution }
  }

  it('stacks the panels, seeds the catalogue and requests the line list', async () => {
    const { wrapper, socket } = await setup()
    const panels = wrapper.findAll('[data-testid="multispec-panel"]')
    expect(panels).toHaveLength(3)
    expect(panels[0]?.attributes('data-label')).toBe('sdss1.fits')
    expect(wrapper.attributes('data-panels')).toBe('3')
    // The collection preview asked for every panel.
    const previews = sentOf(socket, 'preview.request').filter(
      (m) => (m['viewport'] as Record<string, unknown>)['max_items'] !== undefined,
    )
    expect(previews[0]).toMatchObject({ node_id: 'stack', viewport: { max_items: 32 } })
    // The default LLS list was fetched through preview.compute under its own tag.
    expect(sentOf(socket, 'preview.compute')).toContainEqual(
      expect.objectContaining({
        node_type: 'rbcodes.lines.line_list',
        params: { name: 'LLS' },
        tag: 'editor-list:LLS',
      }),
    )
    // The absorber seed became the editor's catalogue.
    expect(wrapper.find('[data-testid="multispec-absorbers"]').attributes('data-count')).toBe('1')
    expect(wrapper.find('[data-testid="multispec-lines"]').exists()).toBe(false)
  })

  it('snaps the redshift from the connected Redshift and overlays the list', async () => {
    const { wrapper } = await setup()
    const snap = wrapper.find('[data-testid="multispec-snap"]')
    expect(snap.exists()).toBe(true)
    await snap.trigger('click')
    await nextTick()
    expect((wrapper.find('[data-testid="multispec-z"]').element as HTMLInputElement).value).toBe(
      String(MGII_Z),
    )
    // MgII 2796/2803 land at 6670/6687 A inside 4000-8000; HI 1215 at 2900 A does not.
    // The DLA seed system is visible too but its list has not been fetched, so it adds nothing.
    const markers = Number(
      wrapper.find('[data-testid="multispec-panel"]').attributes('data-markers'),
    )
    expect(markers).toBe(2)
  })

  it('identifies the nearest line on a click and applies both catalogues', async () => {
    const { wrapper, workflow } = await setup()
    await wrapper.find('[data-testid="multispec-snap"]').trigger('click')
    await nextTick()
    await wrapper.findAll('[data-testid="multispec-panel"]')[0]?.trigger('click')
    await nextTick()
    const lines = wrapper.find('[data-testid="multispec-lines"]')
    expect(lines.attributes('data-count')).toBe('1')
    expect(lines.text()).toContain('MgII 2796')
    expect(wrapper.find('[data-testid="multispec-status"]').text()).toContain('MgII 2796')

    await wrapper.find('[data-testid="multispec-add-absorber"]').trigger('click')
    await nextTick()
    expect(wrapper.find('[data-testid="multispec-absorbers"]').attributes('data-count')).toBe('2')

    await wrapper.find('[data-testid="editor-apply"]').trigger('click')
    const applied = workflow.nodes['viewer']?.params as Record<string, unknown>
    expect(applied['z']).toBe(MGII_Z)
    expect(applied['linelist']).toBe('LLS')
    expect((applied['identifications'] as unknown[])[0]).toMatchObject({
      name: 'MgII 2796',
      zabs: MGII_Z,
      spectrum: 'sdss1.fits',
    })
    expect(applied['catalog']).toHaveLength(2)
    expect((applied['display'] as Record<string, unknown>)['smooth_pixels']).toBe(1)
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('runs a quick fit from a dragged range and can identify at its centroid', async () => {
    const { wrapper } = await setup()
    await wrapper.find('[data-testid="multispec-snap"]').trigger('click')
    await wrapper.findAll('[data-testid="multispec-panel"]')[0]?.trigger('dblclick')
    await nextTick()
    const fit = wrapper.find('[data-testid="multispec-fit"]')
    expect(fit.exists()).toBe(true)
    const centroid = Number(fit.find('[data-centroid]').attributes('data-centroid'))
    expect(centroid).toBeGreaterThan(6600)
    expect(centroid).toBeLessThan(6740)
    await fit.find('[data-testid="multispec-fit-identify"]').trigger('click')
    await nextTick()
    expect(wrapper.find('[data-testid="multispec-lines"]').attributes('data-count')).toBe('1')
  })

  it('answers the rb_multispec keyboard shortcuts', async () => {
    const { wrapper } = await setup()
    const root = wrapper.find('[data-testid="editor-multispec"]')
    // Hover a panel so the cursor position is known.
    await wrapper.findAll('[data-testid="multispec-panel"]')[1]?.trigger('mouseenter')

    await root.trigger('keydown', { key: 'M' })
    await nextTick()
    expect(wrapper.find('[data-testid="multispec-status"]').text()).toContain('MgII')
    expect(
      Number((wrapper.find('[data-testid="multispec-z"]').element as HTMLInputElement).value),
    ).toBeCloseTo(MGII_Z, 3)

    await root.trigger('keydown', { key: 'A' })
    await nextTick()
    expect(wrapper.find('[data-testid="multispec-absorbers"]').attributes('data-count')).toBe('2')

    await root.trigger('keydown', { key: 'Z' })
    await nextTick()
    expect((wrapper.find('[data-testid="multispec-z"]').element as HTMLInputElement).value).toBe(
      '0',
    )

    await root.trigger('keydown', { key: 'S' })
    await nextTick()
    expect(wrapper.find('[data-testid="multispec-status"]').text()).toMatch(/3 px/)

    await root.trigger('keydown', { key: 'v' })
    await nextTick()
    expect(wrapper.find('[data-testid="multispec-vstack-panel"]').exists()).toBe(true)

    await root.trigger('keydown', { key: '?' })
    await nextTick()
    expect(wrapper.find('[data-testid="multispec-shortcuts"]').exists()).toBe(true)

    // g twice around a feature runs the Gaussian fit at the hovered position.
    await root.trigger('keydown', { key: 'g' })
    expect(wrapper.find('[data-testid="multispec-status"]').text()).toContain('6670')
  })

  it('keeps the parameter catalogues when the node already has edits', async () => {
    const { wrapper } = await setup({
      z: MGII_Z,
      catalog: [{ zabs: MGII_Z, linelist: 'LLS', color: 'cyan', visible: false, label: '' }],
      identifications: [
        { name: 'MgII 2803', wave_obs: 6687.8, zabs: MGII_Z, wave_rest: 2803.5, spectrum: 'a' },
      ],
    })
    expect(wrapper.find('[data-testid="multispec-absorbers"]').attributes('data-count')).toBe('1')
    expect(wrapper.find('[data-testid="multispec-lines"]').text()).toContain('MgII 2803')
    // The invisible system contributes no ticks; only the overlay list does.
    await wrapper.find('[data-testid="multispec-absorber-remove"]').trigger('click')
    await nextTick()
    expect(wrapper.find('[data-testid="multispec-absorbers"]').exists()).toBe(false)
    await wrapper.find('[data-testid="multispec-line-remove"]').trigger('click')
    await nextTick()
    expect(wrapper.find('[data-testid="multispec-lines"]').exists()).toBe(false)
  })
})
