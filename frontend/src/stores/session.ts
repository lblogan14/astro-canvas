/**
 * Glue between the WebSocket client and the stores: opens workflows (document + status snapshot
 * + subscription), routes events into the execution store and exposes run/cancel/auto-run.
 */
import { computed, ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'

import { api } from '@/api/client'
import type { PreviewViewport } from '@/api/events'
import type { DecodedFrame } from '@/api/frames'
import { type WsStatus, WsClient } from '@/api/ws'
import { useExecutionStore } from './execution'
import { useWorkflowStore } from './workflow'
import { useWorkspaceStore } from './workspace'

export type FrameListener = (frame: DecodedFrame) => void

export const useSessionStore = defineStore('session', () => {
  const client = shallowRef<WsClient | null>(null)
  const wsStatus = ref<WsStatus>('idle')
  const wsAttempt = ref(0)
  const opening = ref(false)
  const openError = ref<string | null>(null)
  const frameListeners = new Set<FrameListener>()

  const isConnected = computed(() => wsStatus.value === 'open')

  function ensureClient(factory?: () => WsClient): WsClient {
    if (client.value) return client.value
    const ws = factory ? factory() : new WsClient()
    ws.onStatus((status, attempt) => {
      wsStatus.value = status
      wsAttempt.value = attempt
      // A reconnect replays `subscribed` + snapshot from the server; refresh issues/state as well.
      if (status === 'open' && attempt === 0 && ws.workflowId) void refreshStatus(ws.workflowId)
    })
    ws.onMessage((message) => {
      if (message.type === 'workspace.changed') {
        useWorkspaceStore().applyChange(message.paths)
        return
      }
      useExecutionStore().applyMessage(message)
    })
    ws.onFrame((frame) => {
      for (const listener of frameListeners) listener(frame)
    })
    client.value = ws
    return ws
  }

  function connect(factory?: () => WsClient): void {
    ensureClient(factory).connect()
  }

  function disconnect(): void {
    client.value?.close()
    client.value = null
    wsStatus.value = 'closed'
  }

  async function refreshStatus(workflowId: string): Promise<void> {
    try {
      const status = await api.getWorkflowStatus(workflowId)
      useExecutionStore().applySnapshot(status)
    } catch {
      // the snapshot is best-effort; WS events keep the state current
    }
  }

  /** Load a workflow, its status snapshot, and subscribe to its events. */
  async function openWorkflow(workflowId: string): Promise<void> {
    const workflow = useWorkflowStore()
    const execution = useExecutionStore()
    opening.value = true
    openError.value = null
    try {
      await workflow.open(workflowId)
      execution.reset()
      await refreshStatus(workflowId)
      ensureClient().subscribe(workflowId)
    } catch (err) {
      openError.value = err instanceof Error ? err.message : String(err)
      throw err
    } finally {
      opening.value = false
    }
  }

  /** Create a new workflow and open it. */
  async function createWorkflow(name: string): Promise<string> {
    const workflow = useWorkflowStore()
    const execution = useExecutionStore()
    const id = await workflow.create(name)
    execution.reset()
    await refreshStatus(id)
    ensureClient().subscribe(id)
    return id
  }

  function closeWorkflow(): void {
    useWorkflowStore().close()
    useExecutionStore().reset()
    client.value?.subscribe(null)
  }

  /** Run to `targets` (default: every leaf). Flushes pending edits first. */
  async function run(targets?: string[] | null): Promise<string | null> {
    const workflow = useWorkflowStore()
    const id = workflow.id
    if (!id) return null
    await workflow.saveNow()
    const accepted = await api.startRun(id, targets ?? null)
    useExecutionStore().currentRunId = accepted.run_id
    return accepted.run_id
  }

  async function cancel(runId?: string | null): Promise<boolean> {
    const execution = useExecutionStore()
    const target = runId ?? execution.currentRunId
    if (!target) return false
    const result = await api.cancelRun(target)
    return result.cancelled
  }

  async function setAutoRun(enabled: boolean): Promise<void> {
    const id = useWorkflowStore().id
    if (!id) return
    const settings = await api.setWorkflowSettings(id, { auto_run: enabled })
    useExecutionStore().autoRun = settings.auto_run
  }

  function requestPreview(nodeId: string, port: string, viewport: PreviewViewport = {}): boolean {
    return client.value?.requestPreview(nodeId, port, viewport) ?? false
  }

  function requestOutput(nodeId: string, port: string): boolean {
    return client.value?.requestOutput(nodeId, port) ?? false
  }

  function onFrame(listener: FrameListener): () => void {
    frameListeners.add(listener)
    return () => frameListeners.delete(listener)
  }

  return {
    client,
    wsStatus,
    wsAttempt,
    opening,
    openError,
    isConnected,
    connect,
    disconnect,
    refreshStatus,
    openWorkflow,
    createWorkflow,
    closeWorkflow,
    run,
    cancel,
    setAutoRun,
    requestPreview,
    requestOutput,
    onFrame,
  }
})
