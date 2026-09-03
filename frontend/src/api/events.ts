/**
 * Engine events streamed over `/ws` (mirror of `astro_canvas/engine/events.py`) and the
 * commands the client may send. Events are not part of OpenAPI, so they are typed by hand;
 * keep this file in sync with the Python models and `docs/formats/workflow.md`.
 */
import type { Cost, NodeErrors, NodeState } from './types'

export type RunStatus = 'running' | 'done' | 'error' | 'cancelled'

interface BaseEvent {
  ts: number
  workflow_id: string
}

export interface RunStartedEvent extends BaseEvent {
  type: 'run.started'
  run_id: string
  targets: string[] | null
  n_nodes: number
  cached: number
}

export interface RunFinishedEvent extends BaseEvent {
  type: 'run.finished'
  run_id: string
  targets: string[] | null
  n_nodes: number
  cached: number
  status: RunStatus
  elapsed_ms: number
}

export interface NodeStatusEvent extends BaseEvent {
  type: 'node.status'
  node_id: string
  state: NodeState
  run_id: string | null
  cache_hit: boolean
  elapsed_ms: number | null
  cost_class: Cost
  stale: boolean
}

export interface NodeProgressEvent extends BaseEvent {
  type: 'node.progress'
  node_id: string
  frac: number
  message: string | null
}

export interface NodeLogEvent extends BaseEvent {
  type: 'node.log'
  node_id: string
  level: string
  message: string
  fields: Record<string, unknown>
}

export interface NodeErrorEvent extends BaseEvent {
  type: 'node.error'
  node_id: string
  message: string
  traceback: string
  hint: string | null
}

export interface NodeOutputSummaryEvent extends BaseEvent {
  type: 'node.output.summary'
  node_id: string
  /** `"$preview"` carries `ctx.preview()` payloads. */
  port: string
  type_id: string
  summary: Record<string, unknown>
  /** Echo of `viewport.tag` from a `preview.request`; tagged summaries belong to one view. */
  tag?: string | null
}

export interface GraphValidationEvent extends BaseEvent {
  type: 'graph.validation'
  node_errors: NodeErrors
}

export interface WorkspaceChangedEvent extends BaseEvent {
  type: 'workspace.changed'
  paths: string[]
}

export interface PacksChangedEvent extends BaseEvent {
  type: 'packs.changed'
  event: string
}

/** Events published by the engine (`EventBus`). */
export type EngineEvent =
  | RunStartedEvent
  | RunFinishedEvent
  | NodeStatusEvent
  | NodeProgressEvent
  | NodeLogEvent
  | NodeErrorEvent
  | NodeOutputSummaryEvent
  | GraphValidationEvent
  | WorkspaceChangedEvent
  | PacksChangedEvent

/** Replies the WebSocket session itself sends (not engine events). */
export interface HelloMessage {
  type: 'hello'
  client_id: string
  version: string
  ts: number
}

export interface SubscribedMessage {
  type: 'subscribed'
  workflow_id: string
  ts: number
  current_run: string | null
  auto_run: boolean
}

export interface RunAcceptedMessage {
  type: 'run.accepted'
  run_id: string
  workflow_id: string
  ts: number
}

export interface CancelResultMessage {
  type: 'cancel.result'
  cancelled: boolean
  ts: number
}

export interface PongMessage {
  type: 'pong'
  ts: number
}

export interface ErrorMessage {
  type: 'error'
  message: string
  ts: number
}

/** Reply to `preview.compute`: the tagged summaries were sent (ok) or the node body failed. */
export interface PreviewComputedMessage {
  type: 'preview.computed'
  workflow_id: string | null
  node_id: string | null
  node_type: string | null
  tag: string
  ok: boolean
  ports?: string[]
  error?: string
  elapsed_ms: number
  ts: number
}

export type ServerMessage =
  | EngineEvent
  | HelloMessage
  | SubscribedMessage
  | RunAcceptedMessage
  | CancelResultMessage
  | PongMessage
  | ErrorMessage
  | PreviewComputedMessage

export type ServerMessageType = ServerMessage['type']

const MESSAGE_TYPES: ReadonlySet<string> = new Set<ServerMessageType>([
  'run.started',
  'run.finished',
  'node.status',
  'node.progress',
  'node.log',
  'node.error',
  'node.output.summary',
  'graph.validation',
  'workspace.changed',
  'packs.changed',
  'hello',
  'subscribed',
  'run.accepted',
  'cancel.result',
  'pong',
  'error',
  'preview.computed',
])

/** Narrow an arbitrary JSON payload to a known server message (or `null`). */
export function parseServerMessage(payload: unknown): ServerMessage | null {
  if (typeof payload !== 'object' || payload === null) return null
  const type = (payload as { type?: unknown }).type
  if (typeof type !== 'string' || !MESSAGE_TYPES.has(type)) return null
  return payload as ServerMessage
}

/**
 * What a `preview.request` may ask for: an axis range (`lo`/`hi`), a point or tile budget
 * (`n_out`), table rows, and a `tag` that the reply echoes (viewer-only summaries).
 */
export interface PreviewViewport {
  lo?: number
  hi?: number
  n_out?: number
  rows?: number
  /** `SpectrumCollection`: how many items to summarise (default 8, cap 64). */
  max_items?: number
  /** `rbcodes.MultispecView`: how many panels to summarise (default 8, cap 64). */
  max_panels?: number
  tag?: string
}

/**
 * `preview.compute`: run a node body with candidate params off the scheduler (editor live
 * previews). Either a node instance (`node_id`, inputs from the graph) or a bare node type.
 */
export interface ComputeRequest {
  node_id?: string
  node_type?: string
  params: Record<string, unknown>
  tag?: string
  viewport?: PreviewViewport
}

/** Commands the client sends; every one is a JSON object with a `type`. */
export type ClientCommand =
  | { type: 'subscribe'; workflow_id: string }
  | { type: 'run'; targets?: string[] | null }
  | { type: 'cancel'; run_id?: string | null; node_id?: string | null }
  | {
      type: 'preview.request'
      node_id: string
      port: string
      viewport: PreviewViewport
    }
  | { type: 'output.request'; node_id: string; port: string }
  | ({ type: 'preview.compute' } & ComputeRequest)
  | { type: 'ping' }
