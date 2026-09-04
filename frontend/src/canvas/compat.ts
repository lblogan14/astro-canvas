/**
 * Client-side edge validation mirroring `astro_canvas.sdk.porttype.is_compatible` and the
 * compiler's structural rules (`multiple_inputs`, `cycle`, `unknown_port`). Every rejection has a
 * `reason` code so the UI can explain it (`t('canvas.reject.<reason>')`).
 */
import type { EdgeDoc, NodeDoc, NodeSpec, PortTypeSpec } from '@/api/types'
import { applyDynamicPorts } from '@/nodes/dynamicPorts'

export const ANY_TYPE = 'astro.Any'
export const JSON_TYPE = 'astro.Json'
export const SCALAR_TYPES: ReadonlySet<string> = new Set([
  'astro.Float',
  'astro.Int',
  'astro.Str',
  'astro.Bool',
])

export type TypeIndex = Readonly<Record<string, PortTypeSpec>>

/** Can an output of type `source` feed an input of type `target`? */
export function isTypeCompatible(source: string, target: string, types: TypeIndex): boolean {
  if (target === source || target === ANY_TYPE) return true
  if (target === JSON_TYPE && SCALAR_TYPES.has(source)) return true
  const spec = types[source]
  return spec !== undefined && spec.compatible_with.includes(target)
}

export type RejectReason =
  'self' | 'unknown_node' | 'unknown_port' | 'multiple_inputs' | 'type_mismatch' | 'cycle'

export type ConnectionVerdict =
  | { ok: true; sourceType: string; targetType: string }
  | { ok: false; reason: RejectReason; sourceType?: string; targetType?: string }

export interface ConnectionQuery {
  source: string
  sourcePort: string
  target: string
  targetPort: string
}

export interface GraphView {
  nodes: Readonly<Record<string, NodeDoc>>
  edges: Readonly<Record<string, EdgeDoc>>
  specs: Readonly<Record<string, NodeSpec>>
  types: TypeIndex
}

/**
 * The spec a node instance behaves as. A node that declares its ports in its own params (the
 * code node) needs them merged in before an edge can be judged.
 */
function specOf(graph: GraphView, node: NodeDoc): NodeSpec | undefined {
  const spec = graph.specs[node.type]
  return spec ? applyDynamicPorts(spec, node) : undefined
}

/** Type of an output port of a node (by its spec). */
export function outputType(spec: NodeSpec, port: string): string | undefined {
  return spec.outputs.find((p) => p.name === port)?.type
}

/**
 * Type of an input port of a node: a declared input, or a param (linked or linkable) whose
 * `link_type` is the port type once linked.
 */
export function inputType(spec: NodeSpec, node: NodeDoc, port: string): string | undefined {
  const input = spec.inputs.find((p) => p.name === port)
  if (input) return input.type
  const param = spec.params.find((p) => p.name === port)
  if (param && (param.linkable || (node.linked ?? []).includes(port))) return param.link_type
  return undefined
}

/** Ids of every node reachable downstream from `start` (excluding `start`). */
export function descendants(edges: Readonly<Record<string, EdgeDoc>>, start: string): Set<string> {
  const out = new Map<string, string[]>()
  for (const edge of Object.values(edges)) {
    const [from] = edge.from
    const [to] = edge.to
    const list = out.get(from)
    if (list) list.push(to)
    else out.set(from, [to])
  }
  const seen = new Set<string>()
  const stack = [start]
  while (stack.length) {
    const current = stack.pop() as string
    for (const next of out.get(current) ?? []) {
      if (!seen.has(next)) {
        seen.add(next)
        stack.push(next)
      }
    }
  }
  return seen
}

/** The edge currently feeding `target.port`, if any. */
export function incomingEdge(
  edges: Readonly<Record<string, EdgeDoc>>,
  target: string,
  port: string,
): [string, EdgeDoc] | undefined {
  return Object.entries(edges).find(([, e]) => e.to[0] === target && e.to[1] === port)
}

/**
 * Full verdict for a proposed connection. `ignoreEdge` lets a reconnection skip the edge being
 * moved when checking `multiple_inputs`.
 */
export function checkConnection(
  graph: GraphView,
  query: ConnectionQuery,
  ignoreEdge?: string,
): ConnectionVerdict {
  const { source, sourcePort, target, targetPort } = query
  if (source === target) return { ok: false, reason: 'self' }
  const sourceNode = graph.nodes[source]
  const targetNode = graph.nodes[target]
  if (!sourceNode || !targetNode) return { ok: false, reason: 'unknown_node' }
  const sourceSpec = specOf(graph, sourceNode)
  const targetSpec = specOf(graph, targetNode)
  if (!sourceSpec || !targetSpec) return { ok: false, reason: 'unknown_node' }
  const sourceType = outputType(sourceSpec, sourcePort)
  const targetType = inputType(targetSpec, targetNode, targetPort)
  if (!sourceType || !targetType) return { ok: false, reason: 'unknown_port' }
  const existing = incomingEdge(graph.edges, target, targetPort)
  if (existing && existing[0] !== ignoreEdge) {
    // The very same edge (re-validated by the canvas library) is fine; another feeder is not.
    const same = existing[1].from[0] === source && existing[1].from[1] === sourcePort
    if (same) return { ok: true, sourceType, targetType }
    return { ok: false, reason: 'multiple_inputs', sourceType, targetType }
  }
  if (!isTypeCompatible(sourceType, targetType, graph.types)) {
    return { ok: false, reason: 'type_mismatch', sourceType, targetType }
  }
  if (descendants(graph.edges, target).has(source)) {
    return { ok: false, reason: 'cycle', sourceType, targetType }
  }
  return { ok: true, sourceType, targetType }
}
