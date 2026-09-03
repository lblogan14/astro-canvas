import { describe, expect, it, vi } from 'vitest'

// The renderer components import uPlot, which needs `matchMedia` at import time (absent in jsdom).
vi.mock('uplot', () => ({ default: class FakeUPlot {} }))
vi.mock('uplot/dist/uPlot.min.css', () => ({}))

import type { NodeSpec, PortTypeSpec } from '@/api/types'
import {
  EXPANDABLE,
  isPreviewId,
  previewBudget,
  previewComponent,
  rendererFor,
  rendererFromSummary,
} from '../registry'

function typeSpec(renderer: string | null): PortTypeSpec {
  return {
    id: 'astro.X',
    name: 'X',
    color: '#000',
    summary_renderer: renderer,
    compatible_with: [],
    description: '',
    json_schema: {},
    module: '',
    pack: null,
  }
}

describe('preview registry', () => {
  it('maps backend renderer ids and node overrides', () => {
    expect(rendererFor(undefined, typeSpec('spectrum-thumb'), undefined)).toBe('spectrum-thumb')
    expect(rendererFor(undefined, typeSpec('table-grid'), undefined)).toBe('table-head')
    expect(rendererFor(undefined, typeSpec('chip'), undefined)).toBe('kv-tile')
    expect(rendererFor(undefined, typeSpec('type-name'), undefined)).toBe('value-chip')
    expect(rendererFor(undefined, typeSpec('unknown-renderer'), undefined)).toBe('value-chip')
    const spec = { preview: 'figure' } as unknown as NodeSpec
    expect(rendererFor(spec, typeSpec('spectrum-thumb'), undefined)).toBe('figure')
    const bogus = { preview: 'nope' } as unknown as NodeSpec
    expect(rendererFor(bogus, typeSpec('image-thumb'), undefined)).toBe('image-thumb')
  })

  it('guesses from the summary shape', () => {
    expect(rendererFromSummary({ wave: [1], flux: [1] })).toBe('spectrum-thumb')
    const tile = { width: 1, height: 1, step: 1, dtype: 'f4', b64: '', zscale: [0, 1] }
    expect(rendererFromSummary({ tile, shape: [2, 2] })).toBe('image-thumb')
    expect(rendererFromSummary({ tile, shape: [2, 2, 2] })).toBe('cube-thumb')
    expect(rendererFromSummary({ columns: ['a'], head: { a: [1] } })).toBe('table-head')
    expect(rendererFromSummary({ kind: 'plotly', size: 3 })).toBe('figure')
    expect(rendererFromSummary({ type: 'astro.File', data: { path: 'a', size: 1 } })).toBe(
      'file-chip',
    )
    expect(rendererFromSummary({ type: 'astro.Float', data: { value: 1 } })).toBe('value-chip')
    expect(rendererFromSummary({ type: 'astro.EW', data: { W: 1, N: 2 } })).toBe('kv-tile')
    expect(rendererFromSummary({ python_type: 'dict' })).toBe('value-chip')
    expect(rendererFor(undefined, undefined, { wave: [1], flux: [1] })).toBe('spectrum-thumb')
    expect(rendererFor(undefined, undefined, undefined)).toBe('value-chip')
  })

  it('exposes components, budgets and expandability', () => {
    expect(isPreviewId('figure')).toBe(true)
    expect(isPreviewId('x')).toBe(false)
    expect(previewComponent('kv-tile')).toBeTruthy()
    expect(previewBudget('spectrum-thumb', 300)).toBe(600)
    expect(previewBudget('spectrum-thumb', 50)).toBe(200)
    expect(previewBudget('spectrum-thumb', 5000)).toBe(4000)
    expect(previewBudget('image-thumb', 20)).toBe(64)
    expect(previewBudget('cube-thumb', 900)).toBe(512)
    expect(previewBudget('kv-tile', 300)).toBeNull()
    expect(EXPANDABLE.has('table-head')).toBe(true)
    expect(EXPANDABLE.has('value-chip')).toBe(false)
  })
})
