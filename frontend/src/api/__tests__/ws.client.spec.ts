import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ServerMessage } from '@/api/events'
import { type WsStatus, WsClient } from '@/api/ws'

class FakeSocket {
  static instances: FakeSocket[] = []
  binaryType = 'blob'
  onopen: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  sent: string[] = []
  closed = false

  constructor(public readonly url: string) {
    FakeSocket.instances.push(this)
  }

  send(data: string): void {
    this.sent.push(data)
  }

  close(): void {
    this.closed = true
  }

  open(): void {
    this.onopen?.()
  }

  message(data: unknown): void {
    this.onmessage?.({ data })
  }

  drop(): void {
    this.onclose?.()
  }
}

function make(overrides: Partial<ConstructorParameters<typeof WsClient>[0]> = {}) {
  return new WsClient({
    url: (id) => `ws://test/ws?client_id=${id}`,
    factory: (url) => new FakeSocket(url) as unknown as WebSocket,
    minDelayMs: 100,
    maxDelayMs: 1000,
    pingIntervalMs: 500,
    clientId: 'abc',
    ...overrides,
  })
}

describe('WsClient', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    FakeSocket.instances = []
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('connects, re-sends the subscription after (re)connecting and pings', () => {
    const client = make()
    const statuses: WsStatus[] = []
    client.onStatus((s) => statuses.push(s))
    client.subscribe('wf1')
    expect(client.send({ type: 'ping' })).toBe(false)
    client.connect()
    client.connect() // idempotent
    expect(FakeSocket.instances).toHaveLength(1)
    const socket = FakeSocket.instances[0]!
    expect(socket.url).toBe('ws://test/ws?client_id=abc')
    expect(socket.binaryType).toBe('arraybuffer')
    socket.open()
    expect(client.isOpen).toBe(true)
    expect(socket.sent).toEqual([JSON.stringify({ type: 'subscribe', workflow_id: 'wf1' })])
    vi.advanceTimersByTime(500)
    expect(JSON.parse(socket.sent[1]!)).toEqual({ type: 'ping' })
    client.subscribe('wf2')
    expect(JSON.parse(socket.sent[2]!)).toEqual({ type: 'subscribe', workflow_id: 'wf2' })

    socket.drop()
    expect(client.status).toBe('reconnecting')
    vi.advanceTimersByTime(100)
    expect(FakeSocket.instances).toHaveLength(2)
    const second = FakeSocket.instances[1]!
    second.open()
    expect(JSON.parse(second.sent[0]!)).toEqual({ type: 'subscribe', workflow_id: 'wf2' })
    expect(statuses).toEqual(['connecting', 'open', 'reconnecting', 'reconnecting', 'open'])
  })

  it('backs off exponentially up to the ceiling', () => {
    const client = make()
    client.connect()
    for (let i = 0; i < 6; i += 1) {
      FakeSocket.instances.at(-1)!.drop()
      const before = FakeSocket.instances.length
      vi.advanceTimersByTime(Math.min(1000, 100 * 2 ** i) - 1)
      expect(FakeSocket.instances).toHaveLength(before)
      vi.advanceTimersByTime(1)
      expect(FakeSocket.instances).toHaveLength(before + 1)
    }
    expect(client.attempt).toBe(6)
  })

  it('dispatches JSON messages and binary frames, ignoring garbage', () => {
    const client = make()
    const messages: ServerMessage[] = []
    const frames: unknown[] = []
    const off = client.onMessage((m) => messages.push(m))
    client.onFrame((f) => frames.push(f))
    client.connect()
    const socket = FakeSocket.instances[0]!
    socket.open()
    socket.message(JSON.stringify({ type: 'pong', ts: 1 }))
    socket.message('not json')
    socket.message(JSON.stringify({ type: 'unknown' }))
    socket.message(123)
    socket.message(new ArrayBuffer(2)) // too short → ignored
    expect(messages).toEqual([{ type: 'pong', ts: 1 }])
    expect(frames).toEqual([])
    off()
    socket.message(JSON.stringify({ type: 'pong', ts: 2 }))
    expect(messages).toHaveLength(1)
  })

  it('close() stops reconnecting and ignores late socket events', () => {
    const client = make()
    client.connect()
    const socket = FakeSocket.instances[0]!
    socket.open()
    client.close()
    expect(socket.closed).toBe(true)
    expect(client.status).toBe('closed')
    vi.advanceTimersByTime(5000)
    expect(FakeSocket.instances).toHaveLength(1)
    expect(client.requestOutput('n', 'p')).toBe(false)
    expect(client.requestPreview('n', 'p')).toBe(false)
  })

  it('sends preview/output requests when open and reschedules when the factory throws', () => {
    const client = make()
    client.connect()
    const socket = FakeSocket.instances[0]!
    socket.open()
    expect(client.requestOutput('n1', 'out')).toBe(true)
    expect(client.requestPreview('n1', 'out', { lo: 1, hi: 2, n_out: 10 })).toBe(true)
    expect(JSON.parse(socket.sent.at(-1)!)).toEqual({
      type: 'preview.request',
      node_id: 'n1',
      port: 'out',
      viewport: { lo: 1, hi: 2, n_out: 10 },
    })
    const failing = make({
      factory: () => {
        throw new Error('no WebSocket')
      },
    })
    failing.connect()
    expect(failing.status).toBe('reconnecting')
    expect(failing.attempt).toBe(1)
  })
})
