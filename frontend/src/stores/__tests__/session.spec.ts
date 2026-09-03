import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { ApiError, api } from '@/api/client'
import type { DecodedFrame } from '@/api/frames'
import { WsClient } from '@/api/ws'
import { useExecutionStore } from '@/stores/execution'
import { useSessionStore } from '@/stores/session'
import { useWorkflowStore } from '@/stores/workflow'
import { mathChain } from './fixtures'

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return {
    ...original,
    api: {
      getWorkflow: vi.fn<typeof original.api.getWorkflow>(),
      createWorkflow: vi.fn<typeof original.api.createWorkflow>(),
      putWorkflow: vi.fn<typeof original.api.putWorkflow>(),
      getWorkflowStatus: vi.fn<typeof original.api.getWorkflowStatus>(),
      startRun: vi.fn<typeof original.api.startRun>(),
      cancelRun: vi.fn<typeof original.api.cancelRun>(),
      setWorkflowSettings: vi.fn<typeof original.api.setWorkflowSettings>(),
    },
  }
})

const mocked = vi.mocked(api)

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

function fakeClient(): WsClient {
  return new WsClient({
    url: () => 'ws://test',
    factory: () => new FakeSocket() as unknown as WebSocket,
    pingIntervalMs: 0,
  })
}

const status = (workflowId: string) => ({
  workflow_id: workflowId,
  node_errors: {},
  nodes: {},
  current_run: null,
  auto_run: true,
})

describe('session store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    for (const fn of Object.values(mocked)) fn.mockReset()
    FakeSocket.last = null
  })

  it('connects once, tracks socket status and routes messages into the execution store', () => {
    const session = useSessionStore()
    session.connect(fakeClient)
    session.connect()
    expect(session.wsStatus).toBe('connecting')
    const socket = FakeSocket.last!
    socket.onopen?.()
    expect(session.isConnected).toBe(true)
    socket.onmessage?.({
      data: JSON.stringify({
        type: 'node.status',
        ts: 1,
        workflow_id: 'w',
        node_id: 'a',
        state: 'running',
        run_id: 'r',
        cache_hit: false,
        elapsed_ms: null,
        cost_class: 'cheap',
        stale: false,
      }),
    })
    expect(useExecutionStore().node('a').state).toBe('running')
    session.disconnect()
    expect(session.wsStatus).toBe('closed')
    expect(session.client).toBeNull()
  })

  it('opens a workflow: loads the doc, applies the status snapshot and subscribes', async () => {
    mocked.getWorkflow.mockResolvedValue(mathChain())
    mocked.getWorkflowStatus.mockResolvedValue({
      ...status('sample-math-chain'),
      current_run: 'r1',
      auto_run: false,
      node_errors: { c: [{ code: 'bad_param', message: 'x' }] },
    })
    const session = useSessionStore()
    session.connect(fakeClient)
    FakeSocket.last!.onopen?.()
    await session.openWorkflow('sample-math-chain')
    expect(useWorkflowStore().id).toBe('sample-math-chain')
    const execution = useExecutionStore()
    expect(execution.currentRunId).toBe('r1')
    expect(execution.autoRun).toBe(false)
    expect(execution.issueCount).toBe(1)
    expect(JSON.parse(FakeSocket.last!.sent.at(-1)!)).toEqual({
      type: 'subscribe',
      workflow_id: 'sample-math-chain',
    })
    expect(session.opening).toBe(false)
    expect(session.openError).toBeNull()
  })

  it('reports open failures and re-fetches the status snapshot after a reconnect', async () => {
    mocked.getWorkflow.mockRejectedValueOnce(new ApiError(404, 'unknown workflow'))
    const session = useSessionStore()
    session.connect(fakeClient)
    await expect(session.openWorkflow('missing')).rejects.toBeInstanceOf(ApiError)
    expect(session.openError).toBe('unknown workflow')

    mocked.getWorkflow.mockResolvedValue(mathChain())
    mocked.getWorkflowStatus.mockResolvedValue(status('sample-math-chain'))
    await session.openWorkflow('sample-math-chain')
    expect(mocked.getWorkflowStatus).toHaveBeenCalledTimes(1)
    const socket = FakeSocket.last!
    socket.onopen?.()
    expect(mocked.getWorkflowStatus).toHaveBeenCalledTimes(2)
    // a snapshot failure is swallowed
    mocked.getWorkflowStatus.mockRejectedValueOnce(new ApiError(500, 'x'))
    await session.refreshStatus('sample-math-chain')
  })

  it('creates a workflow and subscribes to it; closing unsubscribes', async () => {
    mocked.createWorkflow.mockImplementation(async (doc) => ({ doc, node_errors: {} }))
    mocked.getWorkflowStatus.mockImplementation(async (id) => status(id))
    const session = useSessionStore()
    session.connect(fakeClient)
    FakeSocket.last!.onopen?.()
    const id = await session.createWorkflow('Fresh')
    expect(useWorkflowStore().name).toBe('Fresh')
    expect(JSON.parse(FakeSocket.last!.sent.at(-1)!)).toEqual({
      type: 'subscribe',
      workflow_id: id,
    })
    session.closeWorkflow()
    expect(useWorkflowStore().isOpen).toBe(false)
    expect(session.client?.workflowId).toBeNull()
  })

  it('runs after flushing edits, cancels the current run and toggles auto-run', async () => {
    mocked.getWorkflow.mockResolvedValue(mathChain())
    mocked.getWorkflowStatus.mockResolvedValue(status('sample-math-chain'))
    mocked.putWorkflow.mockImplementation(async (doc) => ({ doc, node_errors: {} }))
    mocked.startRun.mockResolvedValue({ run_id: 'r9', workflow_id: 'sample-math-chain' })
    mocked.cancelRun.mockResolvedValue({ cancelled: true })
    mocked.setWorkflowSettings.mockImplementation(async (_id, settings) => settings)
    const session = useSessionStore()
    expect(await session.run()).toBeNull()
    expect(await session.cancel()).toBe(false)
    await session.setAutoRun(false)
    expect(mocked.setWorkflowSettings).not.toHaveBeenCalled()

    await session.openWorkflow('sample-math-chain')
    const workflow = useWorkflowStore()
    workflow.setParam('c', 'value', 9)
    expect(await session.run(['sum'])).toBe('r9')
    expect(mocked.putWorkflow).toHaveBeenCalledTimes(1)
    expect(mocked.startRun).toHaveBeenCalledWith('sample-math-chain', ['sum'])
    const execution = useExecutionStore()
    expect(execution.currentRunId).toBe('r9')
    expect(await session.cancel()).toBe(true)
    expect(mocked.cancelRun).toHaveBeenCalledWith('r9')
    await session.setAutoRun(false)
    expect(execution.autoRun).toBe(false)
  })

  it('forwards binary frames and preview/output requests through the client', () => {
    const session = useSessionStore()
    expect(session.requestPreview('n', 'p')).toBe(false)
    expect(session.requestOutput('n', 'p')).toBe(false)
    session.connect(fakeClient)
    const socket = FakeSocket.last!
    socket.onopen?.()
    const frames: DecodedFrame[] = []
    const off = session.onFrame((frame) => frames.push(frame))
    expect(session.requestPreview('n', 'p', { lo: 1 })).toBe(true)
    expect(session.requestOutput('n', 'p')).toBe(true)
    const header = new TextEncoder().encode('§node_id¡n¦arrays')
    const buffer = new Uint8Array(8 + header.byteLength)
    new DataView(buffer.buffer).setUint32(0, 1, true)
    new DataView(buffer.buffer).setUint32(4, header.byteLength, true)
    buffer.set(header, 8)
    // The hand-built header above is not valid msgpack once UTF-8 encoded, so the frame is dropped…
    socket.onmessage?.({ data: buffer.buffer })
    expect(frames).toEqual([])
    off()
  })
})
