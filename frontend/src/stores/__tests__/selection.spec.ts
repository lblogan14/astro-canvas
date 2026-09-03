import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useSelectionStore } from '@/stores/selection'

describe('selection store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('sets, selects, toggles and clears', () => {
    const selection = useSelectionStore()
    expect(selection.isEmpty).toBe(true)
    selection.set(['a', 'b', 'a'], ['e1'])
    expect(selection.nodeIds).toEqual(['a', 'b'])
    expect(selection.edgeIds).toEqual(['e1'])
    expect(selection.primaryNodeId).toBe('b')
    selection.selectNode('c')
    expect(selection.nodeIds).toEqual(['c'])
    expect(selection.edgeIds).toEqual([])
    selection.selectNode('d', true)
    selection.selectNode('d', true)
    expect(selection.nodeIds).toEqual(['c', 'd'])
    selection.toggleNode('c')
    expect(selection.nodeIds).toEqual(['d'])
    selection.toggleNode('c')
    expect(selection.nodeSet.has('c')).toBe(true)
    selection.clear()
    expect(selection.isEmpty).toBe(true)
    expect(selection.primaryNodeId).toBeNull()
  })

  it('prunes ids that no longer exist', () => {
    const selection = useSelectionStore()
    selection.set(['a', 'gone'], ['e1', 'e-gone'])
    selection.prune(
      (id) => id === 'a',
      (id) => id === 'e1',
    )
    expect(selection.nodeIds).toEqual(['a'])
    expect(selection.edgeIds).toEqual(['e1'])
    const nodes = selection.nodeIds
    selection.prune(
      () => true,
      () => true,
    )
    expect(selection.nodeIds).toBe(nodes)
  })
})
