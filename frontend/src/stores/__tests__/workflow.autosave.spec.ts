import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { ApiError, api } from '@/api/client'
import type { WorkflowDoc, WorkflowSaved } from '@/api/types'
import { useExecutionStore } from '@/stores/execution'
import { useWorkflowStore } from '@/stores/workflow'
import { mathChain } from './fixtures'

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return {
    ...original,
    api: {
      putWorkflow: vi.fn<typeof original.api.putWorkflow>(),
      createWorkflow: vi.fn<typeof original.api.createWorkflow>(),
      getWorkflow: vi.fn<typeof original.api.getWorkflow>(),
    },
  }
})

const putWorkflow = vi.mocked(api.putWorkflow)
const createWorkflow = vi.mocked(api.createWorkflow)
const getWorkflow = vi.mocked(api.getWorkflow)

function saved(doc: WorkflowDoc, nodeErrors = {}): WorkflowSaved {
  return {
    doc: {
      ...doc,
      meta: { ...doc.meta, modified: '2026-09-02T12:00:00', created: '2026-09-02T00:00:00' },
    },
    node_errors: nodeErrors,
  }
}

describe('workflow store: autosave', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    putWorkflow.mockReset()
    createWorkflow.mockReset()
    getWorkflow.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('folds a burst of edits into one PUT and adopts server meta without a command', async () => {
    putWorkflow.mockImplementation(async (doc) =>
      saved(doc, { sum: [{ code: 'bad_param', message: 'x' }] }),
    )
    const wf = useWorkflowStore()
    wf.load(mathChain())
    wf.setParam('c', 'value', 3)
    expect(wf.saveState).toBe('pending')
    // Each edit re-arms the 250 ms window, so continuous typing still saves once.
    vi.advanceTimersByTime(200)
    wf.setParam('c', 'value', 4)
    vi.advanceTimersByTime(200)
    expect(putWorkflow).not.toHaveBeenCalled()
    vi.advanceTimersByTime(100)
    await vi.runOnlyPendingTimersAsync()
    expect(putWorkflow).toHaveBeenCalledTimes(1)
    const sent = putWorkflow.mock.calls[0]![0]
    expect(sent.nodes?.c?.params).toEqual({ value: 4 })
    expect(wf.saveState).toBe('saved')
    expect(wf.isDirty).toBe(false)
    expect(wf.doc?.meta?.modified).toBe('2026-09-02T12:00:00')
    expect(wf.undoStack).toHaveLength(1)
    expect(useExecutionStore().issues).toEqual({ sum: [{ code: 'bad_param', message: 'x' }] })
    expect(wf.lastSavedAt).not.toBeNull()
  })

  it('re-saves when edits arrive while a save is in flight', async () => {
    let release: (value: WorkflowSaved) => void = () => undefined
    putWorkflow.mockImplementationOnce(
      () =>
        new Promise<WorkflowSaved>((resolve) => {
          release = resolve
        }),
    )
    putWorkflow.mockImplementation(async (doc) => saved(doc))
    const wf = useWorkflowStore()
    wf.load(mathChain())
    wf.setParam('c', 'value', 1)
    vi.advanceTimersByTime(1000)
    expect(wf.saveState).toBe('saving')
    wf.setParam('c', 'value', 2)
    release(saved(mathChain()))
    await vi.runOnlyPendingTimersAsync()
    await vi.runOnlyPendingTimersAsync()
    expect(putWorkflow).toHaveBeenCalledTimes(2)
    expect(putWorkflow.mock.calls[1]![0].nodes?.c?.params).toEqual({ value: 2 })
    expect(wf.saveState).toBe('saved')
  })

  it('records errors and retries on the next edit; saveNow is a no-op when clean', async () => {
    putWorkflow.mockRejectedValueOnce(new ApiError(500, 'boom'))
    putWorkflow.mockImplementation(async (doc) => saved(doc))
    const wf = useWorkflowStore()
    wf.load(mathChain())
    await wf.saveNow()
    expect(putWorkflow).not.toHaveBeenCalled()
    wf.rename('Renamed')
    await wf.saveNow()
    expect(wf.saveState).toBe('error')
    expect(wf.saveError).toBe('boom')
    expect(wf.isDirty).toBe(true)
    wf.rename('Renamed again')
    await vi.advanceTimersByTimeAsync(1000)
    expect(wf.saveState).toBe('saved')
    expect(wf.saveError).toBeNull()
  })

  it('undo and redo also schedule a save', async () => {
    putWorkflow.mockImplementation(async (doc) => saved(doc))
    const wf = useWorkflowStore()
    wf.load(mathChain())
    wf.setParam('c', 'value', 9)
    await vi.advanceTimersByTimeAsync(1000)
    expect(putWorkflow).toHaveBeenCalledTimes(1)
    wf.undo()
    expect(wf.isDirty).toBe(true)
    await vi.advanceTimersByTimeAsync(1000)
    expect(putWorkflow).toHaveBeenCalledTimes(2)
    expect(putWorkflow.mock.calls[1]![0].nodes?.c?.params).toEqual({ value: 2 })
    wf.redo()
    await vi.advanceTimersByTimeAsync(1000)
    expect(putWorkflow).toHaveBeenCalledTimes(3)
  })

  it('loading another document cancels a pending save', async () => {
    putWorkflow.mockImplementation(async (doc) => saved(doc))
    const wf = useWorkflowStore()
    wf.load(mathChain())
    wf.setParam('c', 'value', 9)
    wf.load({ ...mathChain(), id: 'other' })
    await vi.advanceTimersByTimeAsync(2000)
    expect(putWorkflow).not.toHaveBeenCalled()
    expect(wf.saveState).toBe('clean')
  })

  it('create posts an empty document and opens it; open fetches by id', async () => {
    createWorkflow.mockImplementation(async (doc) => saved(doc))
    getWorkflow.mockResolvedValue(mathChain())
    const wf = useWorkflowStore()
    const id = await wf.create('Fresh')
    expect(id).toMatch(/^wf_/)
    expect(wf.name).toBe('Fresh')
    expect(wf.isDirty).toBe(false)
    await wf.open('sample-math-chain')
    expect(wf.id).toBe('sample-math-chain')
    expect(getWorkflow).toHaveBeenCalledWith('sample-math-chain')
  })

  it('normalises documents missing optional maps', () => {
    const wf = useWorkflowStore()
    const bare = mathChain()
    delete bare.nodes
    delete bare.edges
    delete bare.groups
    delete bare.meta
    delete bare.id
    wf.load(bare)
    expect(wf.nodes).toEqual({})
    expect(wf.edges).toEqual({})
    expect(wf.groups).toEqual({})
    expect(wf.id).toMatch(/^wf_/)
  })
})
