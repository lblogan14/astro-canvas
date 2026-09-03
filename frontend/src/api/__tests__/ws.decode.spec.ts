import { describe, expect, it } from 'vitest'
import { encode } from '@msgpack/msgpack'

import { parseServerMessage } from '@/api/events'
import { FRAME_OUTPUT, ctorFor, decodeFrame } from '@/api/frames'

function frame(header: unknown, buffers: Uint8Array[], msgType = FRAME_OUTPUT): ArrayBuffer {
  const packed = encode(header)
  const total = 8 + packed.byteLength + buffers.reduce((n, b) => n + b.byteLength, 0)
  const out = new Uint8Array(total)
  const view = new DataView(out.buffer)
  view.setUint32(0, msgType, true)
  view.setUint32(4, packed.byteLength, true)
  out.set(packed, 8)
  let offset = 8 + packed.byteLength
  for (const buffer of buffers) {
    out.set(buffer, offset)
    offset += buffer.byteLength
  }
  return out.buffer
}

describe('decodeFrame', () => {
  it('decodes an output frame into typed-array views (copying when unaligned)', () => {
    const wave = new Float64Array([1, 2, 3])
    const flag = new Int32Array([7, -1])
    const raw = new Uint8Array([9, 8])
    const waveBytes = new Uint8Array(wave.buffer)
    const flagBytes = new Uint8Array(flag.buffer)
    const header = {
      node_id: 'n1',
      port: 'out',
      type_id: 'astro.Spectrum1D',
      data: { wave_unit: 'Angstrom' },
      arrays: [
        { name: 'wave', dtype: 'f8', shape: [3], offset: 0, nbytes: 24 },
        { name: 'flag', dtype: 'i4', shape: [2], offset: 24, nbytes: 8 },
        { name: 'blob', dtype: 'bytes', shape: [2], offset: 32, nbytes: 2 },
      ],
    }
    const decoded = decodeFrame(frame(header, [waveBytes, flagBytes, raw]))
    expect(decoded.msgType).toBe(FRAME_OUTPUT)
    expect(decoded.header.node_id).toBe('n1')
    expect(decoded.header.data).toEqual({ wave_unit: 'Angstrom' })
    expect(Array.from(decoded.arrays.wave!.view as Float64Array)).toEqual([1, 2, 3])
    expect(decoded.arrays.wave!.view).toBeInstanceOf(Float64Array)
    expect(Array.from(decoded.arrays.flag!.view as Int32Array)).toEqual([7, -1])
    expect(Array.from(decoded.arrays.blob!.view as Uint8Array)).toEqual([9, 8])
    expect(decoded.arrays.blob!.dtype).toBe('bytes')
  })

  it('maps dtype codes to constructors and falls back to bytes', () => {
    expect(ctorFor('f4')).toBe(Float32Array)
    expect(ctorFor('i8')).toBe(BigInt64Array)
    expect(ctorFor('u2')).toBe(Uint16Array)
    expect(ctorFor('?')).toBe(Uint8Array)
    expect(ctorFor('U8')).toBe(Uint8Array)
  })

  it('rejects malformed frames', () => {
    expect(() => decodeFrame(new ArrayBuffer(4))).toThrow(/too short/)
    const short = new Uint8Array(8)
    new DataView(short.buffer).setUint32(4, 100, true)
    expect(() => decodeFrame(short.buffer)).toThrow(/exceeds/)
    expect(() => decodeFrame(frame({ nope: 1 }, []))).toThrow(/node output/)
    const header = {
      node_id: 'n',
      port: 'p',
      type_id: 't',
      data: {},
      arrays: [{ name: 'a', dtype: 'f8', shape: [1], offset: 0, nbytes: 64 }],
    }
    expect(() => decodeFrame(frame(header, [new Uint8Array(8)]))).toThrow(/exceeds frame length/)
  })
})

describe('parseServerMessage', () => {
  it('accepts known types and rejects everything else', () => {
    expect(parseServerMessage({ type: 'pong', ts: 1 })).toEqual({ type: 'pong', ts: 1 })
    expect(parseServerMessage({ type: 'node.status', node_id: 'a' })?.type).toBe('node.status')
    expect(parseServerMessage({ type: 'nope' })).toBeNull()
    expect(parseServerMessage(null)).toBeNull()
    expect(parseServerMessage('x')).toBeNull()
    expect(parseServerMessage({})).toBeNull()
  })
})
