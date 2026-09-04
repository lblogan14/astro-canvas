import { describe, expect, it } from 'vitest'

import { layoutGraph } from '@/canvas/layout'
import type { EdgeDoc, NodeDoc } from '@/api/types'

function node(pos: [number, number], size?: [number, number]): NodeDoc {
  return {
    type: 'core.math.constant',
    version: null,
    title: null,
    pos,
    size: size ?? null,
    params: {},
    linked: [],
    ui: {},
    cost: null,
    disabled: false,
    notes: '',
  }
}

const CHAIN: Record<string, NodeDoc> = {
  a: node([500, 500]),
  b: node([80, 900]),
  c: node([900, 40]),
}
const EDGES: Record<string, EdgeDoc> = {
  e1: { from: ['a', 'out'], to: ['b', 'x'] },
  e2: { from: ['b', 'out'], to: ['c', 'x'] },
}

describe('layoutGraph', () => {
  it('orders a chain left to right from the selection origin', async () => {
    const moves = await layoutGraph(CHAIN, EDGES)
    const at = Object.fromEntries(moves.map((m) => [m.id, m.pos]))
    expect(at['a']?.[0]).toBeLessThan(at['b']?.[0] as number)
    expect(at['b']?.[0]).toBeLessThan(at['c']?.[0] as number)
    // The tidied graph stays anchored at the current top-left corner.
    expect(Math.min(...moves.map((m) => m.pos[0]))).toBe(80)
    expect(Math.min(...moves.map((m) => m.pos[1]))).toBe(40)
  })

  it('lays out downwards when asked', async () => {
    const moves = await layoutGraph(CHAIN, EDGES, { direction: 'DOWN' })
    const at = Object.fromEntries(moves.map((m) => [m.id, m.pos]))
    expect(at['a']?.[1]).toBeLessThan(at['c']?.[1] as number)
  })

  it('restricts itself to the selection and ignores edges leaving it', async () => {
    const moves = await layoutGraph(CHAIN, EDGES, { nodeIds: ['a', 'b'] })
    expect(moves.map((m) => m.id).sort()).toEqual(['a', 'b'])
  })

  it('does nothing for fewer than two nodes', async () => {
    expect(await layoutGraph(CHAIN, EDGES, { nodeIds: ['a'] })).toEqual([])
    expect(await layoutGraph({}, {})).toEqual([])
  })
})
