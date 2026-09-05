/**
 * What App, Wizard and Dashboard modes all need: the document's promoted params and views
 * resolved against the **root** document, the run state of the nodes an item touches, and the
 * three actions a finished GUI offers (run, cancel, export).
 *
 * Layout state stays out of the document until the user presses *Save layout*, the same rule
 * `stores/batch.ts` follows, so opening a template in a mode never dirties it.
 */
import { computed } from 'vue'

import type { NodeIssue, NodeState } from '@/api/types'
import { api } from '@/api/client'
import { useExecutionStore } from '@/stores/execution'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'
import { type ResolveContext, type ResolvedItem, resolveItems, splitRef } from './layouts'

/** How far along a set of nodes is, as one state a header can show. */
export type GroupState = 'idle' | 'running' | 'error' | 'done'

export function useMode() {
  const workflow = useWorkflowStore()
  const execution = useExecutionStore()
  const session = useSessionStore()
  const ui = useUiStore()

  const ctx = computed<ResolveContext>(() => ({
    promoted: workflow.promotedList,
    views: workflow.views,
    nodes: workflow.rootNodes,
    specs: workflow.specs,
  }))

  function resolve(items: readonly unknown[]): { resolved: ResolvedItem[]; missing: string[] } {
    return resolveItems(items, ctx.value)
  }

  /** The nodes a list of items depends on, in item order. */
  function nodesOf(items: readonly ResolvedItem[]): string[] {
    return [...new Set(items.map((item) => item.node))]
  }

  function stateOf(nodeId: string): NodeState {
    return execution.node(nodeId).state
  }

  function issuesOf(nodeId: string): NodeIssue[] {
    return execution.issuesFor(nodeId)
  }

  /**
   * One state for a group of nodes: `error` if any failed or has a compile issue, `running`
   * while any is queued or running, `done` only when every one of them is done.
   */
  function groupState(nodeIds: readonly string[]): GroupState {
    if (nodeIds.length === 0) return 'done'
    let done = 0
    for (const id of nodeIds) {
      const state = stateOf(id)
      if (state === 'error' || issuesOf(id).length > 0) return 'error'
      if (state === 'running' || state === 'queued') return 'running'
      if (state === 'done') done += 1
    }
    return done === nodeIds.length ? 'done' : 'idle'
  }

  /** Compile issues plus run errors of the given nodes, flattened for a mode's message list. */
  function problemsOf(nodeIds: readonly string[]): { node: string; message: string }[] {
    const out: { node: string; message: string }[] = []
    for (const id of nodeIds) {
      for (const issue of issuesOf(id)) out.push({ node: id, message: issue.message })
      const error = execution.node(id).error
      if (error) out.push({ node: id, message: error.message })
    }
    return out
  }

  function setParam(nodeId: string, param: string, value: unknown): void {
    workflow.setParam(nodeId, param, value)
  }

  const running = computed(() => execution.isRunning)
  const autoRun = computed(() => execution.autoRun)

  async function run(targets?: string[] | null): Promise<void> {
    if (!workflow.isOpen) return
    try {
      await session.run(targets ?? null)
    } catch (error) {
      ui.notify(error instanceof Error ? error.message : String(error), 'error')
    }
  }

  async function cancel(): Promise<void> {
    await session.cancel()
  }

  /**
   * What "Export results" writes: the batch layout's `collect` list when the document has one,
   * else the pinned views, else every leaf output. Refs are `"<node>.<port>"`.
   */
  const exportRefs = computed<string[]>(() => {
    const batch = workflow.layouts['batch'] as { collect?: unknown[] } | undefined
    const collected = (batch?.collect ?? [])
      .map((entry) =>
        typeof entry === 'string'
          ? entry
          : `${(entry as { node?: string }).node}.${(entry as { port?: string }).port}`,
      )
      .filter((ref) => ref.includes('.') && !ref.includes('undefined'))
    if (collected.length > 0) return collected
    if (workflow.views.length > 0) return workflow.views.map((view) => `${view.node}.${view.port}`)
    const consumed = new Set(
      Object.values(workflow.doc?.edges ?? {}).map((edge) => String(edge.from[0])),
    )
    const refs: string[] = []
    for (const [nodeId, node] of Object.entries(workflow.rootNodes)) {
      if (consumed.has(nodeId)) continue
      for (const port of workflow.specFor(node)?.outputs ?? []) refs.push(`${nodeId}.${port.name}`)
    }
    return refs
  })

  /**
   * Wait until the nodes named in `refs` have something to export.
   *
   * Sleeping for a fixed moment and then watching `isRunning` is a race: the auto-run debounce is
   * armed by the server 250 ms after the save lands, so on a slow machine nothing was running yet
   * when the wait expired, and the export asked for an output that was still being recomputed --
   * `"ew.out has no cached output"`. So wait for the nodes themselves. `dirty` only counts while
   * auto-run is on, because a dirty node nobody is going to run would otherwise hold the export
   * until the timeout; those refs are reported as skipped instead, which is the honest answer.
   *
   * The server waits for the same thing on its own (`Scheduler.settle`), and that is the wait
   * that has to be right: these states arrive over the event socket *after* the server has
   * changed them, so this one only keeps the request from going out while the graph is visibly
   * still moving.
   */
  async function settle(refs: string[] = [], timeoutMs = 60000): Promise<void> {
    const ids = [...new Set(refs.map((ref) => ref.slice(0, ref.lastIndexOf('.'))))]
    const pending = (): boolean =>
      execution.isRunning ||
      ids.some((id) => {
        const state = execution.node(id).state
        return state === 'queued' || state === 'running' || (state === 'dirty' && execution.autoRun)
      })

    const deadline = Date.now() + timeoutMs
    // Nothing pending in the first moment after a save means the debounce has not armed yet, not
    // that the graph is settled -- so the first reading only counts once it could have.
    const armed = Date.now() + 600
    while (Date.now() < deadline) {
      if (!pending() && Date.now() >= armed) return
      await new Promise((resolve) => setTimeout(resolve, 100))
    }
  }

  /**
   * Write the export refs into the workspace; returns the folder or `null` on failure.
   *
   * Exporting flushes pending edits first, and an edit means a re-run: exporting into the
   * middle of it would write whatever was still cached, so the run is waited out.
   */
  async function exportResults(): Promise<string | null> {
    const id = workflow.id
    if (!id || exportRefs.value.length === 0) return null
    await workflow.saveNow()
    await settle(exportRefs.value)
    try {
      const result = await api.exportOutputs(id, { refs: exportRefs.value, overwrite: true })
      const written = result.files?.length ?? 0
      if (written === 0) {
        ui.notify(String(result.skipped?.[0]?.message ?? ''), 'error')
        return null
      }
      return result.dir
    } catch (error) {
      ui.notify(error instanceof Error ? error.message : String(error), 'error')
      return null
    }
  }

  return {
    ctx,
    resolve,
    nodesOf,
    stateOf,
    issuesOf,
    groupState,
    problemsOf,
    setParam,
    splitRef,
    running,
    autoRun,
    run,
    cancel,
    settle,
    exportRefs,
    exportResults,
  }
}
