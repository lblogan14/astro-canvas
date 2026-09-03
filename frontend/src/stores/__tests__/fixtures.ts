import type { NodeSpec, ParamSpec, PortTypeSpec, WorkflowDoc } from '@/api/types'

function param(name: string, extra: Partial<ParamSpec> = {}): ParamSpec {
  return {
    name,
    label: name.toUpperCase(),
    description: '',
    json_schema: { type: 'number', default: 0 },
    required: false,
    default: 0,
    widget: null,
    unit: null,
    step: null,
    advanced: false,
    linkable: true,
    link_type: 'astro.Float',
    ...extra,
  }
}

function spec(id: string, extra: Partial<NodeSpec>): NodeSpec {
  return {
    id,
    name: id.split('.').pop() ?? id,
    category: 'Math',
    description: '',
    version: '1',
    pack: 'core',
    cost: 'cheap',
    deprecated: false,
    inputs: [],
    outputs: [],
    params: [],
    ...extra,
  } as NodeSpec
}

export const SPECS: NodeSpec[] = [
  spec('core.math.constant', {
    outputs: [{ name: 'out', type: 'astro.Float', description: '', lazy: false, required: true }],
    params: [param('value', { widget: 'number' })],
  }),
  spec('core.math.expr', {
    outputs: [{ name: 'out', type: 'astro.Float', description: '', lazy: false, required: true }],
    params: [
      param('expression', {
        json_schema: { type: 'string', default: 'x' },
        default: 'x',
        link_type: 'astro.Str',
        widget: 'code',
      }),
      param('x'),
      param('y'),
      param('z', { advanced: true }),
    ],
  }),
  spec('core.note.markdown', {
    category: 'Utilities',
    params: [
      param('text', {
        json_schema: { type: 'string', default: '' },
        default: '',
        link_type: 'astro.Str',
        widget: 'markdown',
      }),
    ],
  }),
  spec('test.spec.make', {
    category: 'Spectra/Test',
    cost: 'expensive',
    outputs: [
      { name: 'out', type: 'astro.Spectrum1D', description: '', lazy: false, required: true },
    ],
    params: [param('n', { json_schema: { type: 'integer', default: 100 }, default: 100 })],
  }),
  spec('core.spec.crop', {
    category: 'Spectra/Transform',
    inputs: [
      { name: 'spec', type: 'astro.Spectrum1D', description: '', lazy: false, required: true },
    ],
    outputs: [
      { name: 'out', type: 'astro.Spectrum1D', description: '', lazy: false, required: true },
    ],
    params: [
      param('lo', { required: true, default: null }),
      param('hi', { required: true, default: null }),
    ],
  }),
  spec('core.list.collect', {
    category: 'Lists',
    inputs: [
      { name: 'a', type: 'astro.Spectrum1D', description: '', lazy: false, required: false },
      {
        name: 'b',
        type: 'astro.SpectrumCollection',
        description: '',
        lazy: false,
        required: false,
      },
      { name: 'any', type: 'astro.Any', description: '', lazy: false, required: false },
      { name: 'json', type: 'astro.Json', description: '', lazy: false, required: false },
    ],
    outputs: [
      {
        name: 'out',
        type: 'astro.SpectrumCollection',
        description: '',
        lazy: false,
        required: true,
      },
    ],
  }),
]

function type(id: string, compatible: string[] = []): PortTypeSpec {
  return {
    id,
    name: id.split('.').pop() ?? id,
    color: '#888888',
    summary_renderer: 'chip',
    compatible_with: compatible,
    description: '',
    json_schema: {},
    module: 'test',
    pack: 'core',
  } as PortTypeSpec
}

export const TYPES: PortTypeSpec[] = [
  type('astro.Float'),
  type('astro.Int'),
  type('astro.Str'),
  type('astro.Bool'),
  type('astro.Json'),
  type('astro.Any'),
  type('astro.Spectrum1D', ['astro.SpectrumCollection']),
  type('astro.SpectrumCollection'),
]

export const SPEC_INDEX: Record<string, NodeSpec> = Object.fromEntries(SPECS.map((s) => [s.id, s]))
export const TYPE_INDEX: Record<string, PortTypeSpec> = Object.fromEntries(
  TYPES.map((t) => [t.id, t]),
)

/** The `math_chain.json` fixture the backend ships, as the server returns it. */
export function mathChain(): WorkflowDoc {
  return {
    format: 'astro-canvas/workflow',
    version: 1,
    id: 'sample-math-chain',
    name: 'Math chain',
    description: 'constant -> expr -> expr, with a note; every node is cheap so it auto-runs.',
    nodes: {
      c: {
        type: 'core.math.constant',
        version: null,
        title: 'Two',
        pos: [80, 80],
        size: null,
        params: { value: 2.0 },
        linked: [],
        ui: {},
        cost: null,
        disabled: false,
        notes: '',
      },
      sq: {
        type: 'core.math.expr',
        version: null,
        title: 'Square',
        pos: [360, 80],
        size: null,
        params: { expression: 'x ** 2' },
        linked: ['x'],
        ui: {},
        cost: null,
        disabled: false,
        notes: '',
      },
      sum: {
        type: 'core.math.expr',
        version: null,
        title: 'Sum',
        pos: [640, 80],
        size: null,
        params: { expression: 'x + y + z', z: 1.0 },
        linked: ['x', 'y'],
        ui: {},
        cost: null,
        disabled: false,
        notes: '',
      },
      note: {
        type: 'core.note.markdown',
        version: null,
        title: null,
        pos: [80, 300],
        size: null,
        params: { text: '# Sample\nA tiny reactive chain.' },
        linked: [],
        ui: {},
        cost: null,
        disabled: false,
        notes: '',
      },
    },
    edges: {
      e1: { from: ['c', 'out'], to: ['sq', 'x'] },
      e2: { from: ['sq', 'out'], to: ['sum', 'x'] },
      e3: { from: ['c', 'out'], to: ['sum', 'y'] },
    },
    groups: {},
    subgraphs: {},
    promoted: [],
    views: [],
    layouts: {},
    requires: {},
    meta: { tags: ['sample'], created: '2026-09-02T00:00:00', modified: '2026-09-02T00:00:00' },
  }
}
