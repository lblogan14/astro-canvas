import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { collapseSelection, expandInstance, subgraphSpec } from '@/canvas/subgraph'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useWorkflowStore } from '@/stores/workflow'
import { SPECS, SPEC_INDEX, TYPES, mathChain } from './fixtures'

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return { ...original, api: { putWorkflow: vi.fn<typeof original.api.putWorkflow>() } }
})

function setup() {
  setActivePinia(createPinia())
  const schema = useNodesSchemaStore()
  schema.specs = SPECS
  schema.types = TYPES
  schema.status = 'ready'
  const workflow = useWorkflowStore()
  workflow.autosaveEnabled = false
  workflow.load(mathChain())
  return workflow
}

describe('collapseSelection', () => {
  it('turns boundary edges into named ports and keeps inner edges inside', () => {
    const workflow = setup()
    const result = collapseSelection(workflow.nodes, workflow.edges, ['sq', 'sum'], 'sg1')
    expect(result).not.toBeNull()
    const { subgraph, edges, removed } = result!
    expect(Object.keys(subgraph.nodes ?? {}).sort()).toEqual(['sq', 'sum'])
    // c -> sq.x and c -> sum.y cross the boundary; sq -> sum is internal.
    expect(subgraph.inputs).toEqual([
      { name: 'x', node: 'sq', port: 'x' },
      { name: 'y', node: 'sum', port: 'y' },
    ])
    expect(Object.keys(subgraph.edges ?? {})).toHaveLength(1)
    expect(removed).toEqual(['e2'])
    const rewired = Object.values(edges)
    expect(rewired.every((edge) => edge.to[0] === 'sg1' || edge.from[0] === 'sg1')).toBe(true)
  })

  it('gives two consumers of the same inner output one shared port', () => {
    const workflow = setup()
    // `c.out` feeds both sq.x and sum.y, so collapsing it yields a single named output.
    const result = collapseSelection(workflow.nodes, workflow.edges, ['c'], 'sg1')!
    expect(result.subgraph.outputs).toEqual([{ name: 'out', node: 'c', port: 'out' }])
    expect(Object.keys(result.edges)).toHaveLength(2)
    expect(Object.values(result.edges).every((e) => e.from[0] === 'sg1')).toBe(true)
  })

  it('stores inner positions relative to the instance', () => {
    const workflow = setup()
    const result = collapseSelection(workflow.nodes, workflow.edges, ['sq', 'sum'], 'sg1')!
    expect(result.instance.pos).toEqual([500, 80])
    expect(result.subgraph.nodes?.['sq']?.pos).toEqual([-140, 0])
    expect(result.subgraph.nodes?.['sum']?.pos).toEqual([140, 0])
  })
})

describe('subgraphSpec', () => {
  it('types the boundary ports from the inner nodes and exposes promoted params', () => {
    const workflow = setup()
    // Collapsing `sq` alone leaves an input (from c) and an output (to sum).
    const { subgraph } = collapseSelection(workflow.nodes, workflow.edges, ['sq'], 'sg1')!
    subgraph.promoted = [{ node: 'sq', param: 'z', label: 'Offset', group: null, order: 0 }]
    const spec = subgraphSpec('sub1', subgraph, SPEC_INDEX)
    expect(spec.id).toBe('subgraph:sub1')
    expect(spec.inputs.map((p) => [p.name, p.type])).toEqual([['x', 'astro.Float']])
    expect(spec.outputs.map((p) => [p.name, p.type])).toEqual([['out', 'astro.Float']])
    expect(spec.params.map((p) => [p.name, p.label])).toEqual([['sq.z', 'Offset']])
    expect(spec.params[0]?.default).toBe(0)
  })
})

describe('workflow store: subgraphs', () => {
  beforeEach(() => vi.useRealTimers())

  it('collapses a selection into one instance node in a single undo entry', () => {
    const workflow = setup()
    const before = workflow.undoStack.length
    const instance = workflow.collapseToSubgraph(['sq', 'sum'], 'Measure')
    expect(instance).not.toBeNull()
    expect(Object.keys(workflow.nodes).sort()).toEqual([instance!, 'c', 'note'].sort())
    expect(Object.keys(workflow.subgraphs)).toHaveLength(1)
    expect(workflow.undoStack.length).toBe(before + 1)

    workflow.undo()
    expect(Object.keys(workflow.nodes).sort()).toEqual(['c', 'note', 'sq', 'sum'])
    expect(Object.keys(workflow.subgraphs)).toHaveLength(0)
  })

  it('expands an instance back with its inner positions restored', () => {
    const workflow = setup()
    const positions = {
      sq: workflow.nodes['sq']?.pos,
      sum: workflow.nodes['sum']?.pos,
    }
    const instance = workflow.collapseToSubgraph(['sq', 'sum'])!
    const created = workflow.expandSubgraph(instance)
    expect(created.sort()).toEqual(['sq', 'sum'])
    expect(workflow.nodes['sq']?.pos).toEqual(positions.sq)
    expect(workflow.nodes['sum']?.pos).toEqual(positions.sum)
    // The edge from c is reconnected to the inner node it fed.
    const restored = Object.values(workflow.edges).find((e) => e.to[0] === 'sq')
    expect(restored?.from).toEqual(['c', 'out'])
  })

  it('renames inner nodes that collide with the parent canvas on expand', () => {
    const workflow = setup()
    const instance = workflow.collapseToSubgraph(['sq'])!
    // Re-create a node with the inner id so expanding has to rename.
    workflow.commit('command.add_node', (draft) => {
      const source = draft.nodes['c']
      if (source) draft.nodes['sq'] = { ...source }
    })
    const created = workflow.expandSubgraph(instance)
    expect(created).toEqual(['sq_2'])
    expect(workflow.nodes['sq']).toBeDefined()
  })

  it('navigates in and out of a subgraph body', () => {
    const workflow = setup()
    const instance = workflow.collapseToSubgraph(['sq', 'sum'], 'Measure')!
    expect(workflow.enterSubgraph(instance)).toBe(true)
    expect(workflow.breadcrumbs.map((c) => c.label)).toEqual(['Measure'])
    expect(Object.keys(workflow.nodes).sort()).toEqual(['sq', 'sum'])
    expect(workflow.groups).toEqual({})

    // Edits inside the body land in the subgraph, not the root.
    workflow.setParam('sum', 'z', 9)
    workflow.exitSubgraph(0)
    expect(workflow.breadcrumbs).toHaveLength(0)
    expect(Object.keys(workflow.nodes)).toContain(instance)
    const sgId = Object.keys(workflow.subgraphs)[0] as string
    expect(workflow.subgraphs[sgId]?.nodes?.['sum']?.params?.['z']).toBe(9)
  })

  it('promotes an inner param so the instance exposes it', () => {
    const workflow = setup()
    const instance = workflow.collapseToSubgraph(['sq', 'sum'])!
    const sgId = Object.keys(workflow.subgraphs)[0] as string
    workflow.promoteSubgraphParam(sgId, 'sum', 'z')
    expect(workflow.specs[`subgraph:${sgId}`]?.params.map((p) => p.name)).toEqual(['sum.z'])
    workflow.setParam(instance, 'sum.z', 4)
    expect(workflow.nodes[instance]?.params?.['sum.z']).toBe(4)
    // Expanding writes the override back into the inner node.
    workflow.expandSubgraph(instance)
    expect(workflow.nodes['sum']?.params?.['z']).toBe(4)
  })

  it('validates connections against the typed ports of an instance', () => {
    const workflow = setup()
    const instance = workflow.collapseToSubgraph(['sq', 'sum'])!
    const taken = workflow.validateConnection({
      source: 'c',
      sourcePort: 'out',
      target: instance,
      targetPort: 'y',
    })
    // `c.out` already feeds that port through the rewired edge, so this is a no-op re-validation.
    expect(taken).toMatchObject({ ok: true, targetType: 'astro.Float' })
    const unknown = workflow.validateConnection({
      source: 'c',
      sourcePort: 'out',
      target: instance,
      targetPort: 'nope',
    })
    expect(unknown).toMatchObject({ ok: false, reason: 'unknown_port' })
  })

  it('round-trips a subgraph through a blueprint document', () => {
    const workflow = setup()
    const instance = workflow.collapseToSubgraph(['sq', 'sum'], 'Measure')!
    const sgId = Object.keys(workflow.subgraphs)[0] as string
    const blueprint = workflow.blueprintOf(sgId, 'Measure line')
    expect(blueprint?.name).toBe('Measure line')
    expect(Object.keys(blueprint?.subgraphs ?? {})).toEqual([sgId])

    workflow.removeNodes([instance])
    const inserted = workflow.insertBlueprint(blueprint!, [10, 20])
    expect(inserted).not.toBeNull()
    // The id is already taken by this document's own copy, so the insert gets a fresh one.
    const insertedType = workflow.nodes[inserted!]?.type ?? ''
    expect(insertedType.startsWith('subgraph:')).toBe(true)
    expect(workflow.subgraphs[insertedType.slice('subgraph:'.length)]?.name).toBe('Measure')
    expect(workflow.nodes[inserted!]?.pos).toEqual([10, 20])
  })
})

describe('expandInstance', () => {
  it('returns null for a node that is not an instance', () => {
    const workflow = setup()
    expect(
      expandInstance(workflow.nodes, workflow.edges, 'ghost', { name: '' }, () => false),
    ).toBeNull()
  })
})
