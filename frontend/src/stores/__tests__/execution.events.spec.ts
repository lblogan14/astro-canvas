import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import type { EngineEvent, NodeStatusEvent } from '@/api/events'
import { MAX_LOG, idleExecution, useExecutionStore } from '@/stores/execution'

const WF = 'wf1'

function status(nodeId: string, patch: Partial<NodeStatusEvent> = {}): NodeStatusEvent {
  return {
    type: 'node.status',
    ts: 1,
    workflow_id: WF,
    node_id: nodeId,
    state: 'done',
    run_id: 'r1',
    cache_hit: false,
    elapsed_ms: 12,
    cost_class: 'cheap',
    stale: false,
    ...patch,
  }
}

describe('execution store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('returns idle records for unknown nodes and applies node.status', () => {
    const ex = useExecutionStore()
    expect(ex.node('x')).toEqual(idleExecution())
    ex.applyEngineEvent(status('a', { state: 'running' }))
    expect(ex.node('a').state).toBe('running')
    ex.applyEngineEvent({
      type: 'node.progress',
      ts: 2,
      workflow_id: WF,
      node_id: 'a',
      frac: 0.5,
      message: 'half',
    })
    expect(ex.node('a').progress).toEqual({ frac: 0.5, message: 'half' })
    ex.applyEngineEvent(status('a', { state: 'done', cache_hit: true, elapsed_ms: 3 }))
    expect(ex.node('a')).toMatchObject({
      state: 'done',
      cacheHit: true,
      elapsedMs: 3,
      progress: null,
    })
  })

  it('takes the failure from a status when the node.error was missed', () => {
    // What a reconnecting client gets, and what a client opening a document whose node failed
    // in an earlier session gets: a status and no `node.error`. Without this the canvas said
    // "Error" and had nothing to show.
    const ex = useExecutionStore()
    ex.applyEngineEvent(
      status('b', {
        state: 'error',
        error: 'FileNotFoundError: no such file',
        hint: 'Pick it again in the Workspace panel.',
      }),
    )
    expect(ex.node('b').error).toEqual({
      message: 'FileNotFoundError: no such file',
      traceback: '',
      hint: 'Pick it again in the Workspace panel.',
    })
    expect(ex.errorNodeIds).toEqual(['b'])

    // The event's traceback wins once it arrives, and a re-run clears both.
    ex.applyEngineEvent({
      type: 'node.error',
      ts: 2,
      workflow_id: WF,
      node_id: 'b',
      message: 'FileNotFoundError: no such file',
      traceback: 'Traceback…',
      hint: 'Pick it again in the Workspace panel.',
    })
    ex.applyEngineEvent(status('b', { state: 'error' }))
    expect(ex.node('b').error?.traceback).toBe('Traceback…')
    ex.applyEngineEvent(status('b', { state: 'queued' }))
    expect(ex.node('b').error).toBeNull()
  })

  it('keeps errors while the node is in error and clears them on the next status', () => {
    const ex = useExecutionStore()
    ex.applyEngineEvent({
      type: 'node.error',
      ts: 1,
      workflow_id: WF,
      node_id: 'b',
      message: 'division by zero',
      traceback: 'Traceback…',
      hint: 'check y',
    })
    ex.applyEngineEvent(status('b', { state: 'error' }))
    expect(ex.node('b').error?.hint).toBe('check y')
    expect(ex.errorNodeIds).toEqual(['b'])
    expect(ex.log.at(-1)?.level).toBe('error')
    ex.applyEngineEvent(status('b', { state: 'dirty' }))
    expect(ex.node('b').error).toBeNull()
    expect(ex.errorNodeIds).toEqual([])
  })

  it('stores output summaries per port and preview payloads', () => {
    const ex = useExecutionStore()
    ex.applyEngineEvent({
      type: 'node.output.summary',
      ts: 5,
      workflow_id: WF,
      node_id: 'c',
      port: 'out',
      type_id: 'astro.Float',
      summary: { value: 7 },
    })
    ex.applyEngineEvent({
      type: 'node.output.summary',
      ts: 6,
      workflow_id: WF,
      node_id: 'c',
      port: '$preview',
      type_id: 'astro.Json',
      summary: { text: 'hi' },
    })
    expect(ex.node('c').summaries.out).toEqual({
      typeId: 'astro.Float',
      summary: { value: 7 },
      ts: 5,
    })
    expect(ex.node('c').summaries.$preview?.summary).toEqual({ text: 'hi' })
  })

  it('tracks runs, the current run and the log', () => {
    const ex = useExecutionStore()
    ex.applyEngineEvent({
      type: 'run.started',
      ts: 10,
      workflow_id: WF,
      run_id: 'r1',
      targets: null,
      n_nodes: 3,
      cached: 1,
    })
    expect(ex.isRunning).toBe(true)
    expect(ex.currentRun?.runId).toBe('r1')
    ex.applyEngineEvent({
      type: 'node.log',
      ts: 11,
      workflow_id: WF,
      node_id: 'a',
      level: 'info',
      message: 'hello',
      fields: { k: 1 },
    })
    ex.applyEngineEvent({
      type: 'run.finished',
      ts: 12,
      workflow_id: WF,
      run_id: 'r1',
      targets: null,
      n_nodes: 3,
      cached: 1,
      status: 'done',
      elapsed_ms: 2000,
    })
    expect(ex.isRunning).toBe(false)
    expect(ex.runs.r1).toMatchObject({ status: 'done', elapsedMs: 2000, finishedAt: 12 })
    expect(ex.log.map((l) => l.level)).toEqual(['info', 'info', 'info'])
    // a finish for an unseen run derives its start time
    ex.applyEngineEvent({
      type: 'run.finished',
      ts: 20,
      workflow_id: WF,
      run_id: 'r2',
      targets: ['x'],
      n_nodes: 1,
      cached: 0,
      status: 'error',
      elapsed_ms: 1000,
    })
    expect(ex.runs.r2?.startedAt).toBe(19)
    expect(ex.log.at(-1)?.level).toBe('warning')
    ex.clearLog()
    expect(ex.log).toEqual([])
  })

  it('caps the log', () => {
    const ex = useExecutionStore()
    for (let i = 0; i < MAX_LOG + 20; i += 1) {
      ex.applyEngineEvent({
        type: 'node.log',
        ts: i,
        workflow_id: WF,
        node_id: 'a',
        level: 'debug',
        message: `m${i}`,
        fields: {},
      })
    }
    expect(ex.log).toHaveLength(MAX_LOG)
    expect(ex.log[0]?.message).toBe('m20')
  })

  it('applies graph.validation, ignores workspace/pack events', () => {
    const ex = useExecutionStore()
    ex.applyEngineEvent({
      type: 'graph.validation',
      ts: 1,
      workflow_id: WF,
      node_errors: { a: [{ code: 'cycle', message: 'loop' }] },
    })
    expect(ex.issuesFor('a')).toEqual([{ code: 'cycle', message: 'loop' }])
    expect(ex.issuesFor('b')).toEqual([])
    expect(ex.issueCount).toBe(1)
    const events: EngineEvent[] = [
      { type: 'workspace.changed', ts: 1, workflow_id: WF, paths: ['a.fits'] },
      { type: 'packs.changed', ts: 1, workflow_id: WF, event: 'installed' },
    ]
    events.forEach((e) => ex.applyEngineEvent(e))
    expect(ex.issueCount).toBe(1)
  })

  it('handles session messages', () => {
    const ex = useExecutionStore()
    ex.applyMessage({ type: 'hello', client_id: 'c', version: '0', ts: 1 })
    ex.applyMessage({ type: 'pong', ts: 1 })
    ex.applyMessage({
      type: 'subscribed',
      workflow_id: WF,
      ts: 1,
      current_run: 'r9',
      auto_run: false,
    })
    expect(ex.currentRunId).toBe('r9')
    expect(ex.autoRun).toBe(false)
    ex.applyMessage({ type: 'run.accepted', run_id: 'r10', workflow_id: WF, ts: 1 })
    expect(ex.currentRunId).toBe('r10')
    ex.applyMessage({ type: 'cancel.result', cancelled: true, ts: 1 })
    ex.applyMessage({ type: 'error', message: 'unknown workflow', ts: 1 })
    expect(ex.lastServerError).toBe('unknown workflow')
    expect(ex.log.at(-1)?.message).toBe('unknown workflow')
    ex.applyMessage(status('z'))
    expect(ex.node('z').state).toBe('done')
  })

  it('applies /status snapshots, prunes stale records and resets', () => {
    const ex = useExecutionStore()
    ex.applyEngineEvent({
      type: 'node.error',
      ts: 1,
      workflow_id: WF,
      node_id: 'a',
      message: 'bad',
      traceback: '',
      hint: null,
    })
    ex.applySnapshot({
      workflow_id: WF,
      node_errors: { b: [{ code: 'missing_input', message: 'x' }] },
      current_run: null,
      auto_run: true,
      nodes: {
        a: {
          node_id: 'a',
          state: 'error',
          run_id: 'r1',
          cache_hit: false,
          elapsed_ms: 1,
          cost_class: 'cheap',
          stale: false,
          type: 'node.status',
          ts: 1,
          workflow_id: WF,
        },
        'inst/inner': {
          node_id: 'inst/inner',
          state: 'done',
          run_id: null,
          cache_hit: true,
          elapsed_ms: null,
          cost_class: 'expensive',
          stale: true,
          type: 'node.status',
          ts: 1,
          workflow_id: WF,
        },
      },
    })
    expect(ex.node('a')).toMatchObject({ state: 'error', error: { message: 'bad' } })
    expect(ex.node('inst/inner')).toMatchObject({
      state: 'done',
      stale: true,
      costClass: 'expensive',
    })
    ex.setIssues({})
    expect(ex.issueCount).toBe(0)
    ex.prune((id) => id === 'nothing')
    expect(ex.nodes.a).toBeUndefined()
    expect(ex.nodes['inst/inner']).toBeDefined()
    ex.reset()
    expect(ex.nodes).toEqual({})
    expect(ex.currentRunId).toBeNull()
  })

  it('records preview.computed results per node and tag, and clears them with the tagged views', () => {
    const ex = useExecutionStore()
    ex.applyMessage({
      type: 'node.output.summary',
      ts: 1,
      workflow_id: WF,
      node_id: 'cont',
      port: 'continuum',
      type_id: 'astro.Continuum',
      summary: { cont: [1] },
      tag: 'editor',
    })
    ex.applyMessage({
      type: 'node.output.summary',
      ts: 1,
      workflow_id: WF,
      node_id: 'cont',
      port: 'continuum',
      type_id: 'astro.Continuum',
      summary: { cont: [2] },
      tag: 'viewer',
    })
    ex.applyMessage({
      type: 'preview.computed',
      ts: 2,
      workflow_id: WF,
      node_id: 'cont',
      node_type: null,
      tag: 'editor',
      ok: true,
      ports: ['continuum', 'normalized'],
      elapsed_ms: 8.5,
    })
    expect(ex.compute('cont', 'editor')).toEqual({
      ok: true,
      ports: ['continuum', 'normalized'],
      error: null,
      elapsedMs: 8.5,
      ts: 2,
    })
    expect(ex.compute('cont', 'viewer')).toBeUndefined()
    // Type-mode previews are keyed by `type:<node type>`.
    ex.applyMessage({
      type: 'preview.computed',
      ts: 3,
      workflow_id: WF,
      node_id: null,
      node_type: 'rbcodes.lines.line_list',
      tag: 'editor',
      ok: false,
      error: 'boom',
      elapsed_ms: 1,
    })
    expect(ex.compute('type:rbcodes.lines.line_list', 'editor')?.error).toBe('boom')
    ex.clearTag('cont', 'editor')
    expect(ex.compute('cont', 'editor')).toBeUndefined()
    expect(ex.view('cont', 'continuum', 'editor')).toBeUndefined()
    expect(ex.view('cont', 'continuum', 'viewer')?.summary).toEqual({ cont: [2] })
    ex.reset()
    expect(ex.computes).toEqual({})
  })
})
