/**
 * Design §10.2: arrays arrive as typed arrays; a million-point spectrum must never go through
 * `JSON.parse`. The transport is mocked: a fake socket delivers one binary frame.
 */
import { encode } from '@msgpack/msgpack'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { type DecodedFrame, decodeFrame } from '../frames'
import { WsClient } from '../ws'
import { seriesFromFrame } from '@/widgets/spectrumSeries'

function millionPointFrame(n = 1_000_000): ArrayBuffer {
  const wave = new Float64Array(n)
  const flux = new Float64Array(n)
  for (let i = 0; i < n; i += 1) {
    wave[i] = 3000 + i * 0.01
    flux[i] = Math.sin(i / 1000)
  }
  const header = encode({
    node_id: 'load',
    port: 'out',
    type_id: 'astro.Spectrum1D',
    data: { wave_unit: 'Angstrom', flux_unit: 'x', frame: 'observed', z: null },
    arrays: [
      { name: 'flux', dtype: 'f8', shape: [n], offset: 0, nbytes: n * 8 },
      { name: 'wave', dtype: 'f8', shape: [n], offset: n * 8, nbytes: n * 8 },
    ],
  })
  const buffer = new ArrayBuffer(8 + header.byteLength + n * 16)
  const view = new DataView(buffer)
  view.setUint32(0, 1, true)
  view.setUint32(4, header.byteLength, true)
  new Uint8Array(buffer, 8, header.byteLength).set(header)
  new Uint8Array(buffer, 8 + header.byteLength, n * 8).set(new Uint8Array(flux.buffer))
  new Uint8Array(buffer, 8 + header.byteLength + n * 8, n * 8).set(new Uint8Array(wave.buffer))
  return buffer
}

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
    this.onclose?.()
  }
}

describe('million-point transport', () => {
  afterEach(() => vi.restoreAllMocks())

  it('delivers typed arrays through the WebSocket client without JSON.parse', () => {
    const parseSpy = vi.spyOn(JSON, 'parse')
    const client = new WsClient({
      factory: () => new FakeSocket() as unknown as WebSocket,
      url: () => 'ws://test/ws',
      pingIntervalMs: 0,
    })
    const frames: DecodedFrame[] = []
    client.onFrame((frame) => frames.push(frame))
    client.connect()
    const socket = FakeSocket.last as FakeSocket
    socket.onopen?.()
    expect(client.requestOutput('load', 'out')).toBe(true)
    expect(JSON.parse(socket.sent[0] ?? '{}')).toMatchObject({ type: 'output.request' })
    parseSpy.mockClear()

    const buffer = millionPointFrame()
    const start = performance.now()
    socket.onmessage?.({ data: buffer })
    const elapsed = performance.now() - start

    expect(frames).toHaveLength(1)
    const frame = frames[0] as DecodedFrame
    expect(frame.arrays['wave']?.view).toBeInstanceOf(Float64Array)
    expect(frame.arrays['wave']?.view.length).toBe(1_000_000)
    expect(parseSpy).not.toHaveBeenCalled()
    // Decoding is a header decode plus typed-array views (copies only when unaligned).
    expect(elapsed).toBeLessThan(300)

    const series = seriesFromFrame(frame)
    expect(series?.n).toBe(1_000_000)
    expect(series?.wave).toBe(frame.arrays['wave']?.view) // no copy
    expect(parseSpy).not.toHaveBeenCalled()
    client.close()
  })

  it('decodeFrame itself stays clear of JSON.parse', () => {
    const parseSpy = vi.spyOn(JSON, 'parse')
    const frame = decodeFrame(millionPointFrame(200_000))
    expect(frame.header.type_id).toBe('astro.Spectrum1D')
    expect(frame.arrays['flux']?.view.length).toBe(200_000)
    expect(parseSpy).not.toHaveBeenCalled()
  })
})
