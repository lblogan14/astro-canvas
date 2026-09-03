/**
 * Document → Vue Flow elements. Flow node/edge objects are memoised by document entry identity so
 * an unrelated edit (one param on one node) leaves every other flow object untouched and Vue Flow
 * re-renders only what changed (design §10.2).
 */
import { type ComputedRef, computed } from 'vue'
import type { Edge, Node } from '@vue-flow/core'

import type { EdgeDoc, NodeDoc } from '@/api/types'
import { outputType } from '@/canvas/compat'
import { portStyle } from '@/canvas/ports'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { type CanvasGroup, DEFAULT_NODE_SIZE, useWorkflowStore } from '@/stores/workflow'

export const ASTRO_NODE = 'astro'
export const GROUP_NODE = 'group'

export interface AstroNodeData {
  nodeId: string
}

export interface GroupNodeData {
  groupId: string
}

export type AstroFlowNode = Node<AstroNodeData, Record<string, never>, typeof ASTRO_NODE>
export type GroupFlowNode = Node<GroupNodeData, Record<string, never>, typeof GROUP_NODE>
export type FlowNode = AstroFlowNode | GroupFlowNode

interface NodeCacheEntry {
  source: NodeDoc
  parent: string | undefined
  parentX: number
  parentY: number
  flow: AstroFlowNode
}

interface GroupCacheEntry {
  source: CanvasGroup
  flow: GroupFlowNode
}

interface EdgeCacheEntry {
  source: EdgeDoc
  color: string
  flow: Edge
}

export function groupNodeId(groupId: string): string {
  return `group:${groupId}`
}

export function isGroupNodeId(id: string): boolean {
  return id.startsWith('group:')
}

export function groupIdOf(flowId: string): string {
  return flowId.slice('group:'.length)
}

function buildAstroNode(
  id: string,
  node: NodeDoc,
  parent: string | undefined,
  parentX: number,
  parentY: number,
): AstroFlowNode {
  const [x, y] = node.pos ?? [0, 0]
  const size = node.size
  return {
    id,
    type: ASTRO_NODE,
    position: { x: x - parentX, y: y - parentY },
    data: { nodeId: id },
    parentNode: parent,
    ...(size ? { width: size[0], height: size[1] } : {}),
    ...(parent ? { expandParent: false } : {}),
  }
}

function buildGroupNode(groupId: string, group: CanvasGroup): GroupFlowNode {
  const [x, y] = group.pos ?? [0, 0]
  const [w, h] = group.size ?? [400, 300]
  return {
    id: groupNodeId(groupId),
    type: GROUP_NODE,
    position: { x, y },
    data: { groupId },
    width: w,
    height: h,
    zIndex: -1,
    selectable: true,
  }
}

function buildEdge(id: string, edge: EdgeDoc, color: string): Edge {
  return {
    id,
    source: edge.from[0],
    target: edge.to[0],
    sourceHandle: edge.from[1],
    targetHandle: edge.to[1],
    type: 'default',
    updatable: true,
    style: { stroke: color, strokeWidth: 2 },
    data: { color },
  }
}

/** Reactive Vue Flow nodes and edges derived from the workflow store. */
export function useFlowElements(): { nodes: ComputedRef<FlowNode[]>; edges: ComputedRef<Edge[]> } {
  const workflow = useWorkflowStore()
  const schema = useNodesSchemaStore()
  const nodeCache = new Map<string, NodeCacheEntry>()
  const groupCache = new Map<string, GroupCacheEntry>()
  const edgeCache = new Map<string, EdgeCacheEntry>()

  const nodes = computed<FlowNode[]>(() => {
    const docNodes = workflow.nodes
    const docGroups = workflow.groups
    const out: FlowNode[] = []
    const parentOf = new Map<string, string>()
    for (const gid of Object.keys(docGroups)) {
      const group = docGroups[gid] as CanvasGroup
      for (const member of group.nodes ?? []) parentOf.set(member, gid)
      const cached = groupCache.get(gid)
      if (cached && cached.source === group) {
        out.push(cached.flow)
      } else {
        const flow = buildGroupNode(gid, group)
        groupCache.set(gid, { source: group, flow })
        out.push(flow)
      }
    }
    for (const gid of groupCache.keys()) if (!(gid in docGroups)) groupCache.delete(gid)

    for (const id of Object.keys(docNodes)) {
      const node = docNodes[id] as NodeDoc
      const gid = parentOf.get(id)
      const group = gid ? docGroups[gid] : undefined
      const parent = gid && group ? groupNodeId(gid) : undefined
      const [px, py] = group?.pos ?? [0, 0]
      const cached = nodeCache.get(id)
      if (
        cached &&
        cached.source === node &&
        cached.parent === parent &&
        cached.parentX === px &&
        cached.parentY === py
      ) {
        out.push(cached.flow)
      } else {
        const flow = buildAstroNode(id, node, parent, px, py)
        nodeCache.set(id, { source: node, parent, parentX: px, parentY: py, flow })
        out.push(flow)
      }
    }
    for (const id of nodeCache.keys()) if (!(id in docNodes)) nodeCache.delete(id)
    return out
  })

  const edges = computed<Edge[]>(() => {
    const docEdges = workflow.edges
    const docNodes = workflow.nodes
    const out: Edge[] = []
    for (const id of Object.keys(docEdges)) {
      const edge = docEdges[id] as EdgeDoc
      const sourceNode = docNodes[edge.from[0]]
      const spec = sourceNode ? schema.byId[sourceNode.type] : undefined
      const typeId = spec ? outputType(spec, edge.from[1]) : undefined
      const color = typeId ? portStyle(typeId).color : '#999999'
      const cached = edgeCache.get(id)
      if (cached && cached.source === edge && cached.color === color) {
        out.push(cached.flow)
      } else {
        const flow = buildEdge(id, edge, color)
        edgeCache.set(id, { source: edge, color, flow })
        out.push(flow)
      }
    }
    for (const id of edgeCache.keys()) if (!(id in docEdges)) edgeCache.delete(id)
    return out
  })

  return { nodes, edges }
}

/** Default node width/height used before a node has been measured. */
export const NODE_DEFAULTS = { width: DEFAULT_NODE_SIZE[0], height: DEFAULT_NODE_SIZE[1] }
