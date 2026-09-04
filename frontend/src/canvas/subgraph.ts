/**
 * Subgraphs on the canvas: collapsing a selection into a reusable body, expanding an instance
 * back in place, and the synthetic `NodeSpec` that gives an instance typed ports.
 *
 * The document shape is `astro_canvas.engine.graph.SubgraphDoc`: `nodes`/`edges` are the body,
 * `inputs`/`outputs` name the boundary ports (`{name, node, port}`) and `promoted` lists the
 * inner params an instance may set through its own `params` (keyed `"<inner node>.<param>"`).
 */
import type { EdgeDoc, NodeDoc, NodeSpec, ParamSpec, SubgraphDoc } from '@/api/types'
import { inputType, outputType } from '@/canvas/compat'
import { clone } from '@/lib/deepEqual'

export const SUBGRAPH_PREFIX = 'subgraph:'

export type NodeMap = Readonly<Record<string, NodeDoc>>
export type EdgeMap = Readonly<Record<string, EdgeDoc>>
export type SpecIndex = Readonly<Record<string, NodeSpec>>

export function isSubgraphType(type: string): boolean {
  return type.startsWith(SUBGRAPH_PREFIX)
}

export function subgraphIdOf(type: string): string {
  return type.slice(SUBGRAPH_PREFIX.length)
}

export function subgraphType(id: string): string {
  return `${SUBGRAPH_PREFIX}${id}`
}

const EMPTY_SPEC = {
  category: 'Subgraphs',
  cost: 'cheap',
  deprecated: false,
  description: '',
  editor: null,
  expand: false,
  experimental: false,
  fingerprint: false,
  icon: 'component',
  is_async: false,
  module: '',
  pack: null,
  param_docs: {},
  preview: null,
  version: '1.0.0',
} as const

/** The inner node/port a boundary port or promoted ref points at. */
function innerPort(
  body: NodeMap,
  specs: SpecIndex,
  node: string,
  port: string,
  kind: 'in' | 'out',
): string | undefined {
  const inner = body[node]
  const spec = inner ? specs[inner.type] : undefined
  if (!inner || !spec) return undefined
  return kind === 'out' ? outputType(spec, port) : inputType(spec, inner, port)
}

/**
 * A `NodeSpec` for `subgraph:<id>` so the instance gets handles, edge validation and a param
 * form exactly like a registered node. Ports whose inner type cannot be resolved fall back to
 * `astro.Any` rather than disappearing.
 */
export function subgraphSpec(id: string, sg: SubgraphDoc, specs: SpecIndex): NodeSpec {
  const body = (sg.nodes ?? {}) as NodeMap
  const params: ParamSpec[] = []
  for (const promoted of sg.promoted ?? []) {
    const inner = body[promoted.node]
    const source = inner ? specs[inner.type]?.params.find((p) => p.name === promoted.param) : null
    if (!source) continue
    params.push({
      ...source,
      name: `${promoted.node}.${promoted.param}`,
      label: promoted.label || source.label,
      default: inner?.params?.[promoted.param] ?? source.default,
    })
  }
  return {
    ...EMPTY_SPEC,
    id: subgraphType(id),
    name: sg.name || id,
    description: `Subgraph with ${Object.keys(body).length} nodes.`,
    inputs: (sg.inputs ?? []).map((port) => ({
      name: port.name,
      type: innerPort(body, specs, port.node, port.port, 'in') ?? 'astro.Any',
      description: '',
      lazy: false,
      required: false,
    })),
    outputs: (sg.outputs ?? []).map((port) => ({
      name: port.name,
      type: innerPort(body, specs, port.node, port.port, 'out') ?? 'astro.Any',
      description: '',
      lazy: false,
      required: true,
    })),
    params,
  }
}

/** Synthetic specs for every subgraph in a document, merged over the registry's specs. */
export function subgraphSpecs(
  subgraphs: Readonly<Record<string, SubgraphDoc>>,
  specs: SpecIndex,
): Record<string, NodeSpec> {
  const out: Record<string, NodeSpec> = {}
  for (const [id, sg] of Object.entries(subgraphs))
    out[subgraphType(id)] = subgraphSpec(id, sg, specs)
  return out
}

// --- collapse ----------------------------------------------------------------------------------

export interface CollapseResult {
  subgraph: SubgraphDoc
  /** The instance node to put on the parent canvas. */
  instance: NodeDoc
  /** Parent edges that survive, rewired to the instance (keyed by their original id). */
  edges: Record<string, EdgeDoc>
  /** Parent edge ids that are now inside the subgraph or dangling. */
  removed: string[]
}

function centroid(nodes: NodeMap, ids: readonly string[]): [number, number] {
  let x = 0
  let y = 0
  let n = 0
  for (const id of ids) {
    const pos = nodes[id]?.pos
    if (!pos) continue
    x += pos[0]
    y += pos[1]
    n += 1
  }
  return n === 0 ? [0, 0] : [Math.round(x / n), Math.round(y / n)]
}

function uniqueName(taken: Set<string>, base: string): string {
  let name = base
  let n = 2
  while (taken.has(name)) name = `${base}_${n++}`
  taken.add(name)
  return name
}

/**
 * Collapse `ids` into a subgraph body. Edges crossing the boundary become named ports: one input
 * per distinct inner target port, one output per distinct inner source port, so two outer
 * consumers of the same inner output share one port.
 */
export function collapseSelection(
  nodes: NodeMap,
  edges: EdgeMap,
  ids: readonly string[],
  instanceId: string,
  options: { name?: string; title?: string } = {},
): CollapseResult | null {
  const inside = ids.filter((id) => nodes[id] !== undefined)
  if (inside.length === 0) return null
  const set = new Set(inside)
  const [cx, cy] = centroid(nodes, inside)

  const body: Record<string, NodeDoc> = {}
  for (const id of inside) {
    const node = clone(nodes[id] as NodeDoc)
    const [x, y] = node.pos ?? [0, 0]
    node.pos = [x - cx, y - cy]
    body[id] = node
  }

  const inner: Record<string, EdgeDoc> = {}
  const kept: Record<string, EdgeDoc> = {}
  const removed: string[] = []
  const inputs: NonNullable<SubgraphDoc['inputs']> = []
  const outputs: NonNullable<SubgraphDoc['outputs']> = []
  const inputNames = new Map<string, string>()
  const outputNames = new Map<string, string>()
  const taken = new Set<string>()

  for (const [eid, edge] of Object.entries(edges)) {
    const fromIn = set.has(edge.from[0])
    const toIn = set.has(edge.to[0])
    if (fromIn && toIn) {
      inner[eid] = clone(edge)
      removed.push(eid)
    } else if (toIn) {
      const key = `${edge.to[0]}.${edge.to[1]}`
      let name = inputNames.get(key)
      if (name === undefined) {
        name = uniqueName(taken, edge.to[1])
        inputNames.set(key, name)
        inputs.push({ name, node: edge.to[0], port: edge.to[1] })
      }
      kept[eid] = { from: [...edge.from], to: [instanceId, name] }
    } else if (fromIn) {
      const key = `${edge.from[0]}.${edge.from[1]}`
      let name = outputNames.get(key)
      if (name === undefined) {
        name = uniqueName(taken, edge.from[1])
        outputNames.set(key, name)
        outputs.push({ name, node: edge.from[0], port: edge.from[1] })
      }
      kept[eid] = { from: [instanceId, name], to: [...edge.to] }
    }
  }

  return {
    subgraph: {
      name: options.name ?? 'Subgraph',
      nodes: body,
      edges: inner,
      inputs,
      outputs,
      promoted: [],
    },
    instance: {
      type: '', // filled in by the caller once the subgraph id is known
      version: null,
      title: options.title ?? options.name ?? null,
      pos: [cx, cy],
      size: null,
      params: {},
      linked: [],
      ui: {},
      cost: null,
      disabled: false,
      notes: '',
    },
    edges: kept,
    removed,
  }
}

// --- expand ------------------------------------------------------------------------------------

export interface ExpandResult {
  nodes: Record<string, NodeDoc>
  edges: Record<string, EdgeDoc>
  /** old inner id → id used on the parent canvas (renamed on collision). */
  idMap: Record<string, string>
}

/**
 * Expand `instanceId` back onto the parent canvas: inner nodes return at their stored offsets
 * from the instance position, inner edges come back, and edges attached to the instance's ports
 * are rewired to the inner nodes they mapped to.
 */
export function expandInstance(
  nodes: NodeMap,
  edges: EdgeMap,
  instanceId: string,
  sg: SubgraphDoc,
  isTaken: (id: string) => boolean,
): ExpandResult | null {
  const instance = nodes[instanceId]
  if (!instance) return null
  const [ix, iy] = instance.pos ?? [0, 0]
  const idMap: Record<string, string> = {}
  const taken = (id: string) => isTaken(id) || Object.values(idMap).includes(id)
  for (const id of Object.keys(sg.nodes ?? {})) {
    let candidate = id
    let n = 2
    while (candidate === instanceId || taken(candidate)) candidate = `${id}_${n++}`
    idMap[id] = candidate
  }

  const outNodes: Record<string, NodeDoc> = {}
  for (const [id, node] of Object.entries(sg.nodes ?? {})) {
    const copy = clone(node)
    const [x, y] = copy.pos ?? [0, 0]
    copy.pos = [x + ix, y + iy]
    outNodes[idMap[id] as string] = copy
  }
  // Promoted overrides set on the instance travel back into the inner nodes they came from.
  for (const promoted of sg.promoted ?? []) {
    const value = instance.params?.[`${promoted.node}.${promoted.param}`]
    const target = outNodes[idMap[promoted.node] ?? '']
    if (value !== undefined && target) target.params = { ...target.params, [promoted.param]: value }
  }

  const outEdges: Record<string, EdgeDoc> = {}
  let seq = 0
  const freshEdgeId = (): string => {
    let candidate = `${instanceId}_e${seq++}`
    while (isTaken(candidate) || candidate in outEdges) candidate = `${instanceId}_e${seq++}`
    return candidate
  }
  for (const edge of Object.values(sg.edges ?? {})) {
    const from = idMap[edge.from[0]]
    const to = idMap[edge.to[0]]
    if (from && to) outEdges[freshEdgeId()] = { from: [from, edge.from[1]], to: [to, edge.to[1]] }
  }
  const inputOf = new Map((sg.inputs ?? []).map((p) => [p.name, p]))
  const outputOf = new Map((sg.outputs ?? []).map((p) => [p.name, p]))
  for (const [eid, edge] of Object.entries(edges)) {
    if (edge.to[0] === instanceId) {
      const port = inputOf.get(edge.to[1])
      const target = port ? idMap[port.node] : undefined
      if (port && target) outEdges[eid] = { from: [...edge.from], to: [target, port.port] }
    } else if (edge.from[0] === instanceId) {
      const port = outputOf.get(edge.from[1])
      const source = port ? idMap[port.node] : undefined
      if (port && source) outEdges[eid] = { from: [source, port.port], to: [...edge.to] }
    }
  }
  return { nodes: outNodes, edges: outEdges, idMap }
}
