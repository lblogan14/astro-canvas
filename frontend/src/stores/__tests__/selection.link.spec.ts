import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import {
  axisName,
  fractionOf,
  intersects,
  rowAxis,
  rowsInRange,
  upstreamNodes,
  valueAt,
  valuesOfRows,
  xDomain,
} from '@/modes/linked'
import { useLinkedStore } from '@/stores/linked'
import { mathChain } from './fixtures'

const EDGES = mathChain().edges!

describe('link groups', () => {
  it('walks the upstream closure of a node', () => {
    expect([...upstreamNodes('sum', EDGES)].sort()).toEqual(['c', 'sq', 'sum'])
    expect([...upstreamNodes('sq', EDGES)].sort()).toEqual(['c', 'sq'])
    expect([...upstreamNodes('c', EDGES)]).toEqual(['c'])
    // A node the document does not mention is its own group.
    expect([...upstreamNodes('ghost', EDGES)]).toEqual(['ghost'])
  })

  it('links two views that share an upstream node', () => {
    const a = upstreamNodes('sq', EDGES)
    const b = upstreamNodes('sum', EDGES)
    expect(intersects(a, b)).toBe(true)
    expect(intersects(upstreamNodes('note', EDGES), a)).toBe(false)
  })
})

describe('reading axes out of summaries', () => {
  it('takes the x domain from range, wave or z', () => {
    expect(xDomain({ range: [1200, 1300] })).toEqual([1200, 1300])
    expect(xDomain({ wave: [3, 1, 2] })).toEqual([1, 3])
    expect(xDomain({ z: [0.1, 0.5, 0.3] })).toEqual([0.1, 0.5])
    expect(xDomain({ range: [5, 5] })).toBeNull()
    expect(xDomain({ nothing: true })).toBeNull()
  })

  it('names the axis after the array the summary carries', () => {
    expect(axisName({ wave: [1, 2] })).toBe('wave')
    expect(axisName({ z: [0.1] })).toBe('z')
    expect(axisName({ range: [0, 1] })).toBe('x')
  })

  it('prefers an axis-shaped column of a table', () => {
    const summary = {
      columns: ['name', 'wave', 'flux'],
      head: { name: ['a'], wave: [1215.7], flux: [2] },
    }
    expect(rowAxis(summary)?.column).toBe('wave')
    // With no axis-shaped name the first numeric column wins.
    expect(rowAxis({ columns: ['name', 'flux'], head: { name: ['a'], flux: [2] } })?.column).toBe(
      'flux',
    )
    expect(rowAxis({ columns: ['name'], head: { name: ['a'] } })).toBeNull()
  })

  it('reads the row-object shape the candidate tables use', () => {
    const summary = {
      rows: [
        { index: 0, z: 0.348 },
        { index: 1, z: 1.2 },
      ],
      accepted: 0,
    }
    expect(rowAxis(summary)).toEqual({ column: 'z', values: [0.348, 1.2] })
  })

  it('maps a range onto the rows inside it, and back', () => {
    const summary = {
      columns: ['wave', 'flux'],
      head: { wave: [1200, 1215.7, 1250, 1300], flux: [1, 2, 3, 4] },
    }
    expect(rowsInRange(summary, 1210, 1260)).toEqual({ column: 'wave', rows: [1, 2] })
    // Reversed bounds behave the same.
    expect(rowsInRange(summary, 1260, 1210)?.rows).toEqual([1, 2])
    expect(valuesOfRows(summary, [1, 3])).toEqual([1215.7, 1300])
    expect(rowsInRange({ nothing: true }, 0, 1)).toBeNull()
  })

  it('maps pixels to data and back', () => {
    expect(fractionOf(1250, [1200, 1300])).toBeCloseTo(0.5)
    expect(fractionOf(900, [1200, 1300])).toBe(0)
    expect(valueAt(0.25, [1200, 1300])).toBe(1225)
    expect(valueAt(2, [1200, 1300])).toBe(1300)
  })
})

describe('linked selection store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('publishes a range to the views sharing an upstream node', () => {
    const links = useLinkedStore()
    links.setRange('curve', upstreamNodes('sq', EDGES), 'wave', 1300, 1200)

    expect(links.selection).toEqual({ kind: 'range', axis: 'wave', lo: 1200, hi: 1300 })
    expect(links.isSource('curve')).toBe(true)
    // A table fed by the same spectrum sees it; an unrelated node does not.
    expect(links.selectionFor(upstreamNodes('sum', EDGES))?.kind).toBe('range')
    expect(links.selectionFor(upstreamNodes('note', EDGES))).toBeNull()
    expect(links.linked(['note'])).toBe(false)
  })

  it('publishes row selections with their axis values', () => {
    const links = useLinkedStore()
    links.setRows('table', ['sum', 'c'], [1, 2], [1215.7, 1250], 'wave')
    const selection = links.selectionFor(['c'])
    expect(selection).toEqual({
      kind: 'rows',
      rows: [1, 2],
      values: [1215.7, 1250],
      column: 'wave',
    })
    expect(links.isActive).toBe(true)
  })

  it('an empty or degenerate selection clears instead of publishing', () => {
    const links = useLinkedStore()
    links.setRange('curve', ['c'], 'wave', 1200, 1300)
    links.setRange('curve', ['c'], 'wave', 1200, 1200)
    expect(links.selection).toBeNull()

    links.setRows('table', ['c'], [0])
    links.setRows('table', ['c'], [])
    expect(links.selection).toBeNull()
    expect(links.isActive).toBe(false)
    expect(links.source).toBeNull()
  })
})
