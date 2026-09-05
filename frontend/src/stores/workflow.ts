/**
 * The open workflow document (format v1 mirror) with command-pattern undo/redo, coalescing,
 * dirty tracking and debounced autosave (`PUT /api/workflows/{id}`).
 *
 * Every mutation goes through `commit()`, which snapshots the document core (shallow copies of
 * the `nodes`/`edges`/`groups` maps plus name/description) before and after the change. Entries
 * are always replaced, never mutated in place, so snapshots stay valid and Vue Flow node objects
 * can be memoised by entry identity.
 */
import { computed, ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'

import { api } from '@/api/client'
import type {
  EdgeDoc,
  GroupDoc,
  LayoutIssue,
  NodeDoc,
  NodeErrors,
  NodeSpec,
  PromotedDoc,
  SubgraphDoc,
  ViewDoc,
  WorkflowDoc,
} from '@/api/types'
import { type ClipboardPayload, copySelection, preparePaste } from '@/canvas/clipboard'
import { type ConnectionQuery, type ConnectionVerdict, checkConnection } from '@/canvas/compat'
import {
  collapseSelection,
  expandInstance,
  isSubgraphType,
  subgraphIdOf,
  subgraphSpecs,
  subgraphType,
} from '@/canvas/subgraph'
import { clone } from '@/lib/deepEqual'
import {
  PROMOTED_PREFIX,
  VIEW_PREFIX,
  dropRefFromLayouts,
  groupPromoted,
  refOf,
} from '@/modes/layouts'
import { newId } from '@/lib/ids'
import { applyDynamicPorts } from '@/nodes/dynamicPorts'
import { useExecutionStore } from './execution'
import { useNodesSchemaStore } from './nodesSchema'

export type Pos = [number, number]
export type Size = [number, number]

/** A group with the UI-only geometry the canvas keeps on it (extra fields are preserved). */
export interface CanvasGroup extends GroupDoc {
  pos?: Pos
  size?: Size
}

export interface DocCore {
  name: string
  description: string
  nodes: Record<string, NodeDoc>
  edges: Record<string, EdgeDoc>
  groups: Record<string, CanvasGroup>
  subgraphs: Record<string, SubgraphDoc>
  /** Params lifted into the App/Wizard/Dashboard/Batch layouts, in display order. */
  promoted: PromotedDoc[]
  /** Node outputs pinned as views for those layouts. */
  views: ViewDoc[]
  /** `layouts.app|wizard|dashboard|batch`; unknown sections round-trip untouched. */
  layouts: Record<string, unknown>
}

/** One step of the open subgraph path: the instance node and the body it points at. */
export interface Breadcrumb {
  /** Instance node id in its parent container (empty for the document root). */
  nodeId: string
  subgraphId: string
  label: string
}

export interface Command {
  label: string
  before: DocCore
  after: DocCore
  coalesceKey?: string
  at: number
}

export type SaveState = 'clean' | 'pending' | 'saving' | 'saved' | 'error'

export interface CommitOptions {
  /** Commands with the same key committed within the coalescing window merge into one. */
  coalesce?: string
  /** Position/size/title/notes changes: saved, but they do not touch cache keys. */
  uiOnly?: boolean
}

export const GROUP_PADDING = 24
export const GROUP_HEADER = 32
export const DEFAULT_NODE_SIZE: Size = [240, 120]

const MAX_UNDO = 200

export function emptyDoc(name: string, id = newId('wf')): WorkflowDoc {
  return {
    format: 'astro-canvas/workflow',
    version: 1,
    id,
    name,
    description: '',
    nodes: {},
    edges: {},
    groups: {},
    subgraphs: {},
    promoted: [],
    views: [],
    layouts: {},
    requires: {},
    meta: {},
  }
}

/** Build a node document from its spec with param defaults filled in. */
export function nodeFromSpec(spec: NodeSpec, pos: Pos): NodeDoc {
  const params: Record<string, unknown> = {}
  for (const param of spec.params) {
    if (param.default !== null && param.default !== undefined) params[param.name] = param.default
  }
  return {
    type: spec.id,
    version: null,
    title: null,
    pos,
    size: null,
    params,
    linked: [],
    ui: {},
    cost: null,
    disabled: false,
    notes: '',
  }
}

function core(doc: WorkflowDoc): DocCore {
  return {
    name: doc.name,
    description: doc.description,
    nodes: { ...doc.nodes },
    edges: { ...doc.edges },
    groups: { ...(doc.groups as Record<string, CanvasGroup> | undefined) },
    subgraphs: { ...doc.subgraphs },
    promoted: [...(doc.promoted ?? [])],
    views: [...(doc.views ?? [])],
    layouts: { ...(doc.layouts as Record<string, unknown> | undefined) },
  }
}

/**
 * Resolve a path of instance node ids to the subgraph ids they open. Stops at the first step
 * that is not a subgraph instance, so a stale path degrades to the deepest valid prefix.
 */
export function resolvePath(doc: DocCore, path: readonly string[]): Breadcrumb[] {
  const out: Breadcrumb[] = []
  let nodes: Record<string, NodeDoc> = doc.nodes
  for (const nodeId of path) {
    const node = nodes[nodeId]
    if (!node || !isSubgraphType(node.type)) break
    const subgraphId = subgraphIdOf(node.type)
    const sg = doc.subgraphs[subgraphId]
    if (!sg) break
    out.push({ nodeId, subgraphId, label: node.title || sg.name || subgraphId })
    nodes = (sg.nodes ?? {}) as Record<string, NodeDoc>
  }
  return out
}

function nodeBounds(node: NodeDoc): { x: number; y: number; w: number; h: number } {
  const [x, y] = node.pos ?? [0, 0]
  const [w, h] = node.size ?? DEFAULT_NODE_SIZE
  return { x, y, w, h }
}

/** Geometry that encloses `ids` with padding and a header strip. */
export function groupGeometry(
  nodes: Readonly<Record<string, NodeDoc>>,
  ids: readonly string[],
): { pos: Pos; size: Size } | null {
  let minX = Number.POSITIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  for (const id of ids) {
    const node = nodes[id]
    if (!node) continue
    const b = nodeBounds(node)
    minX = Math.min(minX, b.x)
    minY = Math.min(minY, b.y)
    maxX = Math.max(maxX, b.x + b.w)
    maxY = Math.max(maxY, b.y + b.h)
  }
  if (!Number.isFinite(minX)) return null
  return {
    pos: [minX - GROUP_PADDING, minY - GROUP_PADDING - GROUP_HEADER],
    size: [maxX - minX + 2 * GROUP_PADDING, maxY - minY + 2 * GROUP_PADDING + GROUP_HEADER],
  }
}

export const useWorkflowStore = defineStore('workflow', () => {
  const doc = ref<WorkflowDoc | null>(null)
  const undoStack = shallowRef<Command[]>([])
  const redoStack = shallowRef<Command[]>([])
  const saveState = ref<SaveState>('clean')
  const saveError = ref<string | null>(null)
  /** `layout_errors` from the last save: layout refs the server could not resolve. */
  const layoutErrors = shallowRef<LayoutIssue[]>([])
  const lastSavedAt = ref<number | null>(null)
  /** Increments on every change; compared against the sequence a save started from. */
  const changeSeq = ref(0)
  const savedSeq = ref(0)
  /**
   * How long a burst of edits is collected before the document is PUT. The server debounces for
   * another 250 ms before it auto-runs, so this is half of what a user waits between a keystroke
   * and a new value on the canvas: a second here made an interactive edit feel like a second and
   * a half. 250 ms still folds continuous typing (and a slider drag) into one save.
   */
  const autosaveDelayMs = ref(250)
  const coalesceWindowMs = ref(800)
  const autosaveEnabled = ref(true)
  /** Commands within one `transaction()` fold into a single undo entry. */
  let transactionDepth = 0
  let transactionBefore: DocCore | null = null
  let transactionLabel = ''
  let saveTimer: ReturnType<typeof setTimeout> | null = null
  let saving: Promise<boolean> | null = null

  /** Instance node ids of the open subgraph, outermost first ([] = the document root). */
  const path = ref<string[]>([])

  const subgraphs = computed<Record<string, SubgraphDoc>>(() => doc.value?.subgraphs ?? {})
  const breadcrumbs = computed<Breadcrumb[]>(() =>
    doc.value ? resolvePath(core(doc.value), path.value) : [],
  )
  const openSubgraphId = computed<string | null>(
    () => breadcrumbs.value[breadcrumbs.value.length - 1]?.subgraphId ?? null,
  )
  const openSubgraph = computed<SubgraphDoc | null>(() =>
    openSubgraphId.value ? (subgraphs.value[openSubgraphId.value] ?? null) : null,
  )
  const nodes = computed<Record<string, NodeDoc>>(() =>
    openSubgraph.value
      ? ((openSubgraph.value.nodes ?? {}) as Record<string, NodeDoc>)
      : (doc.value?.nodes ?? {}),
  )
  const edges = computed<Record<string, EdgeDoc>>(() =>
    openSubgraph.value
      ? ((openSubgraph.value.edges ?? {}) as Record<string, EdgeDoc>)
      : (doc.value?.edges ?? {}),
  )
  // Groups live on the root canvas only; inside a subgraph the group layer is empty.
  const groups = computed<Record<string, CanvasGroup>>(() =>
    openSubgraph.value ? {} : ((doc.value?.groups ?? {}) as Record<string, CanvasGroup>),
  )
  /** Registry specs plus one synthetic spec per subgraph (`subgraph:<id>`). */
  const specs = computed<Record<string, NodeSpec>>(() => {
    const registry = useNodesSchemaStore().byId
    const extra = subgraphSpecs(subgraphs.value, registry)
    return Object.keys(extra).length ? { ...registry, ...extra } : registry
  })

  /**
   * The spec **one node instance** behaves as. Identical to `specs[node.type]` for every node
   * whose ports are fixed; a node that declares its ports in its params (the code node) gets
   * them merged in, exactly as `effective_ports` does on the server.
   */
  function specFor(node: NodeDoc | undefined): NodeSpec | undefined {
    if (!node) return undefined
    const spec = specs.value[node.type]
    return spec ? applyDynamicPorts(spec, node) : undefined
  }
  const id = computed(() => doc.value?.id ?? null)
  const name = computed(() => doc.value?.name ?? '')
  const isOpen = computed(() => doc.value !== null)
  const canUndo = computed(() => undoStack.value.length > 0)
  const canRedo = computed(() => redoStack.value.length > 0)
  const undoLabel = computed(() => undoStack.value[undoStack.value.length - 1]?.label ?? null)
  const redoLabel = computed(() => redoStack.value[redoStack.value.length - 1]?.label ?? null)
  const isDirty = computed(() => changeSeq.value !== savedSeq.value)
  const nodeCount = computed(() => Object.keys(nodes.value).length)

  /**
   * The **root** document's nodes, whatever container the canvas has open. Layout refs address
   * root nodes, so modes resolving `promoted`/`views` must read this, not `nodes`.
   */
  const rootNodes = computed<Record<string, NodeDoc>>(() => doc.value?.nodes ?? {})
  /** Promoted params in layout order (`order`, then document order for ties). */
  const promotedList = computed<PromotedDoc[]>(() =>
    [...(doc.value?.promoted ?? [])]
      .map((entry, index) => ({ entry, index }))
      .sort((a, b) => (a.entry.order ?? 0) - (b.entry.order ?? 0) || a.index - b.index)
      .map(({ entry }) => entry),
  )
  /** The same list bucketed by `group` (what the Parameters panel and App sections render). */
  const promotedGroups = computed(() => groupPromoted(promotedList.value))
  const views = computed<ViewDoc[]>(() => doc.value?.views ?? [])
  const layouts = computed<Record<string, unknown>>(
    () => (doc.value?.layouts as Record<string, unknown> | undefined) ?? {},
  )

  // --- document lifecycle ---------------------------------------------------------------------

  function normalize(input: WorkflowDoc): WorkflowDoc {
    const copy = clone(input)
    copy.nodes ??= {}
    copy.edges ??= {}
    copy.groups ??= {}
    copy.subgraphs ??= {}
    copy.promoted ??= []
    copy.views ??= []
    copy.layouts ??= {}
    copy.meta ??= {}
    copy.id ??= newId('wf')
    return copy
  }

  /** Replace the open document (no undo history, not dirty). */
  function load(input: WorkflowDoc): void {
    cancelScheduledSave()
    doc.value = normalize(input)
    layoutErrors.value = []
    path.value = []
    undoStack.value = []
    redoStack.value = []
    changeSeq.value = 0
    savedSeq.value = 0
    saveState.value = 'clean'
    saveError.value = null
  }

  function close(): void {
    cancelScheduledSave()
    doc.value = null
    path.value = []
    undoStack.value = []
    redoStack.value = []
    changeSeq.value = 0
    savedSeq.value = 0
    saveState.value = 'clean'
  }

  async function open(workflowId: string): Promise<void> {
    load(await api.getWorkflow(workflowId))
  }

  /** Create and store a new empty workflow; returns its id. */
  async function create(title: string): Promise<string> {
    const fresh = emptyDoc(title)
    const saved = await api.createWorkflow(fresh)
    load(saved.doc)
    layoutErrors.value = saved.layout_errors ?? []
    useExecutionStore().setIssues(saved.node_errors)
    return saved.doc.id as string
  }

  // --- commands -------------------------------------------------------------------------------

  function applyCore(next: DocCore): void {
    const current = doc.value
    if (!current) return
    current.name = next.name
    current.description = next.description
    current.nodes = next.nodes
    current.edges = next.edges
    current.groups = next.groups
    current.subgraphs = next.subgraphs
    current.promoted = next.promoted
    current.views = next.views
    current.layouts = next.layouts
  }

  /**
   * The maps a mutation should touch. Inside a subgraph the draft's `nodes`/`edges` are swapped
   * for the open body's; `sync` writes them back as a fresh `SubgraphDoc` entry.
   *
   * Everything else on the view is document-level (name, `promoted`, `views`, `layouts`, the
   * subgraph map itself), so `sync` copies those back too — a promotion or layout edit made
   * while a body is open must not be swallowed by the write-back. Groups are the exception:
   * the group layer is empty inside a body, so the root's groups are left as they are.
   */
  function scoped(draft: DocCore): { view: DocCore; sync: () => void } {
    const crumbs = resolvePath(draft, path.value)
    const sgId = crumbs[crumbs.length - 1]?.subgraphId
    const sg = sgId ? draft.subgraphs[sgId] : undefined
    if (!sgId || !sg) return { view: draft, sync: () => {} }
    const view: DocCore = {
      ...draft,
      nodes: { ...((sg.nodes ?? {}) as Record<string, NodeDoc>) },
      edges: { ...((sg.edges ?? {}) as Record<string, EdgeDoc>) },
      groups: {},
    }
    return {
      view,
      sync: () => {
        draft.name = view.name
        draft.description = view.description
        draft.promoted = view.promoted
        draft.views = view.views
        draft.layouts = view.layouts
        const body = view.subgraphs[sgId] ?? sg
        draft.subgraphs = {
          ...view.subgraphs,
          [sgId]: { ...body, nodes: view.nodes, edges: view.edges },
        }
      },
    }
  }

  function markChanged(): void {
    changeSeq.value += 1
    if (autosaveEnabled.value) scheduleSave()
  }

  /**
   * Run `mutate` against a shallow copy of the document core and record an undo command.
   * Returns whatever `mutate` returns.
   */
  function commit<T>(label: string, mutate: (draft: DocCore) => T, options: CommitOptions = {}): T {
    const current = doc.value
    if (!current) throw new Error('no workflow is open')
    const before = core(current)
    const draft = core(current)
    const { view, sync } = scoped(draft)
    const result = mutate(view)
    sync()
    applyCore(draft)
    if (transactionDepth > 0) {
      transactionBefore ??= before
      if (!transactionLabel) transactionLabel = label
      return result
    }
    push({ label, before, after: core(current), coalesceKey: options.coalesce, at: Date.now() })
    markChanged()
    return result
  }

  function push(command: Command): void {
    const top = undoStack.value[undoStack.value.length - 1]
    if (
      top &&
      command.coalesceKey &&
      top.coalesceKey === command.coalesceKey &&
      command.at - top.at <= coalesceWindowMs.value
    ) {
      undoStack.value = [
        ...undoStack.value.slice(0, -1),
        { ...top, after: command.after, at: command.at },
      ]
    } else {
      const next = [...undoStack.value, command]
      undoStack.value = next.length > MAX_UNDO ? next.slice(next.length - MAX_UNDO) : next
    }
    redoStack.value = []
  }

  /** Group several commits into one undo entry. */
  function transaction<T>(label: string, body: () => T): T {
    const current = doc.value
    if (!current) throw new Error('no workflow is open')
    transactionDepth += 1
    if (transactionDepth === 1) {
      transactionBefore = null
      transactionLabel = label
    }
    try {
      return body()
    } finally {
      transactionDepth -= 1
      if (transactionDepth === 0) {
        if (transactionBefore) {
          push({
            label: transactionLabel || label,
            before: transactionBefore,
            after: core(current),
            at: Date.now(),
          })
          markChanged()
        }
        transactionBefore = null
        transactionLabel = ''
      }
    }
  }

  function undo(): boolean {
    const command = undoStack.value[undoStack.value.length - 1]
    if (!command) return false
    undoStack.value = undoStack.value.slice(0, -1)
    redoStack.value = [...redoStack.value, command]
    applyCore(command.before)
    markChanged()
    return true
  }

  function redo(): boolean {
    const command = redoStack.value[redoStack.value.length - 1]
    if (!command) return false
    redoStack.value = redoStack.value.slice(0, -1)
    undoStack.value = [...undoStack.value, command]
    applyCore(command.after)
    markChanged()
    return true
  }

  // --- node operations ------------------------------------------------------------------------

  function hasId(candidate: string): boolean {
    const d = doc.value
    if (!d) return false
    return (
      candidate in nodes.value ||
      candidate in edges.value ||
      candidate in (d.groups ?? {}) ||
      candidate in (d.subgraphs ?? {})
    )
  }

  function freshId(prefix: string): string {
    let candidate = newId(prefix)
    while (hasId(candidate)) candidate = newId(prefix)
    return candidate
  }

  function addNode(spec: NodeSpec, pos: Pos, overrides: Partial<NodeDoc> = {}): string {
    return commit('command.add_node', (draft) => {
      const nodeId = freshId('n')
      draft.nodes[nodeId] = { ...nodeFromSpec(spec, pos), ...overrides }
      return nodeId
    })
  }

  function updateNode(
    nodeId: string,
    patch: Partial<NodeDoc>,
    label: string,
    options?: CommitOptions,
  ) {
    commit(
      label,
      (draft) => {
        const node = draft.nodes[nodeId]
        if (node) draft.nodes[nodeId] = { ...node, ...patch }
      },
      options,
    )
  }

  function removeNodes(ids: readonly string[]): void {
    const set = new Set(ids)
    if (set.size === 0) return
    commit('command.delete', (draft) => {
      for (const nodeId of set) delete draft.nodes[nodeId]
      for (const [eid, edge] of Object.entries(draft.edges)) {
        if (set.has(edge.from[0]) || set.has(edge.to[0])) delete draft.edges[eid]
      }
      for (const [gid, group] of Object.entries(draft.groups)) {
        const members = (group.nodes ?? []).filter((n) => !set.has(n))
        if (members.length === 0) delete draft.groups[gid]
        else if (members.length !== (group.nodes ?? []).length) {
          draft.groups[gid] = { ...group, nodes: members }
        }
      }
    })
  }

  function moveNodes(moves: ReadonlyArray<{ id: string; pos: Pos }>): void {
    if (moves.length === 0) return
    commit(
      'command.move',
      (draft) => {
        for (const { id: nodeId, pos } of moves) {
          const node = draft.nodes[nodeId]
          if (node) draft.nodes[nodeId] = { ...node, pos: [pos[0], pos[1]] }
        }
      },
      {
        coalesce: `move:${moves
          .map((m) => m.id)
          .sort()
          .join(',')}`,
        uiOnly: true,
      },
    )
  }

  function resizeNode(nodeId: string, size: Size, pos?: Pos): void {
    updateNode(nodeId, pos ? { size, pos } : { size }, 'command.resize', {
      coalesce: `resize:${nodeId}`,
      uiOnly: true,
    })
  }

  function setParam(nodeId: string, param: string, value: unknown): void {
    commit(
      'command.edit_param',
      (draft) => {
        const node = draft.nodes[nodeId]
        if (!node) return
        const params = { ...node.params }
        if (value === undefined) delete params[param]
        else params[param] = value
        draft.nodes[nodeId] = { ...node, params }
      },
      { coalesce: `param:${nodeId}:${param}` },
    )
  }

  /** Set several params of one node in a single undo entry (editors' Apply). */
  function setParams(nodeId: string, patch: Record<string, unknown>): void {
    commit('command.edit_param', (draft) => {
      const node = draft.nodes[nodeId]
      if (!node) return
      const params = { ...node.params }
      for (const [name, value] of Object.entries(patch)) {
        if (value === undefined) delete params[name]
        else params[name] = value
      }
      draft.nodes[nodeId] = { ...node, params }
    })
  }

  function setTitle(nodeId: string, title: string | null): void {
    updateNode(nodeId, { title: title?.trim() ? title.trim() : null }, 'command.rename', {
      uiOnly: true,
    })
  }

  function setNotes(nodeId: string, notes: string): void {
    updateNode(nodeId, { notes }, 'command.notes', { coalesce: `notes:${nodeId}`, uiOnly: true })
  }

  function setDisabled(nodeId: string, disabled: boolean): void {
    updateNode(nodeId, { disabled }, disabled ? 'command.bypass' : 'command.enable')
  }

  function setCost(nodeId: string, cost: NodeDoc['cost']): void {
    updateNode(nodeId, { cost: cost ?? null }, 'command.cost')
  }

  function setUi(nodeId: string, patch: Record<string, unknown>): void {
    commit(
      'command.ui',
      (draft) => {
        const node = draft.nodes[nodeId]
        if (node) draft.nodes[nodeId] = { ...node, ui: { ...node.ui, ...patch } }
      },
      { coalesce: `ui:${nodeId}`, uiOnly: true },
    )
  }

  /** Convert a param to an input port (or back; unlinking drops the edge feeding it). */
  function toggleLink(nodeId: string, param: string): void {
    commit('command.link', (draft) => {
      const node = draft.nodes[nodeId]
      if (!node) return
      const linked = node.linked ?? []
      if (linked.includes(param)) {
        draft.nodes[nodeId] = { ...node, linked: linked.filter((p) => p !== param) }
        for (const [eid, edge] of Object.entries(draft.edges)) {
          if (edge.to[0] === nodeId && edge.to[1] === param) delete draft.edges[eid]
        }
      } else {
        draft.nodes[nodeId] = { ...node, linked: [...linked, param] }
      }
    })
  }

  // --- edges ----------------------------------------------------------------------------------

  function validateConnection(query: ConnectionQuery, ignoreEdge?: string): ConnectionVerdict {
    const schema = useNodesSchemaStore()
    return checkConnection(
      { nodes: nodes.value, edges: edges.value, specs: specs.value, types: schema.typeById },
      query,
      ignoreEdge,
    )
  }

  function connect(query: ConnectionQuery): { verdict: ConnectionVerdict; edgeId: string | null } {
    const verdict = validateConnection(query)
    if (!verdict.ok) return { verdict, edgeId: null }
    const edgeId = commit('command.connect', (draft) => {
      // Dropping onto a linkable param converts it to an input port on the fly.
      const target = draft.nodes[query.target]
      const schema = specs.value[target?.type ?? '']
      const isParam = schema?.params.some((p) => p.name === query.targetPort) ?? false
      if (target && isParam && !(target.linked ?? []).includes(query.targetPort)) {
        draft.nodes[query.target] = {
          ...target,
          linked: [...(target.linked ?? []), query.targetPort],
        }
      }
      const eid = freshId('e')
      draft.edges[eid] = {
        from: [query.source, query.sourcePort],
        to: [query.target, query.targetPort],
      }
      return eid
    })
    return { verdict, edgeId }
  }

  function disconnect(edgeIds: readonly string[]): void {
    const present = edgeIds.filter((eid) => edges.value[eid] !== undefined)
    if (present.length === 0) return
    commit('command.disconnect', (draft) => {
      for (const eid of present) delete draft.edges[eid]
    })
  }

  // --- groups ---------------------------------------------------------------------------------

  function groupNodes(ids: readonly string[], title?: string): string | null {
    const members = ids.filter((nodeId) => nodes.value[nodeId] !== undefined)
    if (members.length === 0) return null
    return commit('command.group', (draft) => {
      // A node belongs to at most one group: remove it from any other first.
      const set = new Set(members)
      for (const [gid, group] of Object.entries(draft.groups)) {
        const rest = (group.nodes ?? []).filter((n) => !set.has(n))
        if (rest.length === 0) delete draft.groups[gid]
        else if (rest.length !== (group.nodes ?? []).length)
          draft.groups[gid] = { ...group, nodes: rest }
      }
      const gid = freshId('g')
      const geometry = groupGeometry(draft.nodes, members)
      draft.groups[gid] = {
        title: title ?? '',
        nodes: members,
        color: null,
        ...geometry,
      }
      return gid
    })
  }

  function ungroup(groupIds: readonly string[]): void {
    const present = groupIds.filter((gid) => groups.value[gid] !== undefined)
    if (present.length === 0) return
    commit('command.ungroup', (draft) => {
      for (const gid of present) delete draft.groups[gid]
    })
  }

  function updateGroup(
    groupId: string,
    patch: Partial<CanvasGroup>,
    options?: CommitOptions,
  ): void {
    commit(
      'command.group_edit',
      (draft) => {
        const group = draft.groups[groupId]
        if (group) draft.groups[groupId] = { ...group, ...patch }
      },
      { uiOnly: true, ...options },
    )
  }

  /** Move a group and every member by the same delta. */
  function moveGroup(groupId: string, pos: Pos): void {
    commit(
      'command.move',
      (draft) => {
        const group = draft.groups[groupId]
        if (!group) return
        const [ox, oy] = group.pos ?? pos
        const dx = pos[0] - ox
        const dy = pos[1] - oy
        draft.groups[groupId] = { ...group, pos: [pos[0], pos[1]] }
        for (const nodeId of group.nodes ?? []) {
          const node = draft.nodes[nodeId]
          if (!node) continue
          const [x, y] = node.pos ?? [0, 0]
          draft.nodes[nodeId] = { ...node, pos: [x + dx, y + dy] }
        }
      },
      { coalesce: `move-group:${groupId}`, uiOnly: true },
    )
  }

  /** Recompute a group's geometry from its members (after members moved). */
  function fitGroup(groupId: string): void {
    const group = groups.value[groupId]
    if (!group) return
    const geometry = groupGeometry(nodes.value, group.nodes ?? [])
    if (!geometry) return
    updateGroup(groupId, geometry, { coalesce: `fit-group:${groupId}` })
  }

  function groupOf(nodeId: string): string | null {
    for (const [gid, group] of Object.entries(groups.value)) {
      if ((group.nodes ?? []).includes(nodeId)) return gid
    }
    return null
  }

  // --- subgraphs ------------------------------------------------------------------------------

  /** Open the body of a subgraph instance in the current container (breadcrumb navigation). */
  function enterSubgraph(nodeId: string): boolean {
    const node = nodes.value[nodeId]
    if (!node || !isSubgraphType(node.type)) return false
    if (!subgraphs.value[subgraphIdOf(node.type)]) return false
    path.value = [...path.value, nodeId]
    return true
  }

  /** Go back up; `depth` is how many crumbs to keep (0 = the document root). */
  function exitSubgraph(depth = path.value.length - 1): void {
    path.value = path.value.slice(0, Math.max(0, depth))
  }

  /**
   * Collapse `ids` into a new subgraph and replace them with one instance node. Edges crossing
   * the boundary become named ports; everything happens in one undo entry.
   */
  function collapseToSubgraph(ids: readonly string[], name?: string): string | null {
    const members = ids.filter((nodeId) => nodes.value[nodeId] !== undefined)
    if (members.length === 0) return null
    const instanceId = freshId('sg')
    const subgraphId = freshId('sub')
    const collapsed = collapseSelection(nodes.value, edges.value, members, instanceId, {
      name: name ?? 'Subgraph',
    })
    if (!collapsed) return null
    return commit('command.collapse', (draft) => {
      const set = new Set(members)
      for (const nodeId of members) delete draft.nodes[nodeId]
      for (const eid of Object.keys(draft.edges)) {
        const edge = draft.edges[eid] as EdgeDoc
        if (set.has(edge.from[0]) || set.has(edge.to[0])) delete draft.edges[eid]
      }
      Object.assign(draft.edges, collapsed.edges)
      draft.nodes[instanceId] = { ...collapsed.instance, type: subgraphType(subgraphId) }
      // Members that were grouped leave their group behind.
      for (const [gid, group] of Object.entries(draft.groups)) {
        const rest = (group.nodes ?? []).filter((n) => !set.has(n))
        if (rest.length === 0) delete draft.groups[gid]
        else if (rest.length !== (group.nodes ?? []).length)
          draft.groups[gid] = { ...group, nodes: rest }
      }
      draft.subgraphs = { ...draft.subgraphs, [subgraphId]: collapsed.subgraph }
      return instanceId
    })
  }

  /** Inline a subgraph instance back into the current container, restoring inner positions. */
  function expandSubgraph(nodeId: string): string[] {
    const node = nodes.value[nodeId]
    if (!node || !isSubgraphType(node.type)) return []
    const sg = subgraphs.value[subgraphIdOf(node.type)]
    if (!sg) return []
    const expanded = expandInstance(nodes.value, edges.value, nodeId, sg, hasId)
    if (!expanded) return []
    commit('command.expand', (draft) => {
      delete draft.nodes[nodeId]
      for (const [eid, edge] of Object.entries(draft.edges)) {
        if (edge.from[0] === nodeId || edge.to[0] === nodeId) delete draft.edges[eid]
      }
      Object.assign(draft.nodes, expanded.nodes)
      Object.assign(draft.edges, expanded.edges)
    })
    return Object.values(expanded.idMap)
  }

  /** Rename a subgraph body (the label shown on every instance and in the breadcrumb). */
  function renameSubgraph(subgraphId: string, title: string): void {
    const next = title.trim()
    if (!next) return
    commit('command.rename', (draft) => {
      const sg = draft.subgraphs[subgraphId]
      if (sg) draft.subgraphs = { ...draft.subgraphs, [subgraphId]: { ...sg, name: next } }
    })
  }

  /** Lift an inner node's param so instances of `subgraphId` can set it. */
  function promoteSubgraphParam(subgraphId: string, node: string, param: string): void {
    commit('command.promote', (draft) => {
      const sg = draft.subgraphs[subgraphId]
      if (!sg) return
      const promoted = sg.promoted ?? []
      const already = promoted.some((p) => p.node === node && p.param === param)
      draft.subgraphs = {
        ...draft.subgraphs,
        [subgraphId]: {
          ...sg,
          promoted: already
            ? promoted.filter((p) => !(p.node === node && p.param === param))
            : [...promoted, { node, param, label: null, group: null, order: promoted.length }],
        },
      }
    })
  }

  // --- promoted params, views and layouts (design 7.1, 8.4) -----------------------------------

  /**
   * Promotion, pinning and layouts are **document-level**: their refs address root nodes, so
   * every function here works on `draft` itself rather than the `scoped()` view a subgraph body
   * would give. They go through `commit()` like any other mutation, so a layout edit is undoable
   * and lands in the same autosave.
   */
  function promotedIndex(node: string, param: string): number {
    return (doc.value?.promoted ?? []).findIndex((p) => p.node === node && p.param === param)
  }

  function isPromoted(node: string, param: string): boolean {
    return promotedIndex(node, param) >= 0
  }

  function promotedOf(node: string, param: string): PromotedDoc | undefined {
    return promotedList.value.find((p) => p.node === node && p.param === param)
  }

  /** Renumber `order` to the array position so a reordered list survives a round-trip. */
  function renumber(entries: readonly PromotedDoc[]): PromotedDoc[] {
    return entries.map((entry, index) => ({ ...entry, order: index + 1 }))
  }

  /** Lift a node param into the layouts (no-op when it is already promoted). */
  function promoteParam(node: string, param: string, patch: Partial<PromotedDoc> = {}): void {
    if (isPromoted(node, param)) return
    commit('command.promote', (draft) => {
      draft.promoted = renumber([
        ...draft.promoted,
        { node, param, label: null, group: null, order: draft.promoted.length + 1, ...patch },
      ])
    })
  }

  /** Drop a promoted param and every layout item that referenced it. */
  function unpromoteParam(node: string, param: string): void {
    if (!isPromoted(node, param)) return
    const ref = refOf({ node, param })
    commit('command.unpromote', (draft) => {
      draft.promoted = renumber(
        draft.promoted.filter((p) => !(p.node === node && p.param === param)),
      )
      draft.layouts = dropRefFromLayouts(draft.layouts, `${PROMOTED_PREFIX}${ref}`)
    })
  }

  /** Star toggle: returns whether the param is promoted afterwards. */
  function togglePromoted(node: string, param: string, patch: Partial<PromotedDoc> = {}): boolean {
    if (isPromoted(node, param)) {
      unpromoteParam(node, param)
      return false
    }
    promoteParam(node, param, patch)
    return true
  }

  /** Edit a promoted entry's label, group, help text or order. */
  function updatePromoted(node: string, param: string, patch: Partial<PromotedDoc>): void {
    if (!isPromoted(node, param)) return
    commit(
      'command.promote_edit',
      (draft) => {
        draft.promoted = draft.promoted.map((entry) =>
          entry.node === node && entry.param === param ? { ...entry, ...patch } : entry,
        )
      },
      { coalesce: `promoted:${refOf({ node, param })}` },
    )
  }

  /**
   * Move a promoted param to `index` in the flat list, optionally into another `group`
   * (the Parameters panel's drag ordering).
   */
  function movePromoted(node: string, param: string, index: number, group?: string | null): void {
    const from = promotedList.value.findIndex((p) => p.node === node && p.param === param)
    if (from < 0) return
    commit('command.promote_order', (draft) => {
      const ordered = [...promotedList.value]
      const [entry] = ordered.splice(from, 1)
      if (!entry) return
      const at = Math.max(0, Math.min(index, ordered.length))
      ordered.splice(at, 0, group === undefined ? entry : { ...entry, group })
      draft.promoted = renumber(ordered)
    })
  }

  function viewIndex(nodeId: string, port: string): number {
    return (doc.value?.views ?? []).findIndex((v) => v.node === nodeId && v.port === port)
  }

  function isPinned(nodeId: string, port: string): boolean {
    return viewIndex(nodeId, port) >= 0
  }

  function viewOf(nodeId: string, port: string): ViewDoc | undefined {
    return (doc.value?.views ?? []).find((v) => v.node === nodeId && v.port === port)
  }

  function viewById(viewId: string): ViewDoc | undefined {
    return (doc.value?.views ?? []).find((v) => v.id === viewId)
  }

  /** Pin a node output as a view; returns its id (the existing one when already pinned). */
  function pinView(nodeId: string, port: string, patch: Partial<ViewDoc> = {}): string {
    const existing = viewOf(nodeId, port)
    if (existing) return existing.id
    const viewId = freshId('v')
    commit('command.pin_view', (draft) => {
      draft.views = [...draft.views, { id: viewId, node: nodeId, port, kind: null, ...patch }]
    })
    return viewId
  }

  /** Unpin a view and drop it from every layout. */
  function unpinView(viewId: string): void {
    if (!viewById(viewId)) return
    commit('command.unpin_view', (draft) => {
      draft.views = draft.views.filter((v) => v.id !== viewId)
      draft.layouts = dropRefFromLayouts(draft.layouts, `${VIEW_PREFIX}${viewId}`)
    })
  }

  /** Pin toggle: returns whether the output is pinned afterwards. */
  function togglePinned(nodeId: string, port: string, patch: Partial<ViewDoc> = {}): boolean {
    const existing = viewOf(nodeId, port)
    if (existing) {
      unpinView(existing.id)
      return false
    }
    pinView(nodeId, port, patch)
    return true
  }

  function updateView(viewId: string, patch: Partial<ViewDoc>): void {
    if (!viewById(viewId)) return
    commit(
      'command.view_edit',
      (draft) => {
        draft.views = draft.views.map((v) => (v.id === viewId ? { ...v, ...patch } : v))
      },
      { coalesce: `view:${viewId}` },
    )
  }

  /** Write (or with `null` remove) one layout section as a single undoable command. */
  function setLayout(name: string, section: unknown, label = 'command.layout'): void {
    commit(label, (draft) => {
      const next = { ...draft.layouts }
      if (section === null || section === undefined) delete next[name]
      else next[name] = section
      draft.layouts = next
    })
  }

  /** A standalone document holding one subgraph plus an instance: a reusable blueprint. */
  function blueprintOf(subgraphId: string, title?: string): WorkflowDoc | null {
    const sg = subgraphs.value[subgraphId]
    if (!sg) return null
    const blueprint = emptyDoc(title ?? sg.name ?? 'Blueprint')
    blueprint.subgraphs = { [subgraphId]: clone(sg) }
    blueprint.nodes = {
      main: { ...nodeFromSpec(specs.value[subgraphType(subgraphId)] as NodeSpec, [0, 0]) },
    }
    blueprint.meta = { blueprint: { subgraph: subgraphId } }
    return blueprint
  }

  /** Insert a blueprint document's subgraph into this document as one instance node. */
  function insertBlueprint(source: WorkflowDoc, pos: Pos): string | null {
    const entries = Object.entries(source.subgraphs ?? {})
    const first = entries[0]
    if (!first) return null
    const [sourceId, sg] = first
    const subgraphId = hasId(sourceId) ? freshId('sub') : sourceId
    const instanceId = freshId('sg')
    return commit('command.insert_blueprint', (draft) => {
      draft.subgraphs = { ...draft.subgraphs, [subgraphId]: clone(sg) }
      draft.nodes[instanceId] = {
        type: subgraphType(subgraphId),
        version: null,
        title: sg.name || null,
        pos,
        size: null,
        params: {},
        linked: [],
        ui: {},
        cost: null,
        disabled: false,
        notes: '',
      }
      return instanceId
    })
  }

  // --- clipboard ------------------------------------------------------------------------------

  function copy(ids: readonly string[]): ClipboardPayload | null {
    return copySelection(nodes.value, edges.value, ids)
  }

  function paste(payload: ClipboardPayload, options: { at?: Pos; offset?: Pos } = {}): string[] {
    const prepared = preparePaste(payload, hasId, options)
    const ids = Object.keys(prepared.nodes)
    if (ids.length === 0) return []
    commit('command.paste', (draft) => {
      Object.assign(draft.nodes, prepared.nodes)
      Object.assign(draft.edges, prepared.edges)
    })
    return ids
  }

  function duplicate(ids: readonly string[]): string[] {
    const payload = copy(ids)
    if (!payload) return []
    const prepared = preparePaste(payload, hasId, { offset: [40, 40] })
    const created = Object.keys(prepared.nodes)
    commit('command.duplicate', (draft) => {
      Object.assign(draft.nodes, prepared.nodes)
      Object.assign(draft.edges, prepared.edges)
    })
    return created
  }

  // --- document metadata ----------------------------------------------------------------------

  function rename(title: string): void {
    const next = title.trim()
    if (!next || next === doc.value?.name) return
    commit('command.rename_workflow', (draft) => {
      draft.name = next
    })
  }

  function setDescription(description: string): void {
    commit(
      'command.describe',
      (draft) => {
        draft.description = description
      },
      { coalesce: 'describe' },
    )
  }

  /** Replace the whole document content (version restore) as one undoable command. */
  function replaceContent(source: WorkflowDoc): void {
    const incoming = normalize(source)
    commit('command.restore', (draft) => {
      draft.name = incoming.name
      draft.description = incoming.description
      draft.nodes = { ...incoming.nodes }
      draft.edges = { ...incoming.edges }
      draft.groups = { ...(incoming.groups as Record<string, CanvasGroup> | undefined) }
      draft.subgraphs = { ...incoming.subgraphs }
      draft.promoted = [...(incoming.promoted ?? [])]
      draft.views = [...(incoming.views ?? [])]
      draft.layouts = { ...(incoming.layouts as Record<string, unknown> | undefined) }
    })
  }

  // --- autosave -------------------------------------------------------------------------------

  function cancelScheduledSave(): void {
    if (saveTimer !== null) {
      clearTimeout(saveTimer)
      saveTimer = null
    }
  }

  function scheduleSave(): void {
    cancelScheduledSave()
    saveState.value = 'pending'
    saveTimer = setTimeout(() => {
      saveTimer = null
      void saveNow()
    }, autosaveDelayMs.value)
  }

  /** Persist immediately (awaits an in-flight save first). Resolves when the store is clean. */
  async function saveNow(): Promise<void> {
    cancelScheduledSave()
    if (saving) await saving
    if (!doc.value || !isDirty.value) {
      if (saveState.value === 'pending') saveState.value = savedSeq.value === 0 ? 'clean' : 'saved'
      return
    }
    saving = performSave()
    let ok: boolean
    try {
      ok = await saving
    } finally {
      saving = null
    }
    // Edits that arrived during the request need another round; failures wait for the next edit.
    if (ok && isDirty.value && doc.value) await saveNow()
  }

  async function performSave(): Promise<boolean> {
    const current = doc.value
    if (!current) return false
    const seq = changeSeq.value
    saveState.value = 'saving'
    saveError.value = null
    try {
      const saved = await api.putWorkflow(clone(current) as WorkflowDoc)
      if (doc.value === current) {
        // Adopt the server-maintained timestamps without recording a command.
        current.meta = { ...current.meta, ...saved.doc.meta }
        savedSeq.value = seq
        lastSavedAt.value = Date.now()
        saveState.value = changeSeq.value === seq ? 'saved' : 'pending'
        layoutErrors.value = saved.layout_errors ?? []
        useExecutionStore().setIssues(saved.node_errors as NodeErrors)
      }
      return true
    } catch (err) {
      saveError.value = err instanceof Error ? err.message : String(err)
      saveState.value = 'error'
      return false
    }
  }

  return {
    doc,
    nodes,
    edges,
    groups,
    subgraphs,
    specs,
    specFor,
    path,
    breadcrumbs,
    openSubgraphId,
    id,
    name,
    isOpen,
    nodeCount,
    undoStack,
    redoStack,
    canUndo,
    canRedo,
    undoLabel,
    redoLabel,
    saveState,
    saveError,
    lastSavedAt,
    isDirty,
    changeSeq,
    savedSeq,
    autosaveDelayMs,
    coalesceWindowMs,
    autosaveEnabled,
    load,
    close,
    open,
    create,
    commit,
    transaction,
    undo,
    redo,
    addNode,
    removeNodes,
    moveNodes,
    resizeNode,
    setParam,
    setParams,
    setTitle,
    setNotes,
    setDisabled,
    setCost,
    setUi,
    toggleLink,
    validateConnection,
    connect,
    disconnect,
    groupNodes,
    ungroup,
    updateGroup,
    moveGroup,
    fitGroup,
    groupOf,
    enterSubgraph,
    exitSubgraph,
    collapseToSubgraph,
    expandSubgraph,
    renameSubgraph,
    promoteSubgraphParam,
    rootNodes,
    promotedList,
    promotedGroups,
    views,
    layouts,
    layoutErrors,
    isPromoted,
    promotedOf,
    promoteParam,
    unpromoteParam,
    togglePromoted,
    updatePromoted,
    movePromoted,
    isPinned,
    viewOf,
    viewById,
    pinView,
    unpinView,
    togglePinned,
    updateView,
    setLayout,
    blueprintOf,
    insertBlueprint,
    copy,
    paste,
    duplicate,
    rename,
    setDescription,
    replaceContent,
    scheduleSave,
    saveNow,
  }
})
