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
   * Write the export refs into the workspace; returns the folder or `null` on failure.
   *
   * Exporting flushes the pending edits first, and a flush means a re-run, so the export has to
   * wait for the values it is about to write. That wait is the **server's**: it is the only place
   * that knows, because these node states arrive over the event socket after the server has
   * already changed them. Two attempts at waiting here both failed on the nightly's slowest
   * runner -- a fixed sleep the auto-run debounce outran, then a poll on node states that were
   * simply the previous run's -- and the second one also delayed the export by its own timeout.
   * So this posts and lets `Scheduler.settle` hold the request.
   */
  async function exportResults(): Promise<string | null> {
    const id = workflow.id
    if (!id || exportRefs.value.length === 0) return null
    await workflow.saveNow()
    try {
      const result = await api.exportOutputs(id, {
        refs: exportRefs.value,
        overwrite: true,
        // Ask for the values, not for whatever is cached: a cost-gated node is `stale` until
        // someone runs it explicitly, and a mode has no canvas to press Run on.
        run: true,
      })
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
    exportRefs,
    exportResults,
  }
}
