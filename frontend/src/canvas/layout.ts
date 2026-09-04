/**
 * Auto-layout with elkjs' layered algorithm (design §10.1): tidy the whole graph or just the
 * selection. The layout runs on the document (positions and sizes), not on canvas internals, so
 * the result is one undoable move command.
 */
import type { EdgeDoc, NodeDoc } from '@/api/types'
import { DEFAULT_NODE_SIZE, type Pos } from '@/stores/workflow'

export type NodeMap = Readonly<Record<string, NodeDoc>>
export type EdgeMap = Readonly<Record<string, EdgeDoc>>

export interface LayoutOptions {
  /** Restrict the layout to these nodes (edges between them are honoured). */
  nodeIds?: readonly string[]
  /** `RIGHT` (left to right, the default reading order of a pipeline) or `DOWN`. */
  direction?: 'RIGHT' | 'DOWN'
  spacing?: number
  layerSpacing?: number
}

export interface LayoutMove {
  id: string
  pos: Pos
}

const ELK_OPTIONS = (options: LayoutOptions): Record<string, string> => ({
  'elk.algorithm': 'layered',
  'elk.direction': options.direction ?? 'RIGHT',
  'elk.spacing.nodeNode': String(options.spacing ?? 48),
  'elk.layered.spacing.nodeNodeBetweenLayers': String(options.layerSpacing ?? 96),
  'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
  'elk.edgeRouting': 'POLYLINE',
})

/** The top-left corner of the laid-out nodes' current positions, so the result stays put. */
function origin(nodes: NodeMap, ids: readonly string[]): Pos {
  let x = Number.POSITIVE_INFINITY
  let y = Number.POSITIVE_INFINITY
  for (const id of ids) {
    const pos = nodes[id]?.pos
    if (!pos) continue
    x = Math.min(x, pos[0])
    y = Math.min(y, pos[1])
  }
  return [Number.isFinite(x) ? x : 0, Number.isFinite(y) ? y : 0]
}

/**
 * Positions for `nodeIds` (default: every node) as a layered left-to-right graph, anchored at
 * the selection's current top-left corner. Returns only the nodes that actually move.
 */
export async function layoutGraph(
  nodes: NodeMap,
  edges: EdgeMap,
  options: LayoutOptions = {},
): Promise<LayoutMove[]> {
  const ids = (options.nodeIds ?? Object.keys(nodes)).filter((id) => nodes[id] !== undefined)
  if (ids.length < 2) return []
  const set = new Set(ids)
  const { default: ELK } = await import('elkjs/lib/elk.bundled.js')
  const elk = new ELK()
  const graph = {
    id: 'root',
    layoutOptions: ELK_OPTIONS(options),
    children: ids.map((id) => {
      const [w, h] = nodes[id]?.size ?? DEFAULT_NODE_SIZE
      return { id, width: w, height: h }
    }),
    edges: Object.entries(edges)
      .filter(([, edge]) => set.has(edge.from[0]) && set.has(edge.to[0]))
      .map(([eid, edge]) => ({ id: eid, sources: [edge.from[0]], targets: [edge.to[0]] })),
  }
  const laid = await elk.layout(graph)
  const [ox, oy] = origin(nodes, ids)
  // elk pads the root graph; shift it away so the result lands exactly on the old corner.
  const children = laid.children ?? []
  const padX = children.length ? Math.min(...children.map((c) => c.x ?? 0)) : 0
  const padY = children.length ? Math.min(...children.map((c) => c.y ?? 0)) : 0
  const moves: LayoutMove[] = []
  for (const child of children) {
    const node = nodes[child.id]
    if (!node) continue
    const pos: Pos = [
      Math.round((child.x ?? 0) - padX + ox),
      Math.round((child.y ?? 0) - padY + oy),
    ]
    const [x, y] = node.pos ?? [0, 0]
    if (pos[0] !== x || pos[1] !== y) moves.push({ id: child.id, pos })
  }
  return moves
}
