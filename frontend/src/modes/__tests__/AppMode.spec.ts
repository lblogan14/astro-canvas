import { describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'

import { i18n } from '@/i18n'
import AppMode from '@/modes/AppMode.vue'
import { readAppLayout } from '@/modes/layouts'
import { idleExecution, useExecutionStore } from '@/stores/execution'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'
import { SPECS, TYPES, mathChain } from '@/stores/__tests__/fixtures'

type AnyFn = (...args: unknown[]) => unknown
const startRun = vi.fn<AnyFn>()
const exportOutputs = vi.fn<AnyFn>()

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return {
    ...original,
    api: {
      putWorkflow: vi.fn<AnyFn>(),
      getWorkflowStatus: vi.fn<AnyFn>(),
      startRun: (...args: unknown[]) => startRun(...args),
      exportOutputs: (...args: unknown[]) => exportOutputs(...args),
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
  workflow.promoteParam('c', 'value', { label: 'Constant', group: 'Load' })
  workflow.promoteParam('sum', 'z', { label: 'Offset', group: 'Maths' })
  const view = workflow.pinView('sum', 'out', { kind: 'kv-tile' })
  return { workflow, view, execution: useExecutionStore(), ui: useUiStore() }
}

function mountMode() {
  return mount(AppMode, { global: { plugins: [i18n] } })
}

describe('App mode', () => {
  it('renders one section per promoted group with the views beside them', () => {
    const { view } = setup()
    const app = mountMode()
    expect(app.get('[data-testid="app-section-Load"]').text()).toContain('Constant')
    expect(app.get('[data-testid="app-section-Maths"]').text()).toContain('Offset')
    expect(app.find('[data-testid="field-c.value"]').exists()).toBe(true)
    expect(app.get('[data-testid="app-views"]').text()).not.toContain('No views pinned')
    expect(app.find(`[data-testid="view-tile-${view}"]`).exists()).toBe(true)
  })

  it('writes a promoted widget straight into the node params', async () => {
    const { workflow } = setup()
    const app = mountMode()
    const input = app.get('[data-testid="field-c.value"] input')
    await input.setValue('5')
    expect(workflow.rootNodes['c']?.params?.['value']).toBe(5)
  })

  it('runs and cancels through the session', async () => {
    const { execution } = setup()
    startRun.mockResolvedValue({ run_id: 'r1' })
    const app = mountMode()
    await app.get('[data-testid="app-run"]').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(startRun).toHaveBeenCalled()

    execution.currentRunId = 'r1'
    await app.vm.$nextTick()
    expect(app.find('[data-testid="app-run"]').exists()).toBe(false)
    expect(app.find('[data-testid="app-cancel"]').exists()).toBe(true)
  })

  it('shows the auto-run indicator and node problems', async () => {
    const { execution } = setup()
    execution.autoRun = false
    execution.setIssues({ sum: [{ code: 'bad_param', message: 'z must be finite', param: 'z' }] })
    const app = mountMode()
    expect(app.get('[data-testid="app-autorun"]').attributes('data-on')).toBe('false')
    expect(app.get('[data-testid="app-problems"]').text()).toContain('z must be finite')
  })

  it('reports layout items whose target is gone', () => {
    const { workflow } = setup()
    workflow.setLayout('app', {
      sections: [{ title: 'Load', items: ['promoted:c.value', 'promoted:ghost.x'] }],
    })
    const app = mountMode()
    expect(app.get('[data-testid="app-missing"]').text()).toContain('promoted:ghost.x')
  })

  it('saves the derived layout into the document', async () => {
    const { workflow } = setup()
    expect(workflow.layouts['app']).toBeUndefined()
    const app = mountMode()
    await app.get('[data-testid="app-save-layout"]').trigger('click')

    const layout = readAppLayout(workflow.layouts)
    expect(layout?.sections.map((section) => section.title)).toEqual(['Load', 'Maths', 'Results'])
    // The save is one undoable command, like any other document edit.
    workflow.undo()
    expect(workflow.layouts['app']).toBeUndefined()
  })

  it('exports the pinned views into the workspace', async () => {
    const { workflow, ui } = setup()
    exportOutputs.mockResolvedValue({ dir: 'exports/Math-chain', files: [{ ref: 'sum.out' }] })
    const app = mountMode()
    await app.get('[data-testid="app-export"]').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(exportOutputs).toHaveBeenCalledWith(workflow.id, {
      refs: ['sum.out'],
      overwrite: true,
    })
    expect(app.get('[data-testid="app-exported"]').text()).toContain('exports/Math-chain')
    expect(ui.toast?.message).toContain('exports/Math-chain')
  })

  it('shows the empty state until something is promoted, and returns to the graph', async () => {
    setActivePinia(createPinia())
    const schema = useNodesSchemaStore()
    schema.specs = SPECS
    schema.types = TYPES
    schema.status = 'ready'
    const workflow = useWorkflowStore()
    workflow.autosaveEnabled = false
    workflow.load(mathChain())
    const ui = useUiStore()
    ui.setMode('app')

    const app = mountMode()
    expect(app.get('[data-testid="app-empty"]').text()).toContain('Nothing promoted yet')
    await app.get('[data-testid="app-show-graph"]').trigger('click')
    expect(ui.mode).toBe('canvas')
  })

  it('renders the live renderer of a finished view instead of the stored kind', async () => {
    const { view, execution } = setup()
    execution.nodes['sum'] = {
      ...idleExecution(),
      state: 'done',
      summaries: { out: { typeId: 'astro.Float', summary: { data: { value: 7 } }, ts: 1 } },
    }
    const app = mountMode()
    await app.vm.$nextTick()
    const tile = app.get(`[data-testid="view-tile-${view}"]`)
    expect(tile.attributes('data-state')).toBe('done')
    expect(tile.attributes('data-renderer')).toBe('kv-tile')
  })
})
