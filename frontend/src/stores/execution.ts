/**
 * Runtime state per node (status, progress, error, output summaries), compile issues, the run log
 * and the current run, fed by WebSocket events and `/status` snapshots. Keyed by node id so one
 * event re-renders one node (design §10.2).
 */
import { computed, ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'

import type { EngineEvent, RunStatus, ServerMessage } from '@/api/events'
import type { Cost, NodeErrors, NodeIssue, NodeState, WorkflowStatus } from '@/api/types'

export interface NodeExecution {
  state: NodeState
  stale: boolean
  cacheHit: boolean
  elapsedMs: number | null
  costClass: Cost
  runId: string | null
  progress: { frac: number; message: string | null } | null
  error: { message: string; traceback: string; hint: string | null } | null
  /** Latest summary per output port (`$preview` for `ctx.preview` payloads). */
  summaries: Record<string, SummaryEntry>
}

export interface SummaryEntry {
  typeId: string
  summary: Record<string, unknown>
  ts: number
}

export function viewKey(nodeId: string, port: string, tag: string): string {
  return `${nodeId}/${port}#${tag}`
}

/** Outcome of a `preview.compute` (editor live preview), keyed `node#tag`. */
export interface ComputeEntry {
  ok: boolean
  ports: string[]
  error: string | null
  elapsedMs: number
  ts: number
}

export function computeKey(nodeId: string, tag: string): string {
  return `${nodeId}#${tag}`
}

export interface LogEntry {
  id: number
  ts: number
  level: string
  nodeId: string | null
  message: string
  fields?: Record<string, unknown>
}

export interface RunInfo {
  runId: string
  status: RunStatus
  startedAt: number
  finishedAt: number | null
  nNodes: number
  cached: number
  targets: string[] | null
  elapsedMs: number | null
}

export const MAX_LOG = 500

export function idleExecution(): NodeExecution {
  return {
    state: 'idle',
    stale: false,
    cacheHit: false,
    elapsedMs: null,
    costClass: 'cheap',
    runId: null,
    progress: null,
    error: null,
    summaries: {},
  }
}

export const useExecutionStore = defineStore('execution', () => {
  const nodes = ref<Record<string, NodeExecution>>({})
  const issues = ref<NodeErrors>({})
  const log = shallowRef<LogEntry[]>([])
  const runs = ref<Record<string, RunInfo>>({})
  const currentRunId = ref<string | null>(null)
  const autoRun = ref(true)
  const lastServerError = ref<string | null>(null)
  /** Tagged summaries (`preview.request` with `viewport.tag`), keyed `node/port#tag`. */
  const views = shallowRef<Record<string, SummaryEntry>>({})
  /** Results of `preview.compute` requests, keyed `node#tag`. */
  const computes = shallowRef<Record<string, ComputeEntry>>({})
  let logSeq = 0

  const isRunning = computed(() => currentRunId.value !== null)
  const issueCount = computed(() =>
    Object.values(issues.value).reduce((sum, list) => sum + list.length, 0),
  )
  const errorNodeIds = computed(() =>
    Object.entries(nodes.value)
      .filter(([, n]) => n.state === 'error')
      .map(([id]) => id),
  )
  const currentRun = computed(() =>
    currentRunId.value ? (runs.value[currentRunId.value] ?? null) : null,
  )

  function node(id: string): NodeExecution {
    return nodes.value[id] ?? idleExecution()
  }

  function issuesFor(id: string): NodeIssue[] {
    return issues.value[id] ?? []
  }

  function ensure(id: string): NodeExecution {
    const existing = nodes.value[id]
    if (existing) return existing
    const fresh = idleExecution()
    nodes.value[id] = fresh
    return fresh
  }

  function append(entry: Omit<LogEntry, 'id'>): void {
    logSeq += 1
    const next = [...log.value, { id: logSeq, ...entry }]
    log.value = next.length > MAX_LOG ? next.slice(next.length - MAX_LOG) : next
  }

  function view(nodeId: string, port: string, tag: string): SummaryEntry | undefined {
    return views.value[viewKey(nodeId, port, tag)]
  }

  function clearView(nodeId: string, port: string, tag: string): void {
    const rest = { ...views.value }
    delete rest[viewKey(nodeId, port, tag)]
    views.value = rest
  }

  function compute(nodeId: string, tag: string): ComputeEntry | undefined {
    return computes.value[computeKey(nodeId, tag)]
  }

  /** Forget a node's tagged views and compute result (an editor closing). */
  function clearTag(nodeId: string, tag: string): void {
    const suffix = `#${tag}`
    const prefix = `${nodeId}/`
    const rest: Record<string, SummaryEntry> = {}
    for (const [key, entry] of Object.entries(views.value)) {
      if (!(key.startsWith(prefix) && key.endsWith(suffix))) rest[key] = entry
    }
    views.value = rest
    const remaining = { ...computes.value }
    delete remaining[computeKey(nodeId, tag)]
    computes.value = remaining
  }

  function reset(): void {
    nodes.value = {}
    views.value = {}
    computes.value = {}
    issues.value = {}
    log.value = []
    runs.value = {}
    currentRunId.value = null
    lastServerError.value = null
  }

  function setIssues(nodeErrors: NodeErrors): void {
    issues.value = nodeErrors
  }

  /** Drop runtime records for nodes that no longer exist. */
  function prune(existing: (id: string) => boolean): void {
    for (const id of Object.keys(nodes.value)) {
      if (!existing(id) && !id.includes('/')) delete nodes.value[id]
    }
  }

  /** Apply a `GET /workflows/{id}/status` snapshot (load, reconnect). */
  function applySnapshot(status: WorkflowStatus): void {
    issues.value = status.node_errors
    currentRunId.value = status.current_run ?? null
    autoRun.value = status.auto_run ?? true
    for (const [id, s] of Object.entries(status.nodes)) {
      const record = ensure(id)
      nodes.value[id] = {
        ...record,
        state: s.state,
        stale: s.stale,
        cacheHit: s.cache_hit,
        elapsedMs: s.elapsed_ms ?? null,
        costClass: s.cost_class,
        runId: s.run_id ?? null,
        error: s.state === 'error' ? record.error : null,
        progress: s.state === 'running' ? record.progress : null,
      }
    }
  }

  function applyEngineEvent(event: EngineEvent): void {
    switch (event.type) {
      case 'node.status': {
        const record = ensure(event.node_id)
        nodes.value[event.node_id] = {
          ...record,
          state: event.state,
          stale: event.stale,
          cacheHit: event.cache_hit,
          elapsedMs: event.elapsed_ms,
          costClass: event.cost_class,
          runId: event.run_id,
          progress: event.state === 'running' ? record.progress : null,
          error: event.state === 'error' ? record.error : null,
        }
        break
      }
      case 'node.progress': {
        const record = ensure(event.node_id)
        nodes.value[event.node_id] = {
          ...record,
          progress: { frac: event.frac, message: event.message },
        }
        break
      }
      case 'node.log':
        append({
          ts: event.ts,
          level: event.level,
          nodeId: event.node_id,
          message: event.message,
          fields: event.fields,
        })
        break
      case 'node.error': {
        const record = ensure(event.node_id)
        nodes.value[event.node_id] = {
          ...record,
          error: { message: event.message, traceback: event.traceback, hint: event.hint },
        }
        append({ ts: event.ts, level: 'error', nodeId: event.node_id, message: event.message })
        break
      }
      case 'node.output.summary': {
        if (event.tag) {
          views.value = {
            ...views.value,
            [viewKey(event.node_id, event.port, event.tag)]: {
              typeId: event.type_id,
              summary: event.summary,
              ts: event.ts,
            },
          }
          break
        }
        const record = ensure(event.node_id)
        nodes.value[event.node_id] = {
          ...record,
          summaries: {
            ...record.summaries,
            [event.port]: { typeId: event.type_id, summary: event.summary, ts: event.ts },
          },
        }
        break
      }
      case 'graph.validation':
        issues.value = event.node_errors
        break
      case 'run.started':
        runs.value[event.run_id] = {
          runId: event.run_id,
          status: 'running',
          startedAt: event.ts,
          finishedAt: null,
          nNodes: event.n_nodes,
          cached: event.cached,
          targets: event.targets,
          elapsedMs: null,
        }
        currentRunId.value = event.run_id
        append({
          ts: event.ts,
          level: 'info',
          nodeId: null,
          message: `run.started ${event.run_id} (${event.n_nodes} nodes)`,
        })
        break
      case 'run.finished': {
        const existing = runs.value[event.run_id]
        runs.value[event.run_id] = {
          runId: event.run_id,
          status: event.status,
          startedAt: existing?.startedAt ?? event.ts - event.elapsed_ms / 1000,
          finishedAt: event.ts,
          nNodes: event.n_nodes,
          cached: event.cached,
          targets: event.targets,
          elapsedMs: event.elapsed_ms,
        }
        if (currentRunId.value === event.run_id) currentRunId.value = null
        append({
          ts: event.ts,
          level: event.status === 'done' ? 'info' : 'warning',
          nodeId: null,
          message: `run.finished ${event.run_id} ${event.status} in ${Math.round(event.elapsed_ms)} ms`,
        })
        break
      }
      case 'workspace.changed':
      case 'packs.changed':
        break
    }
  }

  /** Handle anything the WebSocket delivers. */
  function applyMessage(message: ServerMessage): void {
    switch (message.type) {
      case 'hello':
      case 'pong':
        return
      case 'subscribed':
        currentRunId.value = message.current_run
        autoRun.value = message.auto_run
        return
      case 'run.accepted':
        currentRunId.value = message.run_id
        return
      case 'batch.accepted':
      case 'batch.cancelled':
      case 'batch.started':
      case 'batch.row':
      case 'batch.finished':
        return // the batch store owns these
      case 'cancel.result':
        return
      case 'error':
        lastServerError.value = message.message
        append({ ts: message.ts, level: 'error', nodeId: null, message: message.message })
        return
      case 'preview.computed': {
        const key = computeKey(message.node_id ?? `type:${message.node_type ?? ''}`, message.tag)
        computes.value = {
          ...computes.value,
          [key]: {
            ok: message.ok,
            ports: message.ports ?? [],
            error: message.error ?? null,
            elapsedMs: message.elapsed_ms,
            ts: message.ts,
          },
        }
        return
      }
      default:
        applyEngineEvent(message)
    }
  }

  function clearLog(): void {
    log.value = []
  }

  return {
    nodes,
    issues,
    log,
    runs,
    currentRunId,
    currentRun,
    autoRun,
    lastServerError,
    isRunning,
    issueCount,
    errorNodeIds,
    views,
    computes,
    node,
    view,
    clearView,
    compute,
    clearTag,
    issuesFor,
    reset,
    setIssues,
    prune,
    applySnapshot,
    applyEngineEvent,
    applyMessage,
    clearLog,
  }
})
