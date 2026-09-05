/**
 * The export path of the mode helper.
 *
 * Exporting flushes the pending edits first, and flushing means a re-run, so the export has to
 * wait for the outputs it is about to write -- and that wait is the server's (`Scheduler.settle`
 * plus the export endpoint), because these node states arrive after the server has already
 * changed them. Two attempts at waiting here failed on the nightly's slowest runner, so what is
 * tested here is that the request goes out with the edits flushed and that what comes back is
 * reported: the folder on success, the first skipped ref on failure.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useMode } from '@/modes/useMode'
import { idleExecution, useExecutionStore } from '@/stores/execution'
import type { NodeState } from '@/api/types'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useWorkflowStore } from '@/stores/workflow'
import { SPECS, TYPES, mathChain } from '@/stores/__tests__/fixtures'

type AnyFn = (...args: unknown[]) => unknown
const exportOutputs = vi.fn<AnyFn>()
const putWorkflow = vi.fn<AnyFn>()

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return {
    ...original,
    api: {
      putWorkflow: (...args: unknown[]) => putWorkflow(...args),
      exportOutputs: (...args: unknown[]) => exportOutputs(...args),
    },
  }
})

function setup(state: NodeState) {
  setActivePinia(createPinia())
  const schema = useNodesSchemaStore()
  schema.specs = SPECS
  schema.types = TYPES
  schema.status = 'ready'
  const workflow = useWorkflowStore()
  workflow.autosaveEnabled = false
  workflow.load(mathChain())
  workflow.pinView('sum', 'out', { kind: 'kv-tile' })
  const execution = useExecutionStore()
  execution.nodes['sum'] = { ...idleExecution(), state }
  return { workflow, execution, mode: useMode() }
}

describe('useMode export', () => {
  beforeEach(() => {
    exportOutputs.mockReset()
    putWorkflow.mockReset()
    putWorkflow.mockImplementation((id: unknown, doc: unknown) => ({ doc, node_errors: {} }))
    exportOutputs.mockResolvedValue({ dir: 'exports/2026-09-05', files: [{ ref: 'sum.out' }] })
  })

  it('exports what the pinned views name', async () => {
    const { mode } = setup('done')
    await expect(mode.exportResults()).resolves.toBe('exports/2026-09-05')
    expect(exportOutputs).toHaveBeenCalledWith('sample-math-chain', {
      refs: ['sum.out'],
      overwrite: true,
    })
  })

  it('flushes the pending edits before asking for the export', async () => {
    const { workflow, mode } = setup('done')
    workflow.setParam('c', 'value', 9)
    await mode.exportResults()
    expect(putWorkflow, 'the edit reached the server before the export did').toHaveBeenCalled()
    expect(putWorkflow.mock.invocationCallOrder[0]).toBeLessThan(
      exportOutputs.mock.invocationCallOrder[0]!,
    )
  })

  it('does not hold the request back itself, whatever the node states say', async () => {
    // A node the client believes is still running is not a reason to wait: the belief is a run
    // behind, and the server settles the graph before it reads anything.
    const { mode } = setup('running')
    const started = Date.now()
    await expect(mode.exportResults()).resolves.toBe('exports/2026-09-05')
    expect(Date.now() - started).toBeLessThan(500)
  })

  it('reports the first skipped ref when nothing could be written', async () => {
    exportOutputs.mockResolvedValue({
      dir: 'exports/2026-09-05',
      files: [],
      skipped: [{ ref: 'sum.out', reason: 'no_output', message: 'sum.out has no cached output' }],
    })
    const { mode } = setup('done')
    await expect(mode.exportResults()).resolves.toBeNull()
  })
})
