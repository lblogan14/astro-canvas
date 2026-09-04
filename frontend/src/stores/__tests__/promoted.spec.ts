import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import {
  defaultAppLayout,
  defaultDashboardLayout,
  defaultWizardLayout,
  dropRefFromLayouts,
  itemText,
  parseItem,
  readAppLayout,
  readDashboardLayout,
  readWizardLayout,
  resolveItem,
  resolveItems,
  viewRenderer,
} from '@/modes/layouts'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useWorkflowStore } from '@/stores/workflow'
import { SPECS, TYPES, mathChain } from './fixtures'

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return {
    ...original,
    api: {
      putWorkflow: vi.fn<typeof original.api.putWorkflow>(),
      createWorkflow: vi.fn<typeof original.api.createWorkflow>(),
    },
  }
})

function setup() {
  setActivePinia(createPinia())
  const schema = useNodesSchemaStore()
  schema.specs = SPECS
  schema.types = TYPES
  schema.status = 'ready'
  const workflow = useWorkflowStore()
  workflow.autosaveEnabled = false
  workflow.load(mathChain())
  return workflow
}

describe('layout item refs', () => {
  it('parses both the string and object forms and rejects the rest', () => {
    expect(parseItem('promoted:sq.x')).toEqual({ kind: 'promoted', ref: 'sq.x' })
    expect(parseItem('view:v1')).toEqual({ kind: 'view', ref: 'v1' })
    expect(parseItem({ promoted: 'sq.x' })).toEqual({ kind: 'promoted', ref: 'sq.x' })
    expect(parseItem({ ref: 'view:v1' })).toEqual({ kind: 'view', ref: 'v1' })
    for (const raw of ['sq.x', 'promoted:x', 'view:', '', 7, null, { nope: 1 }]) {
      expect(parseItem(raw)).toBeNull()
    }
  })

  it('round-trips through itemText', () => {
    for (const text of ['promoted:inst/plus.y', 'view:curve']) {
      expect(itemText(parseItem(text)!)).toBe(text)
    }
  })
})

describe('workflow store: promotion', () => {
  beforeEach(() => vi.useRealTimers())

  it('promotes a param into an ordered, grouped list', () => {
    const wf = setup()
    expect(wf.isPromoted('c', 'value')).toBe(false)
    wf.promoteParam('c', 'value', { label: 'Constant', group: 'Setup' })
    wf.promoteParam('sum', 'z', { group: 'Setup' })
    wf.promoteParam('sq', 'expression', { group: 'Maths' })

    expect(wf.promotedList.map((p) => `${p.node}.${p.param}`)).toEqual([
      'c.value',
      'sum.z',
      'sq.expression',
    ])
    expect(wf.promotedList.map((p) => p.order)).toEqual([1, 2, 3])
    expect(wf.promotedGroups.map((g) => [g.title, g.entries.length])).toEqual([
      ['Setup', 2],
      ['Maths', 1],
    ])
    expect(wf.isPromoted('c', 'value')).toBe(true)
    expect(wf.promotedOf('c', 'value')?.label).toBe('Constant')
    expect(wf.isDirty).toBe(true)
  })

  it('is idempotent and toggles back off', () => {
    const wf = setup()
    wf.promoteParam('c', 'value')
    wf.promoteParam('c', 'value', { label: 'Twice' })
    expect(wf.promotedList).toHaveLength(1)
    expect(wf.promotedOf('c', 'value')?.label).toBeNull()

    expect(wf.togglePromoted('c', 'value')).toBe(false)
    expect(wf.promotedList).toHaveLength(0)
    expect(wf.togglePromoted('c', 'value', { group: 'Setup' })).toBe(true)
    expect(wf.promotedOf('c', 'value')?.group).toBe('Setup')
  })

  it('edits labels, help text and groups', () => {
    const wf = setup()
    wf.promoteParam('c', 'value')
    wf.updatePromoted('c', 'value', { label: 'Redshift', group: 'Setup', help: 'Absorber z' })
    const entry = wf.promotedOf('c', 'value')!
    expect([entry.label, entry.group]).toEqual(['Redshift', 'Setup'])
    expect((entry as Record<string, unknown>)['help']).toBe('Absorber z')
    // Unknown promoted keys survive into the saved document.
    expect((wf.doc!.promoted![0] as Record<string, unknown>)['help']).toBe('Absorber z')
  })

  it('reorders across groups and renumbers order', () => {
    const wf = setup()
    wf.promoteParam('c', 'value', { group: 'Setup' })
    wf.promoteParam('sum', 'z', { group: 'Setup' })
    wf.promoteParam('sq', 'x', { group: 'Maths' })

    wf.movePromoted('sq', 'x', 0, 'Setup')
    expect(wf.promotedList.map((p) => p.param)).toEqual(['x', 'value', 'z'])
    expect(wf.promotedList.map((p) => p.order)).toEqual([1, 2, 3])
    expect(wf.promotedGroups).toHaveLength(1)
    // Out-of-range indices clamp instead of dropping the entry.
    wf.movePromoted('sq', 'x', 99)
    expect(wf.promotedList.map((p) => p.param)).toEqual(['value', 'z', 'x'])
  })

  it('undoes promotion in one step', () => {
    const wf = setup()
    wf.promoteParam('c', 'value', { group: 'Setup' })
    wf.updatePromoted('c', 'value', { label: 'Constant' })
    wf.undo()
    expect(wf.promotedOf('c', 'value')?.label).toBeNull()
    wf.undo()
    expect(wf.promotedList).toHaveLength(0)
    wf.redo()
    expect(wf.isPromoted('c', 'value')).toBe(true)
  })
})

describe('workflow store: pinned views', () => {
  it('pins and unpins node outputs', () => {
    const wf = setup()
    expect(wf.isPinned('sum', 'out')).toBe(false)
    const id = wf.pinView('sum', 'out', { kind: 'value-chip' })
    expect(wf.isPinned('sum', 'out')).toBe(true)
    expect(wf.viewOf('sum', 'out')?.id).toBe(id)
    expect(wf.viewById(id)?.kind).toBe('value-chip')
    // Pinning twice keeps the same view id.
    expect(wf.pinView('sum', 'out')).toBe(id)

    wf.updateView(id, { label: 'Total' })
    expect((wf.viewById(id) as Record<string, unknown>)['label']).toBe('Total')
    expect(wf.togglePinned('sum', 'out')).toBe(false)
    expect(wf.views).toHaveLength(0)
    wf.undo()
    expect(wf.views).toHaveLength(1)
  })
})

describe('workflow store: layouts', () => {
  it('writes one layout section as an undoable command', () => {
    const wf = setup()
    wf.setLayout('app', { sections: [{ title: 'Setup', items: ['promoted:c.value'] }] })
    expect(readAppLayout(wf.layouts)?.sections[0]?.title).toBe('Setup')
    wf.setLayout('app', null)
    expect(wf.layouts['app']).toBeUndefined()
    wf.undo()
    expect(readAppLayout(wf.layouts)?.sections).toHaveLength(1)
  })

  it('drops layout items when their target is unpromoted or unpinned', () => {
    const wf = setup()
    wf.promoteParam('c', 'value', { group: 'Setup' })
    const view = wf.pinView('sum', 'out')
    wf.setLayout('app', {
      sections: [{ title: 'Setup', items: ['promoted:c.value', `view:${view}`] }],
    })
    wf.setLayout('dashboard', {
      cols: 12,
      items: [{ ref: 'promoted:c.value', x: 0, y: 0, w: 3, h: 2 }],
    })
    wf.setLayout('batch', { columns: [{ promoted: 'c.value', column: 'value' }], collect: [] })

    wf.unpromoteParam('c', 'value')
    expect(readAppLayout(wf.layouts)?.sections[0]?.items).toEqual([`view:${view}`])
    expect(readDashboardLayout(wf.layouts)?.items).toEqual([])
    expect(wf.layouts['batch']).toEqual({ columns: [], collect: [] })

    wf.unpinView(view)
    expect(readAppLayout(wf.layouts)?.sections[0]?.items).toEqual([])
  })

  it('leaves sections it does not understand alone', () => {
    const layouts = { custom: { rows: ['promoted:c.value'] }, app: { sections: [] } }
    expect(dropRefFromLayouts(layouts, 'promoted:c.value')).toEqual(layouts)
  })
})

describe('default layouts', () => {
  function promoted() {
    const wf = setup()
    wf.promoteParam('c', 'value', { label: 'Constant', group: 'Load' })
    wf.promoteParam('sq', 'expression', { group: 'Maths' })
    wf.promoteParam('sum', 'z', { group: 'Maths' })
    wf.pinView('sum', 'out', { kind: 'value-chip' })
    return wf
  }

  it('derives App sections from the promoted groups', () => {
    const wf = promoted()
    const layout = defaultAppLayout(wf.promotedList, wf.views)
    expect(layout.sections.map((s) => [s.title, s.items])).toEqual([
      ['Load', ['promoted:c.value']],
      ['Maths', ['promoted:sq.expression', 'promoted:sum.z']],
      ['Results', [`view:${wf.views[0]!.id}`]],
    ])
  })

  it('derives Wizard steps with the nodes each step gates on', () => {
    const wf = promoted()
    const layout = defaultWizardLayout(wf.promotedList, wf.views)
    expect(layout.steps.map((s) => [s.title, s.nodes])).toEqual([
      ['Load', ['c']],
      ['Maths', ['sq', 'sum']],
      ['Results', ['sum']],
    ])
  })

  it('derives a Dashboard grid that fits the 12 column width', () => {
    const wf = promoted()
    const layout = defaultDashboardLayout(wf.promotedList, wf.views)
    expect(layout.cols).toBe(12)
    expect(layout.items.map((t) => [t.ref, t.x, t.y, t.w, t.h])).toEqual([
      ['promoted:c.value', 0, 0, 3, 2],
      ['promoted:sq.expression', 3, 0, 3, 2],
      ['promoted:sum.z', 6, 0, 3, 2],
      [`view:${wf.views[0]!.id}`, 0, 2, 6, 5],
    ])
    for (const tile of layout.items) expect(tile.x + tile.w).toBeLessThanOrEqual(layout.cols)
  })

  it('reads a hand-written wizard section, defaults and all', () => {
    const layout = readWizardLayout({
      wizard: { steps: [{ title: 'Load', items: ['promoted:c.value', 'junk'] }, 'nope'] },
    })
    expect(layout?.steps).toEqual([
      {
        title: 'Load',
        items: ['promoted:c.value'],
        description: null,
        nodes: [],
        optional: false,
      },
    ])
    expect(readWizardLayout({})).toBeNull()
  })
})

describe('item resolution', () => {
  it('resolves promoted params against the document and its specs', () => {
    const wf = setup()
    wf.promoteParam('sum', 'z', { label: 'Offset', group: 'Maths' })
    const ctx = {
      promoted: wf.promotedList,
      views: wf.views,
      nodes: wf.rootNodes,
      specs: wf.specs,
    }
    const item = resolveItem('promoted:sum.z', ctx)
    expect(item?.kind).toBe('promoted')
    if (item?.kind !== 'promoted') throw new Error('expected a promoted item')
    expect([item.node, item.param, item.label, item.value]).toEqual(['sum', 'z', 'Offset', 1.0])
    expect(item.spec?.name).toBe('z')
    expect(item.linked).toBe(false)
    // The param's own description becomes the help text when the entry has none.
    expect(item.help).toBeNull()
  })

  it('reports items whose target is gone instead of rendering them', () => {
    const wf = setup()
    wf.promoteParam('c', 'value')
    const ctx = {
      promoted: wf.promotedList,
      views: wf.views,
      nodes: wf.rootNodes,
      specs: wf.specs,
    }
    const { resolved, missing } = resolveItems(
      ['promoted:c.value', 'promoted:ghost.value', 'view:nope', 'junk'],
      ctx,
    )
    expect(resolved.map((r) => r.key)).toEqual(['promoted:c.value'])
    expect(missing).toEqual(['promoted:ghost.value', 'view:nope', 'junk'])
  })

  it('prefers the live renderer over the document kind hint', () => {
    const view = { id: 'v', node: 'sum', port: 'out', kind: 'spectrum' }
    expect(viewRenderer(view, 'table-head')).toBe('table-head')
    expect(viewRenderer(view, null)).toBe('spectrum-thumb')
    expect(viewRenderer({ ...view, kind: 'moment-thumbs' }, null)).toBe('moment-thumbs')
    expect(viewRenderer({ ...view, kind: 'nonsense' }, null)).toBeNull()
    expect(viewRenderer({ ...view, kind: null }, null)).toBeNull()
  })
})
