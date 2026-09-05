/**
 * The export path of the mode helper.
 *
 * Exporting flushes the pending edits first, and flushing means a re-run, so the export has to
 * wait for the outputs it is about to write. It used to sleep for a fixed 400 ms and then watch
 * `isRunning`, which is a race the auto-run debounce wins on a slow machine: nothing was running
 * yet, so the wait returned immediately and the server answered `"ew.out has no cached output"`.
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

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return {
    ...original,
    api: {
      putWorkflow: vi.fn<AnyFn>(),
      exportOutputs: (...args: unknown[]) => exportOutputs(...args),
    },
  }
})

/** Wait `ms` of real time — the settle loop polls, so the test has to let it. */
const wait = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

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

  it('holds the export until the node it exports has finished recomputing', async () => {
    const { execution, mode } = setup('running')
    const pending = mode.exportResults()

    await wait(800)
    expect(exportOutputs, 'exported while the node was still running').not.toHaveBeenCalled()

    execution.nodes['sum'] = { ...idleExecution(), state: 'done' }
    await expect(pending).resolves.toBe('exports/2026-09-05')
    expect(exportOutputs).toHaveBeenCalledOnce()
  })

  it('does not wait out a dirty node that nothing is going to run', async () => {
    const { execution, mode } = setup('dirty')
    execution.autoRun = false

    const started = Date.now()
    await expect(mode.exportResults()).resolves.toBe('exports/2026-09-05')
    // Long enough for the debounce to have armed, far short of the 60 s timeout.
    expect(Date.now() - started).toBeLessThan(5000)
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
