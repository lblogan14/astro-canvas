/**
 * Batch mode state: the row table, the column → node-param mapping, what to collect, and the
 * live state of the running batch (`batch.row` events plus a final `GET .../batch/{id}` for the
 * assembled results grid).
 *
 * The mapping is kept here rather than in the document so an ad-hoc batch does not dirty the
 * workflow; `saveLayout()` writes it back into `layouts.batch` when the user asks.
 */
import { computed, ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'

import { api, errorMessage } from '@/api/client'
import type { BatchInfo, BatchRowState, BatchSpec } from '@/api/types'
import type { BatchFinishedEvent, BatchRowEvent, BatchStartedEvent } from '@/api/events'
import { type Row, parseDelimited, parseSpecguiBatch, suggestMapping } from '@/modes/batchTable'
import { useWorkflowStore } from './workflow'

export type { Row }

export interface RowState {
  state: BatchRowState
  error: string | null
  elapsedMs: number | null
  outputs: Record<string, unknown>
}

const IDLE: RowState = { state: 'pending', error: null, elapsedMs: null, outputs: {} }

/** `"<node>.<param>"` refs a document offers as batch columns: its promoted params first. */
export function bindableRefs(
  promoted: ReadonlyArray<{ node: string; param: string }>,
  nodes: Readonly<Record<string, { params?: Record<string, unknown> }>>,
): string[] {
  const refs = promoted.map((p) => `${p.node}.${p.param}`)
  for (const [nodeId, node] of Object.entries(nodes)) {
    for (const param of Object.keys(node.params ?? {})) {
      const ref = `${nodeId}.${param}`
      if (!refs.includes(ref)) refs.push(ref)
    }
  }
  return refs
}

export const useBatchStore = defineStore('batch', () => {
  const columns = ref<string[]>([])
  const rows = shallowRef<Row[]>([])
  /** column name → `"<node>.<param>"`; unmapped columns travel with the row but bind nothing. */
  const mapping = ref<Record<string, string>>({})
  /** `"<node>.<port>"` refs whose values become result columns. */
  const collect = ref<string[]>([])
  const continueOnError = ref(true)
  const maxWorkers = ref<number | null>(null)

  const batchId = ref<string | null>(null)
  const status = ref<'idle' | 'running' | 'done' | 'error' | 'cancelled'>('idle')
  const rowStates = ref<Record<number, RowState>>({})
  const results = shallowRef<BatchInfo['results'] | null>(null)
  const error = ref<string | null>(null)
  const selected = ref<Set<number>>(new Set())

  const isRunning = computed(() => status.value === 'running')
  const rowCount = computed(() => rows.value.length)
  const mappedColumns = computed(() => columns.value.filter((name) => mapping.value[name]))
  const counts = computed(() => {
    const totals: Record<string, number> = {}
    for (let i = 0; i < rows.value.length; i += 1) {
      const state = rowStates.value[i]?.state ?? 'pending'
      totals[state] = (totals[state] ?? 0) + 1
    }
    return totals
  })

  function stateOf(index: number): RowState {
    return rowStates.value[index] ?? IDLE
  }

  // --- table editing ---------------------------------------------------------------------------

  function setTable(next: { columns: string[]; rows: Row[] }, remap = true): void {
    columns.value = [...next.columns]
    rows.value = next.rows.map((row) => ({ ...row }))
    if (remap) mapping.value = suggestMapping(next.columns, useWorkflowStore().nodes)
    reset()
  }

  function addRow(template?: Row): void {
    const base: Row = {}
    for (const name of columns.value) base[name] = template?.[name] ?? null
    rows.value = [...rows.value, base]
  }

  function removeRows(indices: readonly number[]): void {
    const drop = new Set(indices)
    rows.value = rows.value.filter((_, index) => !drop.has(index))
    selected.value = new Set()
    reset()
  }

  function setCell(index: number, column: string, value: Row[string]): void {
    const row = rows.value[index]
    if (!row) return
    const next = [...rows.value]
    next[index] = { ...row, [column]: value }
    rows.value = next
  }

  function addColumn(name: string, ref?: string): void {
    const column = name.trim()
    if (!column || columns.value.includes(column)) return
    columns.value = [...columns.value, column]
    rows.value = rows.value.map((row) => ({ ...row, [column]: null }))
    if (ref) mapping.value = { ...mapping.value, [column]: ref }
  }

  function removeColumn(name: string): void {
    columns.value = columns.value.filter((c) => c !== name)
    const next = { ...mapping.value }
    delete next[name]
    mapping.value = next
  }

  function setMapping(column: string, ref: string | null): void {
    const next = { ...mapping.value }
    if (ref) next[column] = ref
    else delete next[column]
    mapping.value = next
  }

  /** Import CSV/ECSV/TSV or a specgui `master_batch_table` export (CSV or JSON). */
  function importText(text: string): { rows: number; preset: boolean } {
    const specgui = parseSpecguiBatch(text)
    const table = specgui ?? parseDelimited(text)
    setTable(table)
    return { rows: table.rows.length, preset: specgui !== null }
  }

  /** Seed the table from the open document's `layouts.batch` (columns, collect and mapping). */
  function loadLayout(): boolean {
    const layout = useWorkflowStore().doc?.layouts?.['batch'] as
      | { columns?: unknown[]; collect?: unknown[]; max_workers?: number | null; rows?: string }
      | undefined
    if (!layout) return false
    const nextColumns: string[] = []
    const nextMapping: Record<string, string> = {}
    for (const entry of layout.columns ?? []) {
      const ref =
        typeof entry === 'string' ? entry : String((entry as { promoted?: string }).promoted ?? '')
      if (!ref) continue
      const column =
        typeof entry === 'string' ? entry : String((entry as { column?: string }).column ?? ref)
      nextColumns.push(column)
      nextMapping[column] = ref
    }
    columns.value = nextColumns
    mapping.value = nextMapping
    collect.value = (layout.collect ?? []).map((entry) =>
      typeof entry === 'string'
        ? entry
        : `${(entry as { node?: string }).node}.${(entry as { port?: string }).port}`,
    )
    maxWorkers.value = layout.max_workers ?? null
    if (rows.value.length === 0) addRow()
    reset()
    // A template may point at a bundled row table; it fills the grid once it arrives.
    if (layout.rows) void loadRows(layout.rows)
    return true
  }

  /** Replace the rows with a workspace file's table, keeping the layout's column mapping. */
  async function loadRows(path: string): Promise<number> {
    try {
      const table = parseDelimited(await api.fetchWorkspaceText(path))
      if (table.rows.length === 0) return 0
      const known = new Set(columns.value)
      columns.value = [...columns.value, ...table.columns.filter((c) => !known.has(c))]
      rows.value = table.rows
      reset()
      return table.rows.length
    } catch (err) {
      error.value = errorMessage(err)
      return 0
    }
  }

  /** Write the current columns/collect back into the document's `layouts.batch`. */
  function saveLayout(): void {
    const workflow = useWorkflowStore()
    const doc = workflow.doc
    if (!doc) return
    doc.layouts = {
      ...doc.layouts,
      batch: {
        columns: columns.value
          .filter((name) => mapping.value[name])
          .map((name) => ({ promoted: mapping.value[name], column: name })),
        collect: [...collect.value],
        max_workers: maxWorkers.value,
        continue_on_error: continueOnError.value,
      },
    }
    workflow.scheduleSave()
  }

  /** Apply one row's mapped values to the canvas so it can be inspected node by node. */
  function openInCanvas(index: number): boolean {
    const row = rows.value[index]
    if (!row) return false
    const workflow = useWorkflowStore()
    const patches = new Map<string, Record<string, unknown>>()
    for (const [column, ref] of Object.entries(mapping.value)) {
      const dot = ref.lastIndexOf('.')
      const node = ref.slice(0, dot)
      const param = ref.slice(dot + 1)
      if (!node || !param || !workflow.nodes[node]) continue
      patches.set(node, { ...patches.get(node), [param]: row[column] })
    }
    if (patches.size === 0) return false
    workflow.transaction('command.batch_row', () => {
      for (const [node, patch] of patches) workflow.setParams(node, patch)
    })
    return true
  }

  // --- running ---------------------------------------------------------------------------------

  function reset(): void {
    batchId.value = null
    status.value = 'idle'
    rowStates.value = {}
    results.value = null
    error.value = null
  }

  function spec(): BatchSpec {
    const bindings = columns.value
      .filter((name) => mapping.value[name])
      .map((name) => {
        const ref = mapping.value[name] as string
        const dot = ref.lastIndexOf('.')
        return { node: ref.slice(0, dot), param: ref.slice(dot + 1), column: name }
      })
    return {
      bindings,
      collect: collect.value.map((ref) => {
        const dot = ref.lastIndexOf('.')
        return { node: ref.slice(0, dot), port: ref.slice(dot + 1), prefix: null }
      }),
      max_workers: maxWorkers.value,
      continue_on_error: continueOnError.value,
    }
  }

  /** Run every row, or only `indices` (Run selected). */
  async function run(indices?: readonly number[]): Promise<string | null> {
    const workflow = useWorkflowStore()
    const id = workflow.id
    if (!id || rows.value.length === 0 || collect.value.length === 0) return null
    await workflow.saveNow()
    const picked = indices && indices.length ? [...indices].sort((a, b) => a - b) : null
    const payloadRows = (picked ?? rows.value.map((_, i) => i)).map((i) => rows.value[i] as Row)
    reset()
    // Row indices in the request are dense; remember which table rows they belong to.
    indexMap = picked ?? payloadRows.map((_, i) => i)
    status.value = 'running'
    try {
      const info = await api.startBatch(id, { rows: payloadRows, spec: spec() })
      batchId.value = info.batch_id
      return info.batch_id
    } catch (err) {
      status.value = 'error'
      error.value = errorMessage(err)
      return null
    }
  }

  async function cancel(): Promise<void> {
    const id = useWorkflowStore().id
    if (!id || !batchId.value) return
    try {
      await api.cancelBatch(id, batchId.value)
    } catch (err) {
      error.value = errorMessage(err)
    }
  }

  /** Dense request index → table row index (Run selected leaves gaps). */
  let indexMap: number[] = []

  function applyMessage(message: BatchStartedEvent | BatchRowEvent | BatchFinishedEvent): void {
    if (batchId.value && message.batch_id !== batchId.value) return
    if (message.type === 'batch.started') {
      batchId.value = message.batch_id
      status.value = 'running'
      return
    }
    if (message.type === 'batch.row') {
      const index = indexMap[message.row] ?? message.row
      rowStates.value = {
        ...rowStates.value,
        [index]: {
          state: message.state,
          error: message.error,
          elapsedMs: message.elapsed_ms,
          outputs: message.outputs,
        },
      }
      return
    }
    status.value = message.status === 'running' ? 'done' : message.status
    void refreshResults()
  }

  async function refreshResults(): Promise<void> {
    const id = useWorkflowStore().id
    if (!id || !batchId.value) return
    try {
      const info = await api.getBatch(id, batchId.value)
      results.value = info.results
    } catch (err) {
      error.value = errorMessage(err)
    }
  }

  function toggleSelected(index: number): void {
    const next = new Set(selected.value)
    if (next.has(index)) next.delete(index)
    else next.add(index)
    selected.value = next
  }

  return {
    columns,
    rows,
    mapping,
    mappedColumns,
    collect,
    continueOnError,
    maxWorkers,
    batchId,
    status,
    rowStates,
    results,
    error,
    selected,
    isRunning,
    rowCount,
    counts,
    stateOf,
    setTable,
    addRow,
    removeRows,
    setCell,
    addColumn,
    removeColumn,
    setMapping,
    importText,
    loadLayout,
    loadRows,
    saveLayout,
    openInCanvas,
    reset,
    spec,
    run,
    cancel,
    applyMessage,
    refreshResults,
    toggleSelected,
  }
})
