import { describe, expect, it } from 'vitest'

import { CLIPBOARD_FORMAT, copySelection, parseClipboard, preparePaste } from '@/canvas/clipboard'
import { mathChain } from '@/stores/__tests__/fixtures'

describe('clipboard', () => {
  const doc = mathChain()

  it('copies nodes with internal edges and the bounding origin', () => {
    const payload = copySelection(doc.nodes!, doc.edges!, ['sq', 'sum', 'missing'])
    expect(payload).not.toBeNull()
    expect(Object.keys(payload!.nodes)).toEqual(['sq', 'sum'])
    expect(Object.keys(payload!.edges)).toEqual(['e2'])
    expect(payload!.origin).toEqual([360, 80])
    expect(copySelection(doc.nodes!, doc.edges!, [])).toBeNull()
    // copies are detached from the document
    payload!.nodes.sq!.title = 'changed'
    expect(doc.nodes!.sq!.title).toBe('Square')
  })

  it('round-trips through text and rejects foreign payloads', () => {
    const payload = copySelection(doc.nodes!, doc.edges!, ['c'])!
    expect(parseClipboard(JSON.stringify(payload))).toEqual(payload)
    expect(parseClipboard('{"format":"other"}')).toBeNull()
    expect(parseClipboard('not json')).toBeNull()
    expect(
      parseClipboard(JSON.stringify({ format: CLIPBOARD_FORMAT, nodes: { a: doc.nodes!.c } })),
    ).toMatchObject({ edges: {}, origin: [0, 0] })
  })

  it('re-keys pasted nodes, keeps offsets and remaps edges', () => {
    const payload = copySelection(doc.nodes!, doc.edges!, ['c', 'sq'])!
    const taken = new Set(Object.keys(doc.nodes!))
    const result = preparePaste(payload, (id) => taken.has(id), { at: [0, 0] })
    const ids = Object.keys(result.nodes)
    expect(ids).toHaveLength(2)
    expect(ids.every((id) => !taken.has(id))).toBe(true)
    expect(result.nodes[result.idMap.c!]!.pos).toEqual([0, 0])
    expect(result.nodes[result.idMap.sq!]!.pos).toEqual([280, 0])
    const [edge] = Object.values(result.edges)
    expect(edge).toEqual({ from: [result.idMap.c, 'out'], to: [result.idMap.sq, 'x'] })
    const shifted = preparePaste(payload, () => false)
    expect(shifted.nodes[shifted.idMap.c!]!.pos).toEqual([120, 120])
    const custom = preparePaste(payload, () => false, { offset: [0, 10] })
    expect(custom.nodes[custom.idMap.c!]!.pos).toEqual([80, 90])
  })

  it('drops edges whose endpoints are missing from the payload', () => {
    const payload = copySelection(doc.nodes!, doc.edges!, ['c'])!
    payload.edges.bogus = { from: ['c', 'out'], to: ['ghost', 'x'] }
    const result = preparePaste(payload, () => false)
    expect(Object.keys(result.edges)).toHaveLength(0)
  })
})
