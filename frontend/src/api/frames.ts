/**
 * Binary frames from `/ws` (`engine/events.py: encode_frame / output_frame`):
 * `u32 msg_type | u32 header_len | msgpack header | buffers` (little-endian header words).
 * Arrays are C-contiguous little-endian buffers described by `header.arrays`; this module builds
 * typed-array views over the payload without copying.
 */
import { decode } from '@msgpack/msgpack'

export const FRAME_OUTPUT = 1

export interface ArrayDescriptor {
  name: string
  /** numpy `dtype.str` without the byte-order prefix (`f8`, `i8`, `u1`, `?`, `bytes`, `U…`). */
  dtype: string
  shape: number[]
  offset: number
  nbytes: number
}

export interface OutputFrameHeader {
  node_id: string
  port: string
  type_id: string
  /** JSON-safe remainder of the value (arrays removed). */
  data: Record<string, unknown>
  arrays: ArrayDescriptor[]
}

export type TypedArray =
  | Float64Array
  | Float32Array
  | Int8Array
  | Int16Array
  | Int32Array
  | BigInt64Array
  | Uint8Array
  | Uint16Array
  | Uint32Array
  | BigUint64Array

export interface DecodedArray {
  dtype: string
  shape: number[]
  /** Typed view for numeric dtypes; raw bytes for `bytes`, booleans and strings. */
  view: TypedArray
}

export interface DecodedFrame {
  msgType: number
  header: OutputFrameHeader
  arrays: Record<string, DecodedArray>
}

const HEADER_BYTES = 8

type TypedArrayCtor = {
  new (buffer: ArrayBufferLike, byteOffset: number, length: number): TypedArray
  readonly BYTES_PER_ELEMENT: number
}

const DTYPE_CTORS: Record<string, TypedArrayCtor> = {
  f8: Float64Array,
  f4: Float32Array,
  i1: Int8Array,
  i2: Int16Array,
  i4: Int32Array,
  i8: BigInt64Array,
  u1: Uint8Array,
  u2: Uint16Array,
  u4: Uint32Array,
  u8: BigUint64Array,
}

/** Typed-array constructor for a numpy dtype code, or `Uint8Array` for raw/bool/str data. */
export function ctorFor(dtype: string): TypedArrayCtor {
  return DTYPE_CTORS[dtype] ?? Uint8Array
}

function isHeader(value: unknown): value is OutputFrameHeader {
  if (typeof value !== 'object' || value === null) return false
  const header = value as Partial<OutputFrameHeader>
  return typeof header.node_id === 'string' && Array.isArray(header.arrays)
}

/** Decode one binary WebSocket frame into its header and typed-array views. */
export function decodeFrame(buffer: ArrayBuffer): DecodedFrame {
  if (buffer.byteLength < HEADER_BYTES) throw new Error('frame too short')
  const words = new DataView(buffer)
  const msgType = words.getUint32(0, true)
  const headerLen = words.getUint32(4, true)
  const payloadStart = HEADER_BYTES + headerLen
  if (payloadStart > buffer.byteLength) throw new Error('frame header exceeds frame length')
  const header = decode(new Uint8Array(buffer, HEADER_BYTES, headerLen))
  if (!isHeader(header)) throw new Error('frame header must describe a node output')
  const arrays: Record<string, DecodedArray> = {}
  for (const desc of header.arrays) {
    const start = payloadStart + desc.offset
    if (start + desc.nbytes > buffer.byteLength) {
      throw new Error(`array ${desc.name} exceeds frame length`)
    }
    const ctor = ctorFor(desc.dtype)
    const length = Math.floor(desc.nbytes / ctor.BYTES_PER_ELEMENT)
    // Typed arrays need aligned offsets; msgpack headers make that unlikely, so copy when needed.
    const aligned = start % ctor.BYTES_PER_ELEMENT === 0
    const source = aligned ? buffer : buffer.slice(start, start + desc.nbytes)
    const view = new ctor(source, aligned ? start : 0, length)
    arrays[desc.name] = { dtype: desc.dtype, shape: desc.shape, view }
  }
  return { msgType, header, arrays }
}
