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

export type ServerMessage =
  | EngineEvent
  | HelloMessage
  | SubscribedMessage
  | RunAcceptedMessage
  | CancelResultMessage
  | PongMessage
  | ErrorMessage

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
])

/** Narrow an arbitrary JSON payload to a known server message (or `null`). */
export function parseServerMessage(payload: unknown): ServerMessage | null {
  if (typeof payload !== 'object' || payload === null) return null
  const type = (payload as { type?: unknown }).type
  if (typeof type !== 'string' || !MESSAGE_TYPES.has(type)) return null
  return payload as ServerMessage
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
      viewport: { lo?: number; hi?: number; n_out?: number }
    }
  | { type: 'output.request'; node_id: string; port: string }
  | { type: 'ping' }
