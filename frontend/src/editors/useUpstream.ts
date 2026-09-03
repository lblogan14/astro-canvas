/**
 * Editors work on a node's *inputs*: this composable resolves the edge into an input port,
 * requests a full-resolution tagged preview of the upstream output (`preview.request` with
 * `viewport.tag = 'editor'`) and exposes it as a `SpectrumSeries` (or the raw summary for
 * key/value outputs such as `Transition`).
 */
import { computed, onBeforeUnmount, type Ref, watch } from 'vue'

import type { SummaryEntry } from '@/stores/execution'
import { useExecutionStore } from '@/stores/execution'
import { useSessionStore } from '@/stores/session'
import { useWorkflowStore } from '@/stores/workflow'
import { type SpectrumSeries, seriesFromSummary } from '@/widgets/spectrumSeries'

import { EDITOR_TAG } from './registry'

export const EDITOR_POINTS = 20000

export interface UpstreamSource {
  nodeId: string
  port: string
}

/** The `(node, port)` feeding `port` of `nodeId`, or `null` when nothing is connected. */
export function upstreamOf(
  edges: Record<string, { from: [string, string]; to: [string, string] }>,
  nodeId: string,
  port: string,
): UpstreamSource | null {
  for (const edge of Object.values(edges)) {
    if (edge.to[0] === nodeId && edge.to[1] === port) {
      return { nodeId: edge.from[0], port: edge.from[1] }
    }
  }
  return null
}

/** Key/value payload of a summary (`{type, data: {...}}` for scalars and chips). */
export function summaryData(entry: SummaryEntry | undefined): Record<string, unknown> | null {
  if (!entry) return null
  const inner = entry.summary['data']
  if (typeof inner === 'object' && inner !== null && !Array.isArray(inner)) {
    return inner as Record<string, unknown>
  }
  return entry.summary
}

/**
 * `viewport` overrides the default point budget (the multi-spectrum viewer asks for more
 * panels and fewer points each); it is merged over `{ n_out: EDITOR_POINTS }`.
 */
export function useUpstream(
  nodeId: Ref<string>,
  port: string,
  viewport: Record<string, unknown> = {},
) {
  const workflow = useWorkflowStore()
  const execution = useExecutionStore()
  const session = useSessionStore()

  const source = computed(() => upstreamOf(workflow.edges, nodeId.value, port))
  const entry = computed<SummaryEntry | undefined>(() => {
    const src = source.value
    if (!src) return undefined
    return (
      execution.view(src.nodeId, src.port, EDITOR_TAG) ??
      execution.node(src.nodeId).summaries[src.port]
    )
  })
  const series = computed<SpectrumSeries | null>(() =>
    entry.value ? seriesFromSummary(entry.value.summary) : null,
  )
  const data = computed(() => summaryData(entry.value))
  const ready = computed(() => source.value !== null && entry.value !== undefined)

  function request(): void {
    const src = source.value
    if (!src) return
    session.requestPreview(src.nodeId, src.port, {
      n_out: EDITOR_POINTS,
      ...viewport,
      tag: EDITOR_TAG,
    })
  }

  // Re-request when the upstream node finishes a new run or the wiring changes.
  watch(
    () => [
      source.value?.nodeId,
      source.value?.port,
      source.value ? execution.node(source.value.nodeId).runId : null,
    ],
    () => request(),
    { immediate: true },
  )

  onBeforeUnmount(() => {
    const src = source.value
    if (src) execution.clearView(src.nodeId, src.port, EDITOR_TAG)
  })

  return { source, entry, series, data, ready, request }
}
