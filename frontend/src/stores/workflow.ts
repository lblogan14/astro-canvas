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
import type { EdgeDoc, GroupDoc, NodeDoc, NodeErrors, NodeSpec, WorkflowDoc } from '@/api/types'
import { type ClipboardPayload, copySelection, preparePaste } from '@/canvas/clipboard'
import { type ConnectionQuery, type ConnectionVerdict, checkConnection } from '@/canvas/compat'
import { clone } from '@/lib/deepEqual'
import { newId } from '@/lib/ids'
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
  }
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
  const lastSavedAt = ref<number | null>(null)
  /** Increments on every change; compared against the sequence a save started from. */
  const changeSeq = ref(0)
  const savedSeq = ref(0)
  const autosaveDelayMs = ref(1000)
  const coalesceWindowMs = ref(800)
  const autosaveEnabled = ref(true)
  /** Commands within one `transaction()` fold into a single undo entry. */
  let transactionDepth = 0
  let transactionBefore: DocCore | null = null
  let transactionLabel = ''
  let saveTimer: ReturnType<typeof setTimeout> | null = null
  let saving: Promise<boolean> | null = null

  const nodes = computed<Record<string, NodeDoc>>(() => doc.value?.nodes ?? {})
  const edges = computed<Record<string, EdgeDoc>>(() => doc.value?.edges ?? {})
  const groups = computed<Record<string, CanvasGroup>>(
    () => (doc.value?.groups ?? {}) as Record<string, CanvasGroup>,
  )
  const id = computed(() => doc.value?.id ?? null)
  const name = computed(() => doc.value?.name ?? '')
  const isOpen = computed(() => doc.value !== null)
  const canUndo = computed(() => undoStack.value.length > 0)
  const canRedo = computed(() => redoStack.value.length > 0)
  const undoLabel = computed(() => undoStack.value[undoStack.value.length - 1]?.label ?? null)
  const redoLabel = computed(() => redoStack.value[redoStack.value.length - 1]?.label ?? null)
  const isDirty = computed(() => changeSeq.value !== savedSeq.value)
  const nodeCount = computed(() => Object.keys(nodes.value).length)

  // --- document lifecycle ---------------------------------------------------------------------

  function normalize(input: WorkflowDoc): WorkflowDoc {
    const copy = clone(input)
    copy.nodes ??= {}
    copy.edges ??= {}
    copy.groups ??= {}
    copy.meta ??= {}
    copy.id ??= newId('wf')
    return copy
  }

  /** Replace the open document (no undo history, not dirty). */
  function load(input: WorkflowDoc): void {
    cancelScheduledSave()
    doc.value = normalize(input)
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
    const result = mutate(draft)
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
    return (
      !!d &&
      (candidate in (d.nodes ?? {}) ||
        candidate in (d.edges ?? {}) ||
        candidate in (d.groups ?? {}))
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
      { nodes: nodes.value, edges: edges.value, specs: schema.byId, types: schema.typeById },
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
      const schema = useNodesSchemaStore().byId[target?.type ?? '']
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
