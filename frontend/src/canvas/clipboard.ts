/**
 * Copy/paste and duplicate of node selections as a self-contained payload: the selected nodes,
 * the edges between them, and their bounding-box origin so pasting keeps relative offsets.
 */
import type { EdgeDoc, NodeDoc } from '@/api/types'
import { clone } from '@/lib/deepEqual'
import { newId } from '@/lib/ids'

export const CLIPBOARD_FORMAT = 'astro-canvas/clipboard'

export interface ClipboardPayload {
  format: typeof CLIPBOARD_FORMAT
  version: 1
  nodes: Record<string, NodeDoc>
  edges: Record<string, EdgeDoc>
  /** Top-left corner of the copied nodes' positions. */
  origin: [number, number]
}

export interface PasteResult {
  nodes: Record<string, NodeDoc>
  edges: Record<string, EdgeDoc>
  /** old id → new id */
  idMap: Record<string, string>
}

export function copySelection(
  nodes: Readonly<Record<string, NodeDoc>>,
  edges: Readonly<Record<string, EdgeDoc>>,
  ids: readonly string[],
): ClipboardPayload | null {
  const picked = ids.filter((id) => nodes[id] !== undefined)
  if (picked.length === 0) return null
  const set = new Set(picked)
  const outNodes: Record<string, NodeDoc> = {}
  let minX = Number.POSITIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  for (const id of picked) {
    const node = nodes[id] as NodeDoc
    outNodes[id] = clone(node)
    const [x, y] = node.pos ?? [0, 0]
    minX = Math.min(minX, x)
    minY = Math.min(minY, y)
  }
  const outEdges: Record<string, EdgeDoc> = {}
  for (const [eid, edge] of Object.entries(edges)) {
    if (set.has(edge.from[0]) && set.has(edge.to[0])) outEdges[eid] = clone(edge)
  }
  return {
    format: CLIPBOARD_FORMAT,
    version: 1,
    nodes: outNodes,
    edges: outEdges,
    origin: [Number.isFinite(minX) ? minX : 0, Number.isFinite(minY) ? minY : 0],
  }
}

export function parseClipboard(text: string): ClipboardPayload | null {
  try {
    const value = JSON.parse(text) as Partial<ClipboardPayload>
    if (value.format !== CLIPBOARD_FORMAT || typeof value.nodes !== 'object' || !value.nodes) {
      return null
    }
    return {
      format: CLIPBOARD_FORMAT,
      version: 1,
      nodes: value.nodes,
      edges: value.edges ?? {},
      origin: value.origin ?? [0, 0],
    }
  } catch {
    return null
  }
}

/**
 * Re-key a payload for insertion. Positions are translated so the payload's origin lands on
 * `at` (or shifted by `offset` from the origin when `at` is omitted); internal edges are kept.
 */
export function preparePaste(
  payload: ClipboardPayload,
  taken: (id: string) => boolean,
  options: { at?: [number, number]; offset?: [number, number] } = {},
): PasteResult {
  const [ox, oy] = payload.origin
  const [tx, ty] = options.at ?? [
    ox + (options.offset?.[0] ?? 40),
    oy + (options.offset?.[1] ?? 40),
  ]
  const idMap: Record<string, string> = {}
  const nodes: Record<string, NodeDoc> = {}
  const used = new Set<string>()
  for (const [oldId, node] of Object.entries(payload.nodes)) {
    let id = newId()
    while (taken(id) || used.has(id)) id = newId()
    used.add(id)
    idMap[oldId] = id
    const [x, y] = node.pos ?? [ox, oy]
    nodes[id] = { ...clone(node), pos: [x - ox + tx, y - oy + ty] }
  }
  const edges: Record<string, EdgeDoc> = {}
  for (const edge of Object.values(payload.edges)) {
    const from = idMap[edge.from[0]]
    const to = idMap[edge.to[0]]
    if (!from || !to) continue
    let id = newId('e')
    while (taken(id) || used.has(id)) id = newId('e')
    used.add(id)
    edges[id] = { from: [from, edge.from[1]], to: [to, edge.to[1]] }
  }
  return { nodes, edges, idMap }
}
