/**
 * `WsClient`: one WebSocket to `/ws` with reconnection (exponential back-off), a single
 * workflow subscription that is re-established after every reconnect, JSON message dispatch and
 * binary frame decoding (`frames.ts`).
 *
 * The client is framework-free; the stores wrap its callbacks in reactive state.
 */
import {
  type ClientCommand,
  type PreviewViewport,
  type ServerMessage,
  parseServerMessage,
  type ComputeRequest,
} from './events'
import { type DecodedFrame, decodeFrame } from './frames'
import { wsUrl } from './client'

export type WsStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed'

export type MessageHandler = (message: ServerMessage) => void
export type FrameHandler = (frame: DecodedFrame) => void
export type StatusHandler = (status: WsStatus, attempt: number) => void

export type TimerId = ReturnType<typeof globalThis.setTimeout>
export type SetTimer = (fn: () => void, ms: number) => TimerId
export type ClearTimer = (id: TimerId) => void

export interface WsClientOptions {
  /** Build the socket URL; defaults to `wsUrl(clientId)`. */
  url?: (clientId: string) => string
  /** WebSocket constructor (injectable for tests). */
  factory?: (url: string) => WebSocket
  clientId?: string
  /** Back-off floor/ceiling in ms. */
  minDelayMs?: number
  maxDelayMs?: number
  /** Heartbeat interval in ms (`0` disables). */
  pingIntervalMs?: number
  /** Scheduler (injectable for tests). */
  setTimeout?: SetTimer
  clearTimeout?: ClearTimer
}

function randomClientId(): string {
  return Math.random().toString(36).slice(2, 10)
}

export class WsClient {
  readonly clientId: string
  status: WsStatus = 'idle'
  attempt = 0
  /** Workflow the client is (or wants to be) subscribed to. */
  workflowId: string | null = null

  private socket: WebSocket | null = null
  private readonly messageHandlers = new Set<MessageHandler>()
  private readonly frameHandlers = new Set<FrameHandler>()
  private readonly statusHandlers = new Set<StatusHandler>()
  private reconnectTimer: TimerId | null = null
  private pingTimer: TimerId | null = null
  private wantOpen = false
  private readonly opts: Required<Omit<WsClientOptions, 'clientId'>>

  constructor(options: WsClientOptions = {}) {
    this.clientId = options.clientId ?? randomClientId()
    this.opts = {
      url: options.url ?? ((id) => wsUrl(id)),
      factory: options.factory ?? ((url) => new WebSocket(url)),
      minDelayMs: options.minDelayMs ?? 500,
      maxDelayMs: options.maxDelayMs ?? 10_000,
      pingIntervalMs: options.pingIntervalMs ?? 20_000,
      setTimeout: options.setTimeout ?? ((fn, ms) => globalThis.setTimeout(fn, ms)),
      clearTimeout: options.clearTimeout ?? ((id) => globalThis.clearTimeout(id)),
    }
  }

  get isOpen(): boolean {
    return this.status === 'open'
  }

  onMessage(handler: MessageHandler): () => void {
    this.messageHandlers.add(handler)
    return () => this.messageHandlers.delete(handler)
  }

  onFrame(handler: FrameHandler): () => void {
    this.frameHandlers.add(handler)
    return () => this.frameHandlers.delete(handler)
  }

  onStatus(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler)
    return () => this.statusHandlers.delete(handler)
  }

  /** Open the socket (idempotent); reconnects automatically until `close()`. */
  connect(): void {
    this.wantOpen = true
    if (this.socket && (this.status === 'open' || this.status === 'connecting')) return
    this.open()
  }

  /** Close for good; no reconnection. */
  close(): void {
    this.wantOpen = false
    this.clearTimers()
    const socket = this.socket
    this.socket = null
    if (socket) {
      socket.onopen = socket.onmessage = socket.onclose = socket.onerror = null
      try {
        socket.close()
      } catch {
        // already closed
      }
    }
    this.setStatus('closed')
  }

  /** Subscribe to a workflow's events (re-sent after every reconnect); `null` unsubscribes locally. */
  subscribe(workflowId: string | null): void {
    this.workflowId = workflowId
    if (workflowId && this.isOpen) this.send({ type: 'subscribe', workflow_id: workflowId })
  }

  /** Send a command; returns `false` when the socket is not open. */
  send(command: ClientCommand): boolean {
    if (!this.socket || this.status !== 'open') return false
    this.socket.send(JSON.stringify(command))
    return true
  }

  requestOutput(nodeId: string, port: string): boolean {
    return this.send({ type: 'output.request', node_id: nodeId, port })
  }

  requestPreview(nodeId: string, port: string, viewport: PreviewViewport = {}): boolean {
    return this.send({ type: 'preview.request', node_id: nodeId, port, viewport })
  }

  requestCompute(request: ComputeRequest): boolean {
    return this.send({ type: 'preview.compute', tag: 'editor', ...request })
  }

  // --- internals ------------------------------------------------------------------------------

  private open(): void {
    this.clearTimers()
    this.setStatus(this.attempt === 0 ? 'connecting' : 'reconnecting')
    let socket: WebSocket
    try {
      socket = this.opts.factory(this.opts.url(this.clientId))
    } catch {
      this.scheduleReconnect()
      return
    }
    socket.binaryType = 'arraybuffer'
    this.socket = socket
    socket.onopen = () => {
      if (this.socket !== socket) return
      this.attempt = 0
      this.setStatus('open')
      if (this.workflowId) this.send({ type: 'subscribe', workflow_id: this.workflowId })
      this.schedulePing()
    }
    socket.onmessage = (event: MessageEvent<unknown>) => {
      if (this.socket !== socket) return
      this.dispatch(event.data)
    }
    socket.onclose = () => {
      if (this.socket !== socket) return
      this.socket = null
      this.clearTimers()
      if (this.wantOpen) this.scheduleReconnect()
      else this.setStatus('closed')
    }
    socket.onerror = () => {
      // `onclose` follows every error; nothing to do here.
    }
  }

  private dispatch(data: unknown): void {
    if (data instanceof ArrayBuffer) {
      let frame: DecodedFrame
      try {
        frame = decodeFrame(data)
      } catch {
        return
      }
      for (const handler of this.frameHandlers) handler(frame)
      return
    }
    if (typeof data !== 'string') return
    let payload: unknown
    try {
      payload = JSON.parse(data)
    } catch {
      return
    }
    const message = parseServerMessage(payload)
    if (!message) return
    for (const handler of this.messageHandlers) handler(message)
  }

  private scheduleReconnect(): void {
    this.attempt += 1
    this.setStatus('reconnecting')
    const delay = Math.min(
      this.opts.maxDelayMs,
      this.opts.minDelayMs * 2 ** Math.min(this.attempt - 1, 10),
    )
    this.reconnectTimer = this.opts.setTimeout(() => {
      this.reconnectTimer = null
      if (this.wantOpen) this.open()
    }, delay)
  }

  private schedulePing(): void {
    if (!this.opts.pingIntervalMs) return
    this.pingTimer = this.opts.setTimeout(() => {
      this.pingTimer = null
      if (this.send({ type: 'ping' })) this.schedulePing()
    }, this.opts.pingIntervalMs)
  }

  private clearTimers(): void {
    if (this.reconnectTimer !== null) {
      this.opts.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.pingTimer !== null) {
      this.opts.clearTimeout(this.pingTimer)
      this.pingTimer = null
    }
  }

  private setStatus(status: WsStatus): void {
    if (this.status === status && status !== 'reconnecting') return
    this.status = status
    for (const handler of this.statusHandlers) handler(status, this.attempt)
  }
}
