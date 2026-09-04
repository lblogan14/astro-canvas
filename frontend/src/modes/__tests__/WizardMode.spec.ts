import { describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'

import { i18n } from '@/i18n'
import WizardMode from '@/modes/WizardMode.vue'
import { readWizardLayout } from '@/modes/layouts'
import { idleExecution, useExecutionStore } from '@/stores/execution'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'
import { SPECS, TYPES, mathChain } from '@/stores/__tests__/fixtures'

type AnyFn = (...args: unknown[]) => unknown
const startRun = vi.fn<AnyFn>()

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return {
    ...original,
    api: {
      putWorkflow: vi.fn<AnyFn>(),
      exportOutputs: vi.fn<AnyFn>(),
      startRun: (...args: unknown[]) => startRun(...args),
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
  workflow.promoteParam('sum', 'z', { label: 'Offset', group: 'Measure' })
  const view = workflow.pinView('sum', 'out', { kind: 'kv-tile' })
  return { workflow, view, execution: useExecutionStore(), ui: useUiStore() }
}

function done(nodeIds: string[]) {
  const execution = useExecutionStore()
  for (const id of nodeIds) execution.nodes[id] = { ...idleExecution(), state: 'done' }
}

function mountMode() {
  return mount(WizardMode, { global: { plugins: [i18n] } })
}

describe('Wizard mode', () => {
  it('derives one step per promoted group plus a results step', () => {
    setup()
    const wizard = mountMode()
    expect(wizard.get('[data-testid="wizard-step-0"]').text()).toContain('Load')
    expect(wizard.get('[data-testid="wizard-step-1"]').text()).toContain('Measure')
    expect(wizard.get('[data-testid="wizard-step-2"]').text()).toContain('Results')
    expect(wizard.get('[data-testid="wizard-body-0"]').text()).toContain('Constant')
  })

  it('gates Next on the step nodes being done', async () => {
    setup()
    const wizard = mountMode()
    const next = wizard.get('[data-testid="wizard-next"]')
    expect(next.attributes('disabled')).toBeDefined()
    expect(wizard.get('[data-testid="wizard-state"]').text()).toBe('Not run yet')

    done(['c'])
    await wizard.vm.$nextTick()
    expect(wizard.get('[data-testid="wizard-next"]').attributes('disabled')).toBeUndefined()
    await wizard.get('[data-testid="wizard-next"]').trigger('click')
    expect(wizard.find('[data-testid="wizard-body-1"]').exists()).toBe(true)
  })

  it('blocks Next while a step has validation errors', async () => {
    const { execution } = setup()
    done(['c'])
    execution.setIssues({ c: [{ code: 'bad_param', message: 'value must be finite' }] })
    const wizard = mountMode()
    expect(wizard.get('[data-testid="wizard-step-0"]').attributes('data-state')).toBe('error')
    expect(wizard.get('[data-testid="wizard-next"]').attributes('disabled')).toBeDefined()
    expect(wizard.get('[data-testid="wizard-problems"]').text()).toContain('must be finite')
  })

  it('keeps values when stepping back and forth', async () => {
    const { workflow } = setup()
    done(['c', 'sq', 'sum'])
    const wizard = mountMode()
    await wizard.get('[data-testid="wizard-body-0"] input').setValue('9')
    expect(workflow.rootNodes['c']?.params?.['value']).toBe(9)

    await wizard.get('[data-testid="wizard-next"]').trigger('click')
    await wizard.get('[data-testid="wizard-back"]').trigger('click')
    const input = wizard.get('[data-testid="wizard-body-0"] input')
    expect((input.element as HTMLInputElement).value).toBe('9')
  })

  it('runs only the nodes of the current step', async () => {
    setup()
    startRun.mockResolvedValue({ run_id: 'r1' })
    const wizard = mountMode()
    await wizard.get('[data-testid="wizard-run-step"]').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(startRun).toHaveBeenCalledWith(expect.any(String), ['c'])
  })

  it('skips to the results step', async () => {
    setup()
    const wizard = mountMode()
    await wizard.get('[data-testid="wizard-skip"]').trigger('click')
    expect(wizard.find('[data-testid="wizard-body-2"]').exists()).toBe(true)
    expect(wizard.find('[data-testid="wizard-export"]').exists()).toBe(true)
    expect(wizard.find('[data-testid="wizard-views"]').exists()).toBe(true)
  })

  it('edits step titles and moves items between steps, then saves the layout', async () => {
    const { workflow } = setup()
    const wizard = mountMode()
    await wizard.get('[data-testid="wizard-edit"]').trigger('click')

    const title = wizard.get('[data-testid="wizard-title-0"]')
    await title.setValue('Load spectrum')
    await title.trigger('change')
    // Move the Offset param one step earlier: it joins the renamed first step.
    await wizard
      .get('[data-testid="wizard-edit-step-1"] [data-testid="wizard-item-promoted:sum.z"]')
      .get('button')
      .trigger('click')
    await wizard.get('[data-testid="wizard-save-layout"]').trigger('click')

    const layout = readWizardLayout(workflow.layouts)
    expect(layout?.steps[0]?.title).toBe('Load spectrum')
    expect(layout?.steps[0]?.items).toEqual(['promoted:c.value', 'promoted:sum.z'])
    expect(layout?.steps[1]?.items).toEqual([])
    // The editor closed and the wizard shows the stored layout.
    expect(wizard.find('[data-testid="wizard-editor"]').exists()).toBe(false)
  })

  it('adds and removes steps, and lists unassigned items in the tray', async () => {
    const { workflow } = setup()
    workflow.setLayout('wizard', { steps: [{ title: 'Only', items: ['promoted:c.value'] }] })
    const wizard = mountMode()
    await wizard.get('[data-testid="wizard-edit"]').trigger('click')
    expect(wizard.get('[data-testid="wizard-tray"]').text()).toContain('Offset')

    await wizard.get('[data-testid="wizard-add-step"]').trigger('click')
    expect(wizard.find('[data-testid="wizard-edit-step-1"]').exists()).toBe(true)
    await wizard.get('[data-testid="wizard-remove-step-1"]').trigger('click')
    expect(wizard.find('[data-testid="wizard-edit-step-1"]').exists()).toBe(false)
  })

  it('shows the empty state with nothing promoted', () => {
    setActivePinia(createPinia())
    const schema = useNodesSchemaStore()
    schema.specs = SPECS
    schema.types = TYPES
    schema.status = 'ready'
    const workflow = useWorkflowStore()
    workflow.autosaveEnabled = false
    workflow.load(mathChain())
    expect(mountMode().find('[data-testid="wizard-empty"]').exists()).toBe(true)
  })
})
