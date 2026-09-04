import { describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'

import { i18n } from '@/i18n'
import InspectorPanel from '@/app/inspector/InspectorPanel.vue'
import ParametersPanel from '@/app/params/ParametersPanel.vue'
import { idleExecution, useExecutionStore } from '@/stores/execution'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useSelectionStore } from '@/stores/selection'
import { useWorkflowStore } from '@/stores/workflow'
import { SPECS, TYPES, mathChain } from '@/stores/__tests__/fixtures'

type AnyFn = (...args: unknown[]) => unknown

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return { ...original, api: { putWorkflow: vi.fn<AnyFn>() } }
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
  const selection = useSelectionStore()
  selection.selectNode('sum')
  return { workflow, selection }
}

function mountPanel(component: typeof InspectorPanel | typeof ParametersPanel) {
  return mount(component, { global: { plugins: [i18n] } })
}

describe('inspector promotion star', () => {
  it('promotes the selected node param with the spec label', async () => {
    const { workflow } = setup()
    const panel = mountPanel(InspectorPanel)
    const star = panel.get('[data-testid="promote-z"]')
    expect(star.attributes('aria-pressed')).toBe('false')

    await star.trigger('click')
    expect(workflow.isPromoted('sum', 'z')).toBe(true)
    expect(workflow.promotedOf('sum', 'z')?.label).toBe('Z')
    expect(panel.get('[data-testid="promote-z"]').attributes('aria-pressed')).toBe('true')

    await panel.get('[data-testid="promote-z"]').trigger('click')
    expect(workflow.isPromoted('sum', 'z')).toBe(false)
  })

  it('promotes into the open subgraph body, not the document', async () => {
    const { workflow, selection } = setup()
    const instance = workflow.collapseToSubgraph(['sq', 'sum'], 'Measure')
    expect(instance).not.toBeNull()
    const subgraph = Object.keys(workflow.subgraphs)[0]!
    expect(workflow.enterSubgraph(instance!)).toBe(true)
    selection.selectNode('sum')

    const panel = mountPanel(InspectorPanel)
    await panel.get('[data-testid="promote-z"]').trigger('click')
    expect(workflow.promotedList).toHaveLength(0)
    expect(workflow.subgraphs[subgraph]?.promoted).toEqual([
      { node: 'sum', param: 'z', label: null, group: null, order: 0 },
    ])
  })
})

describe('parameters panel', () => {
  it('lists promoted params by group and reorders them', async () => {
    const { workflow } = setup()
    workflow.promoteParam('c', 'value', { label: 'Constant', group: 'Load' })
    workflow.promoteParam('sum', 'z', { group: 'Maths' })
    const panel = mountPanel(ParametersPanel)

    expect(panel.get('[data-testid="params-group-Load"]').text()).toBe('Load')
    expect(panel.get('[data-testid="param-item-c.value"]').text()).toContain('Constant')

    await panel.get('[data-testid="param-down-c.value"]').trigger('click')
    expect(workflow.promotedList.map((p) => p.param)).toEqual(['z', 'value'])
    // Moving down does not change the group.
    expect(workflow.promotedOf('c', 'value')?.group).toBe('Load')
  })

  it('edits the label, group and help text in place', async () => {
    const { workflow } = setup()
    workflow.promoteParam('c', 'value')
    const panel = mountPanel(ParametersPanel)
    await panel.get('[data-testid="param-edit-c.value"]').trigger('click')

    const label = panel.get('[data-testid="param-label-c.value"]')
    await label.setValue('Redshift')
    const group = panel.get('[data-testid="param-group-c.value"]')
    await group.setValue('Setup')
    await group.trigger('change')
    const help = panel.get('[data-testid="param-help-c.value"]')
    await help.setValue('The absorber redshift')

    const entry = workflow.promotedOf('c', 'value')!
    expect([entry.label, entry.group]).toEqual(['Redshift', 'Setup'])
    expect((entry as Record<string, unknown>)['help']).toBe('The absorber redshift')
  })

  it('removes an item and reports layout errors from the server', async () => {
    const { workflow } = setup()
    workflow.promoteParam('c', 'value')
    workflow.pinView('sum', 'out', { kind: 'value-chip' })
    workflow.layoutErrors = [
      { layout: 'app', code: 'unknown_view', message: 'view:v9: no such view', ref: 'v9' },
    ]
    const panel = mountPanel(ParametersPanel)
    expect(panel.get('[data-testid="layout-errors"]').text()).toContain('no such view')

    await panel.get('[data-testid="param-remove-c.value"]').trigger('click')
    expect(workflow.promotedList).toHaveLength(0)
    const viewId = workflow.views[0]!.id
    await panel.get(`[data-testid="view-remove-${viewId}"]`).trigger('click')
    expect(workflow.views).toHaveLength(0)
  })
})

describe('preview pin', () => {
  it('pins the output with the renderer as the view kind', async () => {
    const { workflow } = setup()
    const execution = useExecutionStore()
    execution.nodes['sum'] = {
      ...idleExecution(),
      state: 'done',
      summaries: { out: { typeId: 'astro.Float', summary: { data: { value: 7 } }, ts: 1 } },
    }
    const { default: PreviewHost } = await import('@/previews/PreviewHost.vue')
    const host = mount(PreviewHost, {
      props: { nodeId: 'sum', spec: workflow.specs['core.math.expr'], exec: execution.node('sum') },
      global: { plugins: [i18n] },
    })

    const pin = host.get('[data-testid="preview-pin"]')
    expect(pin.attributes('data-pinned')).toBe('false')
    await pin.trigger('click')
    // The pinned kind is whatever the registry picked for the live summary.
    expect(workflow.viewOf('sum', 'out')?.kind).toBe('kv-tile')
    expect(host.get('[data-testid="preview-pin"]').attributes('data-pinned')).toBe('true')
  })
})
