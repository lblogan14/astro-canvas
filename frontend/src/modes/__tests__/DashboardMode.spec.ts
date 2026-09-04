import { describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'

import { i18n } from '@/i18n'
import DashboardMode from '@/modes/DashboardMode.vue'
import { readDashboardLayout } from '@/modes/layouts'
import { upstreamNodes } from '@/modes/linked'
import { idleExecution, useExecutionStore } from '@/stores/execution'
import { useLinkedStore } from '@/stores/linked'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useWorkflowStore } from '@/stores/workflow'
import { SPECS, TYPES, mathChain } from '@/stores/__tests__/fixtures'
import type { NodeSpec, WorkflowDoc } from '@/api/types'

type AnyFn = (...args: unknown[]) => unknown

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return {
    ...original,
    api: {
      putWorkflow: vi.fn<AnyFn>(),
      startRun: vi.fn<AnyFn>(),
      exportOutputs: vi.fn<AnyFn>(),
    },
  }
})

/** A table node for this test only: one spectrum in, one table out, so the two views link. */
const TABLE_SPEC = {
  ...(SPECS.find((entry) => entry.id === 'core.spec.crop') as NodeSpec),
  id: 'test.table.make',
  outputs: [{ name: 'out', type: 'astro.Table', description: '', lazy: false, required: true }],
  params: [],
}

/** `src` (spectrum) feeds both `crop` (curve view) and `table` (table view). */
function document(): WorkflowDoc {
  const base = mathChain()
  return {
    ...base,
    nodes: {
      src: { ...base.nodes!['c']!, type: 'test.spec.make', params: { n: 4 } },
      crop: { ...base.nodes!['sq']!, type: 'core.spec.crop', params: { lo: 1200, hi: 1300 } },
      table: { ...base.nodes!['sum']!, type: 'test.table.make', params: {}, linked: [] },
    },
    edges: {
      e1: { from: ['src', 'out'], to: ['crop', 'spec'] },
      e2: { from: ['src', 'out'], to: ['table', 'spec'] },
    },
  }
}

/** A spectrum-like curve on `crop` and a table on `table`: both fed by `src`, so they link. */
const CURVE = {
  typeId: 'astro.Spectrum1D',
  summary: { wave: [1200, 1215.7, 1250, 1300], flux: [1, 2, 3, 4], range: [1200, 1300], n: 4 },
  ts: 1,
}
const TABLE = {
  typeId: 'astro.Table',
  summary: {
    columns: ['wave', 'flux'],
    head: { wave: [1200, 1215.7, 1250, 1300], flux: [1, 2, 3, 4] },
    n_rows: 4,
  },
  ts: 1,
}

function setup() {
  setActivePinia(createPinia())
  const schema = useNodesSchemaStore()
  schema.specs = [...SPECS, TABLE_SPEC]
  schema.types = TYPES
  schema.status = 'ready'
  const workflow = useWorkflowStore()
  workflow.autosaveEnabled = false
  workflow.load(document())
  const curve = workflow.pinView('crop', 'out', { kind: 'spectrum-thumb' })
  const table = workflow.pinView('table', 'out', { kind: 'table-head' })
  workflow.promoteParam('src', 'n', { label: 'Points', group: 'Load' })

  const execution = useExecutionStore()
  execution.nodes['crop'] = { ...idleExecution(), state: 'done', summaries: { out: CURVE } }
  execution.nodes['table'] = { ...idleExecution(), state: 'done', summaries: { out: TABLE } }
  return { workflow, execution, curve, table, links: useLinkedStore() }
}

function mountMode() {
  // uPlot needs a real canvas; the tile's selection layer sits outside the renderer anyway.
  return mount(DashboardMode, {
    global: {
      plugins: [i18n],
      stubs: { SpectrumThumb: { template: '<div data-preview="spectrum-thumb" />' } },
    },
  })
}

describe('Dashboard mode', () => {
  it('lays out the views and promoted params as grid tiles', () => {
    const { curve, table } = setup()
    const dash = mountMode()
    expect(dash.find(`[data-testid="dashboard-tile-view:${curve}"]`).exists()).toBe(true)
    expect(dash.find(`[data-testid="dashboard-tile-view:${table}"]`).exists()).toBe(true)
    expect(dash.find('[data-testid="dashboard-param-src.n"]').exists()).toBe(true)
    // The grid is locked until Edit is pressed.
    expect(dash.find('[data-testid="dashboard-save-layout"]').exists()).toBe(false)
  })

  it('drags a range in the spectrum and highlights the linked table rows', async () => {
    const { curve, table, links } = setup()
    const dash = mountMode()
    const element = dash.get(`[data-testid="view-select-${curve}"]`).element as HTMLElement
    element.setPointerCapture = () => {}
    element.getBoundingClientRect = () =>
      ({ left: 0, width: 100, top: 0, height: 50, right: 100, bottom: 50 }) as DOMRect
    // jsdom has no PointerEvent; a MouseEvent carries the coordinates the handler reads.
    const at = (type: string, clientX: number) =>
      element.dispatchEvent(new MouseEvent(type, { clientX, bubbles: true }))

    at('pointerdown', 10)
    at('pointermove', 60)
    at('pointerup', 60)
    await dash.vm.$nextTick()

    // 10 % to 60 % of 1200–1300 Å.
    expect(links.selection).toEqual({ kind: 'range', axis: 'wave', lo: 1210, hi: 1260 })
    expect(links.isSource(curve)).toBe(true)

    const tableTile = dash.get(`[data-testid="view-tile-${table}"]`)
    expect(tableTile.attributes('data-linked')).toBe('true')
    expect(tableTile.attributes('data-selected-rows')).toBe('2')
    expect(tableTile.findAll('tbody tr[data-linked="true"]')).toHaveLength(2)
    expect(dash.get('[data-testid="dashboard-selection"]').text()).toContain('1210')
  })

  it('shows the band on the source curve and clears the selection', async () => {
    const { curve, links } = setup()
    const dash = mountMode()
    links.setRange('other', upstreamNodes('crop', document().edges!), 'wave', 1220, 1240)
    await dash.vm.$nextTick()
    expect(dash.find(`[data-testid="view-band-${curve}"]`).exists()).toBe(true)

    await dash.get('[data-testid="dashboard-clear-selection"]').trigger('click')
    expect(links.selection).toBeNull()
    await dash.vm.$nextTick()
    expect(dash.find(`[data-testid="view-band-${curve}"]`).exists()).toBe(false)
  })

  it('selects rows in a table and marks them on the linked curve', async () => {
    const { curve, table, links } = setup()
    const dash = mountMode()
    const row = dash.get(`[data-testid="view-tile-${table}"] tbody tr[data-row="1"]`)
    await row.trigger('click')

    expect(links.selection).toEqual({
      kind: 'rows',
      rows: [1],
      values: [1215.7],
      column: 'wave',
    })
    await dash.vm.$nextTick()
    expect(dash.find(`[data-testid="view-band-${curve}"]`).exists()).toBe(true)
  })

  it('unlocks, removes a tile and saves the layout', async () => {
    const { workflow, curve } = setup()
    const dash = mountMode()
    await dash.get('[data-testid="dashboard-edit"]').trigger('click')
    await dash.get(`[data-testid="dashboard-remove-view:${curve}"]`).trigger('click')
    await dash.get('[data-testid="dashboard-save-layout"]').trigger('click')

    const layout = readDashboardLayout(workflow.layouts)
    expect(layout?.items.map((tile) => tile.ref)).toEqual([
      'promoted:src.n',
      `view:${workflow.views[1]!.id}`,
    ])
    expect(layout?.cols).toBe(12)
    workflow.undo()
    expect(workflow.layouts['dashboard']).toBeUndefined()
  })

  it('reports tiles whose target is gone', () => {
    const { workflow } = setup()
    workflow.setLayout('dashboard', {
      cols: 12,
      items: [{ ref: 'view:ghost', x: 0, y: 0, w: 6, h: 4 }],
    })
    const dash = mountMode()
    expect(dash.get('[data-testid="dashboard-missing"]').text()).toContain('view:ghost')
  })
})
