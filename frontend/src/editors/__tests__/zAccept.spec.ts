import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'

import type { NodeSpec } from '@/api/types'
import { WsClient } from '@/api/ws'
import ZAcceptEditor from '@/editors/ZAcceptEditor.vue'
import {
  CURATED_LINELISTS,
  combineCandidates,
  curatedLinesFromSummary,
  curveSeries,
  defaultLinelist,
  formatScore,
  formatZ,
  lineTicks,
  nearestCandidate,
  parseZFind,
} from '@/editors/zAccept'
import { i18n } from '@/i18n'
import { useExecutionStore } from '@/stores/execution'
import { useSessionStore } from '@/stores/session'
import { mathChain } from '@/stores/__tests__/fixtures'
import { useWorkflowStore } from '@/stores/workflow'

vi.mock('@/editors/EditorPlot.vue', () => ({
  default: {
    name: 'EditorPlot',
    props: ['x', 'y', 'error', 'overlays', 'markers', 'step'],
    emits: ['click'],
    template:
      '<div data-widget="editor-plot-stub" :data-points="x ? x.length : 0" :data-markers="JSON.stringify(markers)" @click="$emit(\'click\', 0.31)" />',
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

const Z = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]

function scan(label: string, values: (number | null)[], solutions: Record<string, unknown>[]) {
  return {
    type: 'rbcodes.ZFindResult',
    statistic: 'score',
    n: 6,
    z_range: [0.0, 0.5],
    z: Z,
    curves: [{ label, values }],
    solutions,
    spectrum: {
      type: 'astro.Spectrum1D',
      n: 4,
      range: [4000, 7000],
      wave: [4000, 5000, 6000, 7000],
      flux: [1, 1.2, 0.9, 1],
      error: [0.1, null, 0.1, 0.1],
      continuum: [1, 1, 1, 1],
      frame: 'observed',
      z: null,
      v0_wrest: null,
    },
    warnings: ['No error array — using MAD-STD IVAR (sigma=0.01).'],
    linelist: 'zfind_galaxy',
  }
}

const FIRST = scan(
  'PicketFence:zfind_galaxy',
  [null, -1, -5, -74, -3, -2],
  [
    {
      z: 0.3,
      z_err: 1e-4,
      chi2_dof: -74,
      method: 'PicketFence:zfind_galaxy',
      template_type: 'Unknown',
      n_features: 12,
    },
    {
      z: 0.2,
      z_err: null,
      chi2_dof: -5,
      method: 'PicketFence:zfind_galaxy',
      template_type: 'Unknown',
      n_features: 3,
    },
  ],
)
const SECOND = {
  ...scan(
    'Template:LateTypeEmission',
    [3, 2, 1.5, 0.01, 1, 2],
    [
      {
        z: 0.31,
        z_err: 2e-3,
        chi2_dof: 0.01,
        method: 'Template:LateTypeEmission',
        template_type: 'LateTypeEmission',
        n_features: 3813,
      },
    ],
  ),
  statistic: 'chi2',
  linelist: null,
}

describe('zAccept helpers', () => {
  it('parses ZFindResult and AbsorberResult summaries', () => {
    const parsed = parseZFind(FIRST)
    expect(parsed).not.toBeNull()
    expect(parsed?.statistic).toBe('score')
    expect(parsed?.z).toEqual(Z)
    expect(parsed?.curves[0]?.values[0]).toBeNull()
    expect(parsed?.solutions).toHaveLength(2)
    expect(parsed?.solutions[0]).toMatchObject({ z: 0.3, zErr: 1e-4, score: -74, nFeatures: 12 })
    expect(parsed?.solutions[1]?.zErr).toBeNull()
    expect(parsed?.spectrum?.wave).toEqual([4000, 5000, 6000, 7000])
    expect(parsed?.spectrum?.error?.[1]).toBeNaN()
    expect(parsed?.zRange).toEqual([0, 0.5])
    expect(parsed?.warnings).toHaveLength(1)
    const absorbers = parseZFind({
      type: 'rbcodes.AbsorberResult',
      statistic: 'significance',
      z: Z,
      curves: [{ label: 'zfind_igm', values: [0, 1, 6, 1, 0, 0] }],
      candidates: [
        {
          z: 0.2,
          significance: 6.4,
          n_lines: 2,
          linelist_name: 'zfind_igm',
          lines_matched: ['a', 'b'],
        },
      ],
    })
    expect(absorbers?.statistic).toBe('significance')
    expect(absorbers?.solutions[0]).toMatchObject({
      z: 0.2,
      score: 6.4,
      nFeatures: 2,
      method: 'Absorber:zfind_igm',
    })
    expect(parseZFind(undefined)).toBeNull()
    expect(parseZFind({ wave: [1], flux: [1] })).toBeNull()
    expect(
      parseZFind({ z: Z, curves: [{ label: 'short', values: [1] }], statistic: 'bogus' }),
    ).toMatchObject({
      curves: [],
      statistic: 'chi2',
      n: 6,
    })
  })

  it('numbers candidates like the backend and finds the nearest one per source', () => {
    const candidates = combineCandidates([parseZFind(FIRST), null, parseZFind(SECOND)])
    expect(candidates.map((c) => [c.index, c.source, c.rank, c.z])).toEqual([
      [0, 0, 0, 0.3],
      [1, 0, 1, 0.2],
      [2, 2, 0, 0.31],
    ])
    expect(nearestCandidate(candidates, 0, 0.22)?.index).toBe(1)
    expect(nearestCandidate(candidates, 2, 0.0)?.index).toBe(2)
    expect(nearestCandidate(candidates, 1, 0.3)).toBeNull()
    expect(combineCandidates([null, null])).toEqual([])
  })

  it('builds curve series, line ticks and labels', () => {
    const parsed = parseZFind(FIRST)!
    const series = curveSeries(parsed, 0)
    expect(series?.label).toBe('PicketFence:zfind_galaxy')
    expect(series?.y[0]).toBeNaN()
    expect(series?.y[3]).toBe(-74)
    expect(curveSeries(parsed, 3)).toBeNull()
    const lines = curatedLinesFromSummary({
      wrest: [3727.09, 3934.78, 'x'],
      name: ['[OII] 3727', 'CaII K', 'bad'],
      kind: ['emission', 'absorption', 'emission'],
    })
    expect(lines).toEqual([
      { wrest: 3727.09, name: '[OII] 3727', kind: 'emission' },
      { wrest: 3934.78, name: 'CaII K', kind: 'absorption' },
    ])
    expect(curatedLinesFromSummary({ wrest: [1], name: ['a'] })[0]?.kind).toBe('emission')
    expect(curatedLinesFromSummary(undefined)).toEqual([])
    const ticks = lineTicks(lines, 0.3, [4000, 5000])
    expect(ticks).toHaveLength(1)
    expect(ticks[0]?.x).toBeCloseTo(3727.09 * 1.3, 6)
    expect(lineTicks(lines, 0.3, null)).toHaveLength(2)
    expect(formatZ(0.0056686, 6.66e-5)).toBe('0.005669 ± 0.000067')
    expect(formatZ(0.31, null)).toBe('0.31000')
    expect(formatZ(1.5, 0.2)).toBe('1.50 ± 0.20')
    expect(formatScore(-74.0948)).toBe('-74.095')
    expect(formatScore(0.0021)).toBe('2.10e-3')
    expect(formatScore(123456)).toBe('1.23e+5')
    expect(formatScore(150.25)).toBe('150.3')
    expect(formatScore(Number.NaN)).toBe('–')
    expect(defaultLinelist('zfind_qso')).toBe('zfind_qso')
    expect(defaultLinelist('custom')).toBe('zfind_galaxy')
    expect(defaultLinelist(null)).toBe('zfind_galaxy')
    expect(CURATED_LINELISTS).toContain('zfind_igm')
  })
})

const RANK_SPEC: NodeSpec = {
  id: 'rbcodes.zfind.rank',
  name: 'Rank and Accept',
  category: 'rbcodes/Redshift',
  version: '1.0.0',
  cost: 'cheap',
  inputs: [
    { name: 'results', type: 'rbcodes.ZFindResult', description: '', required: true, lazy: false },
    {
      name: 'results_2',
      type: 'rbcodes.ZFindResult',
      description: '',
      required: false,
      lazy: false,
    },
    {
      name: 'results_3',
      type: 'rbcodes.ZFindResult',
      description: '',
      required: false,
      lazy: false,
    },
    {
      name: 'results_4',
      type: 'rbcodes.ZFindResult',
      description: '',
      required: false,
      lazy: false,
    },
  ],
  params: [],
  outputs: [
    { name: 'redshift', type: 'astro.Redshift', description: '', required: true, lazy: false },
    {
      name: 'candidates',
      type: 'rbcodes.ZCandidates',
      description: '',
      required: true,
      lazy: false,
    },
  ],
  description: '',
  param_docs: {},
  icon: null,
  preview: null,
  editor: 'z-accept',
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

describe('ZAcceptEditor', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('WebSocket', FakeSocket as unknown as typeof WebSocket)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function summary(nodeId: string, typeId: string, payload: Record<string, unknown>) {
    return {
      type: 'node.output.summary',
      workflow_id: 'wf-z',
      node_id: nodeId,
      port: 'out',
      type_id: typeId,
      tag: 'editor',
      ts: 1,
      summary: payload,
    } as never
  }

  async function setup() {
    const workflow = useWorkflowStore()
    workflow.load({
      ...mathChain(),
      id: 'wf-z',
      name: 'wf-z',
      nodes: {
        pf: { type: 'rbcodes.zfind.picket_fence_search', params: {}, disabled: false, notes: '' },
        tpl: { type: 'rbcodes.zfind.template_search', params: {}, disabled: false, notes: '' },
        rank: {
          type: 'rbcodes.zfind.rank',
          params: { accepted: null },
          disabled: false,
          notes: '',
        },
      },
      edges: {
        e1: { from: ['pf', 'out'], to: ['rank', 'results'] },
        e2: { from: ['tpl', 'out'], to: ['rank', 'results_3'] },
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
    // Tagged editor previews of both scans and the curated line list arrive.
    execution.applyMessage(summary('pf', 'rbcodes.ZFindResult', FIRST))
    execution.applyMessage(summary('tpl', 'rbcodes.ZFindResult', SECOND))
    execution.applyMessage(
      summary('type:rbcodes.zfind.curated_linelist', 'astro.LineList', {
        type: 'astro.LineList',
        n: 2,
        wrest: [3727.09, 5008.24],
        name: ['[OII] 3727', '[OIII] 5007'],
        fval: [2, 3],
        kind: ['emission', 'emission'],
      }),
    )
    const wrapper = mount(ZAcceptEditor, {
      props: { nodeId: 'rank', spec: RANK_SPEC },
      global: { plugins: [i18n] },
    })
    await flushPromises()
    return { wrapper, workflow, socket }
  }

  it('lists the combined candidates, overlays lines at the selected z and applies the index', async () => {
    const { wrapper, workflow, socket } = await setup()
    const rows = wrapper.findAll('[data-testid="zaccept-candidate"]')
    expect(rows).toHaveLength(3)
    expect(rows.map((r) => r.attributes('data-index'))).toEqual(['0', '1', '2'])
    expect(rows[0]?.attributes('aria-selected')).toBe('true')
    // The first scan's line list preset was requested through preview.compute.
    const computes = sentOf(socket, 'preview.compute')
    expect(computes.length).toBeGreaterThan(0)
    expect(computes[0]).toMatchObject({
      node_type: 'rbcodes.zfind.curated_linelist',
      params: { name: 'zfind_galaxy' },
      tag: 'editor',
    })
    // Lines at z = 0.3 within the 4000-7000 A spectrum: [OII] at 4845 and [OIII] at 6511.
    expect(wrapper.find('[data-testid="zaccept-spectrum"]').attributes('data-lines')).toBe('2')
    expect(wrapper.find('[data-testid="editor-apply"]').attributes('disabled')).toBeDefined()
    // Pick the template candidate (source 2): the curve switches to that scan.
    await rows[2]?.trigger('click')
    await nextTick()
    expect(wrapper.find('[data-testid="zaccept-curve"]').attributes('data-source')).toBe('2')
    expect(wrapper.find('[data-testid="zaccept-selected"]').attributes('data-index')).toBe('2')
    expect(wrapper.find('[data-testid="zaccept-selected"]').text()).toContain('χ²/dof')
    expect(wrapper.find('[data-testid="editor-apply"]').attributes('disabled')).toBeUndefined()
    // Switching the overlay list issues a new compute request.
    const select = wrapper.find('[data-testid="zaccept-linelist"]')
    await select.setValue('zfind_qso')
    expect(sentOf(socket, 'preview.compute').at(-1)).toMatchObject({
      params: { name: 'zfind_qso' },
    })
    await wrapper.find('[data-testid="editor-apply"]').trigger('click')
    expect(workflow.nodes['rank']?.params?.['accepted']).toBe(2)
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('selects the nearest candidate of the shown scan when the curve is clicked', async () => {
    const { wrapper } = await setup()
    // The stub emits click at z = 0.31 on the active (first) scan: nearest is #0 (z = 0.3).
    await wrapper
      .find('[data-testid="zaccept-curve"] [data-widget="editor-plot-stub"]')
      .trigger('click')
    expect(wrapper.find('[data-testid="zaccept-selected"]').attributes('data-index')).toBe('0')
    // Show the template scan, then the same click lands on #2 (z = 0.31).
    await wrapper.find('[data-testid="zaccept-source"][data-source="2"]').trigger('click')
    await wrapper
      .find('[data-testid="zaccept-curve"] [data-widget="editor-plot-stub"]')
      .trigger('click')
    expect(wrapper.find('[data-testid="zaccept-selected"]').attributes('data-index')).toBe('2')
    const markers = JSON.parse(
      wrapper
        .find('[data-testid="zaccept-curve"] [data-widget="editor-plot-stub"]')
        .attributes('data-markers') ?? '[]',
    ) as { label: string; color: string }[]
    expect(markers.map((m) => m.label)).toEqual(['#2'])
    expect(markers[0]?.color).toBe('#F59E0B')
  })
})
