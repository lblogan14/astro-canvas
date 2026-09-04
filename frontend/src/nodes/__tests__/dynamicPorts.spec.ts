import { describe, expect, it } from 'vitest'

import type { NodeDoc, NodeSpec } from '@/api/types'
import { applyDynamicPorts, declaredPorts, isValidPortName } from '../dynamicPorts'

const CODE_SPEC: NodeSpec = {
  id: 'core.code.python',
  name: 'Python',
  category: 'Code',
  version: '1.0.0',
  cost: 'auto',
  inputs: [],
  params: [],
  outputs: [],
  description: '',
  param_docs: {},
  icon: 'code',
  preview: null,
  editor: 'code',
  pack: 'core',
  module: '',
  deprecated: false,
  experimental: false,
  expand: false,
  fingerprint: false,
  is_async: false,
  dynamic_ports: { inputs: 'inputs', outputs: 'outputs', values: 'values' },
}

const FIXED_SPEC: NodeSpec = {
  ...CODE_SPEC,
  id: 'core.math.constant',
  dynamic_ports: null,
  outputs: [{ name: 'out', type: 'astro.Float', description: '', required: true, lazy: false }],
}

function node(params: Record<string, unknown>): NodeDoc {
  return { type: 'core.code.python', params } as NodeDoc
}

describe('declaredPorts', () => {
  it('reads name and type from each entry', () => {
    expect(
      declaredPorts([
        { name: 'spec', type: 'astro.Spectrum1D' },
        { name: 'z', type: 'astro.Float' },
      ]),
    ).toEqual([
      { name: 'spec', type: 'astro.Spectrum1D', description: '', required: true, lazy: false },
      { name: 'z', type: 'astro.Float', description: '', required: true, lazy: false },
    ])
  })

  it('defaults a missing type to astro.Any', () => {
    expect(declaredPorts([{ name: 'x' }])[0]?.type).toBe('astro.Any')
  })

  it('accepts a bare string as a name', () => {
    expect(declaredPorts(['x'])[0]).toMatchObject({ name: 'x', type: 'astro.Any' })
  })

  it.each([
    ['a half-typed row', [{ name: '' }]],
    ['a name that is not an identifier', [{ name: '2fast' }]],
    ['a name with a space', [{ name: 'my port' }]],
    ['a row with no name at all', [{ type: 'astro.Float' }]],
    ['a value that is not a list', 'nope'],
    ['nothing', undefined],
  ])('drops %s rather than throwing', (_case, value) => {
    expect(declaredPorts(value)).toEqual([])
  })

  it('keeps the first of two rows with the same name', () => {
    const ports = declaredPorts([{ name: 'a', type: 'astro.Int' }, { name: 'a' }])
    expect(ports).toHaveLength(1)
    expect(ports[0]?.type).toBe('astro.Int')
  })
})

describe('isValidPortName', () => {
  it.each(['a', 'spec', '_x', 'z1'])('accepts %s', (name) => {
    expect(isValidPortName(name)).toBe(true)
  })
  it.each(['', '1a', 'a b', 'a-b', 'a.b'])('rejects %s', (name) => {
    expect(isValidPortName(name)).toBe(false)
  })
})

describe('applyDynamicPorts', () => {
  it('merges the declared ports into the spec', () => {
    const spec = applyDynamicPorts(
      CODE_SPEC,
      node({
        inputs: [{ name: 'spec', type: 'astro.Spectrum1D' }],
        outputs: [{ name: 'ew', type: 'astro.Float' }],
      }),
    )
    expect(spec.inputs.map((p) => [p.name, p.type])).toEqual([['spec', 'astro.Spectrum1D']])
    expect(spec.outputs.map((p) => [p.name, p.type])).toEqual([['ew', 'astro.Float']])
  })

  it('leaves a node with fixed ports untouched, by identity', () => {
    expect(applyDynamicPorts(FIXED_SPEC, node({}))).toBe(FIXED_SPEC)
  })

  it('yields no ports for a node that declares none yet', () => {
    const spec = applyDynamicPorts(CODE_SPEC, node({}))
    expect(spec.inputs).toEqual([])
    expect(spec.outputs).toEqual([])
  })

  it('returns the spec unchanged when the declaration names no params', () => {
    const spec: NodeSpec = {
      ...CODE_SPEC,
      dynamic_ports: { inputs: null, outputs: null, values: 'values' },
    }
    expect(applyDynamicPorts(spec, node({}))).toBe(spec)
  })

  it('handles a missing node', () => {
    expect(applyDynamicPorts(CODE_SPEC, undefined).inputs).toEqual([])
  })
})
