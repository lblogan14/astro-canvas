import { describe, expect, it } from 'vitest'

import {
  checkConnection,
  descendants,
  incomingEdge,
  inputType,
  isTypeCompatible,
  outputType,
} from '@/canvas/compat'
import { portStyle, typeLabel } from '@/canvas/ports'
import { SPEC_INDEX, TYPE_INDEX, mathChain } from '@/stores/__tests__/fixtures'

describe('isTypeCompatible', () => {
  it('mirrors the SDK rules', () => {
    expect(isTypeCompatible('astro.Float', 'astro.Float', TYPE_INDEX)).toBe(true)
    expect(isTypeCompatible('astro.Float', 'astro.Any', TYPE_INDEX)).toBe(true)
    expect(isTypeCompatible('astro.Float', 'astro.Json', TYPE_INDEX)).toBe(true)
    expect(isTypeCompatible('astro.Spectrum1D', 'astro.Json', TYPE_INDEX)).toBe(false)
    expect(isTypeCompatible('astro.Spectrum1D', 'astro.SpectrumCollection', TYPE_INDEX)).toBe(true)
    expect(isTypeCompatible('astro.SpectrumCollection', 'astro.Spectrum1D', TYPE_INDEX)).toBe(false)
    expect(isTypeCompatible('pack.Unknown', 'astro.Float', TYPE_INDEX)).toBe(false)
  })
})

describe('checkConnection', () => {
  const doc = mathChain()
  const graph = {
    nodes: doc.nodes!,
    edges: doc.edges!,
    specs: SPEC_INDEX,
    types: TYPE_INDEX,
  }

  it('accepts a valid new connection to a linked param', () => {
    const nodes = { ...graph.nodes, sum: { ...graph.nodes.sum!, linked: ['x', 'y', 'z'] } }
    expect(
      checkConnection(
        { ...graph, nodes },
        { source: 'c', sourcePort: 'out', target: 'sum', targetPort: 'z' },
      ),
    ).toEqual({ ok: true, sourceType: 'astro.Float', targetType: 'astro.Float' })
  })

  it('treats linkable params as ports even before they are linked', () => {
    expect(
      checkConnection(graph, { source: 'c', sourcePort: 'out', target: 'sum', targetPort: 'z' }).ok,
    ).toBe(true)
    expect(inputType(SPEC_INDEX['core.math.expr']!, graph.nodes.sum!, 'nope')).toBeUndefined()
    expect(outputType(SPEC_INDEX['core.math.expr']!, 'nope')).toBeUndefined()
  })

  it('rejects self, unknown nodes and ports, occupied inputs, mismatches and cycles', () => {
    const q = (source: string, sourcePort: string, target: string, targetPort: string) =>
      checkConnection(graph, { source, sourcePort, target, targetPort })
    expect(q('c', 'out', 'c', 'x')).toEqual({ ok: false, reason: 'self' })
    expect(q('zz', 'out', 'c', 'x')).toEqual({ ok: false, reason: 'unknown_node' })
    expect(q('c', 'nope', 'sq', 'x')).toEqual({ ok: false, reason: 'unknown_port' })
    expect(q('sum', 'out', 'sq', 'x')).toMatchObject({ ok: false, reason: 'multiple_inputs' })
    // re-validating an edge that already exists is idempotent
    expect(q('c', 'out', 'sq', 'x').ok).toBe(true)
    expect(q('sum', 'out', 'c', 'value')).toMatchObject({ ok: false, reason: 'cycle' })
    const withSpec = {
      ...graph,
      nodes: {
        ...graph.nodes,
        s: { type: 'test.spec.make', params: {}, disabled: false, notes: '' },
        crop: { type: 'core.spec.crop', params: {}, disabled: false, notes: '' },
        ghost: { type: 'pack.missing', params: {}, disabled: false, notes: '' },
      },
    }
    expect(
      checkConnection(withSpec, { source: 's', sourcePort: 'out', target: 'sq', targetPort: 'y' }),
    ).toMatchObject({
      ok: false,
      reason: 'type_mismatch',
      sourceType: 'astro.Spectrum1D',
      targetType: 'astro.Float',
    })
    expect(
      checkConnection(withSpec, {
        source: 's',
        sourcePort: 'out',
        target: 'crop',
        targetPort: 'spec',
      }).ok,
    ).toBe(true)
    expect(
      checkConnection(withSpec, {
        source: 'ghost',
        sourcePort: 'out',
        target: 'crop',
        targetPort: 'spec',
      }),
    ).toEqual({ ok: false, reason: 'unknown_node' })
  })

  it('lets a reconnection ignore the edge being moved', () => {
    expect(
      checkConnection(
        graph,
        { source: 'c', sourcePort: 'out', target: 'sq', targetPort: 'x' },
        'e1',
      ).ok,
    ).toBe(true)
    expect(incomingEdge(graph.edges, 'sq', 'x')?.[0]).toBe('e1')
    expect(incomingEdge(graph.edges, 'sq', 'y')).toBeUndefined()
  })

  it('computes descendants', () => {
    expect([...descendants(graph.edges, 'c')].sort()).toEqual(['sq', 'sum'])
    expect(descendants(graph.edges, 'sum').size).toBe(0)
    expect(descendants({}, 'c').size).toBe(0)
  })
})

describe('port styles', () => {
  it('assigns Okabe–Ito colours and glyphs, stable for unknown types', () => {
    expect(portStyle('astro.Spectrum1D')).toEqual({ color: '#0072B2', glyph: 'diamond' })
    expect(portStyle('astro.Float').glyph).toBe('circle')
    const custom = portStyle('pack.Custom')
    expect(portStyle('pack.Custom')).toEqual(custom)
    expect(custom.color).toMatch(/^#/)
    expect(typeLabel('astro.Spectrum1D')).toBe('Spectrum1D')
    expect(typeLabel('Plain')).toBe('Plain')
  })
})
