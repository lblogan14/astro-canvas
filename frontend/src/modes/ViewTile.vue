<script setup lang="ts">
/**
 * One pinned view, drawn at whatever size the mode gives it: App's right-hand column, a Wizard
 * step's result panel, a Dashboard tile.
 *
 * The renderer is the one the node's live output picked, falling back to the view's stored
 * `kind` before the node has run (design 8.4). Like `PreviewHost`, the tile asks the server for
 * a payload matching its own width, so a Dashboard tile resized wide gets more points.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Maximize2 } from '@lucide/vue'

import type { ViewDoc } from '@/api/types'
import { previewBudget, previewComponent, rendererFor } from '@/previews'
import { useExecutionStore } from '@/stores/execution'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'
import { viewRenderer } from './layouts'

const props = withDefaults(
  defineProps<{
    view: ViewDoc
    label?: string
    /** Body height in pixels; `null` lets the tile fill its container. */
    height?: number | null
    compact?: boolean
  }>(),
  { label: '', height: null, compact: false },
)

const { t } = useI18n()
const execution = useExecutionStore()
const schema = useNodesSchemaStore()
const session = useSessionStore()
const workflow = useWorkflowStore()
const ui = useUiStore()

const host = ref<HTMLDivElement | null>(null)
const width = ref(360)
let observer: ResizeObserver | null = null
let debounce: ReturnType<typeof setTimeout> | null = null
let requested: number | null = null

const exec = computed(() => execution.node(props.view.node))
const entry = computed(() => exec.value.summaries[props.view.port])
const node = computed(() => workflow.rootNodes[props.view.node])
const spec = computed(() => (node.value ? workflow.specs[node.value.type] : undefined))
const typeId = computed(
  () =>
    entry.value?.typeId ??
    spec.value?.outputs.find((port) => port.name === props.view.port)?.type ??
    'astro.Any',
)
const live = computed(() =>
  entry.value
    ? rendererFor(spec.value, schema.typeById[entry.value.typeId], entry.value.summary)
    : null,
)
const renderer = computed(() => viewRenderer(props.view, live.value))
const title = computed(
  () => props.label || node.value?.title || spec.value?.name || props.view.node,
)
const progress = computed(() => exec.value.progress)

function scheduleRequest(): void {
  if (debounce !== null) clearTimeout(debounce)
  debounce = setTimeout(() => {
    debounce = null
    const kind = renderer.value
    if (!kind || exec.value.state !== 'done') return
    const budget = previewBudget(kind, width.value)
    if (budget === null || requested === budget) return
    requested = budget
    session.requestPreview(props.view.node, props.view.port, { n_out: budget })
  }, 100)
}

onMounted(() => {
  if (host.value) width.value = host.value.clientWidth || width.value
  if (typeof ResizeObserver !== 'undefined' && host.value) {
    observer = new ResizeObserver((entries) => {
      const next = Math.round(entries[0]?.contentRect.width ?? width.value)
      if (next && Math.abs(next - width.value) >= 16) {
        width.value = next
        scheduleRequest()
      }
    })
    observer.observe(host.value)
  }
  scheduleRequest()
})

onBeforeUnmount(() => {
  observer?.disconnect()
  if (debounce !== null) clearTimeout(debounce)
})

watch(
  () => [exec.value.state, exec.value.runId],
  () => {
    requested = null
    scheduleRequest()
  },
)

function expand(): void {
  ui.openViewer({ nodeId: props.view.node, port: props.view.port })
}
</script>

<template>
  <figure
    class="flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border bg-card"
    :data-testid="`view-tile-${view.id}`"
    :data-state="exec.state"
    :data-renderer="renderer ?? 'none'"
  >
    <figcaption
      class="flex h-7 shrink-0 items-center gap-1 border-b px-2 text-[11px] font-medium"
      :class="compact ? 'h-6' : ''"
    >
      <span class="min-w-0 flex-1 truncate" :title="`${view.node}.${view.port}`">{{ title }}</span>
      <span
        v-if="exec.state === 'running'"
        class="rounded bg-blue-500/15 px-1 text-blue-600"
        data-testid="view-tile-running"
      >
        {{
          progress?.frac
            ? t('modes.progress', { pct: Math.round(progress.frac * 100) })
            : t('node.state.running')
        }}
      </span>
      <span v-else-if="exec.stale" class="rounded bg-amber-500/15 px-1 text-amber-600">
        {{ t('node.state.stale') }}
      </span>
      <button
        type="button"
        class="inline-flex size-5 items-center justify-center rounded text-muted-foreground hover:text-foreground"
        :aria-label="t('preview.expand', { port: view.port })"
        :title="t('preview.expand', { port: view.port })"
        :data-testid="`view-expand-${view.id}`"
        @click="expand"
      >
        <Maximize2 class="size-3" />
      </button>
    </figcaption>

    <div
      ref="host"
      class="min-h-0 min-w-0 flex-1 overflow-auto p-2"
      :style="height === null ? undefined : { height: `${height}px` }"
    >
      <p v-if="exec.error" class="text-[11px] text-destructive" data-testid="view-tile-error">
        {{ exec.error.message }}
      </p>
      <component
        v-else-if="entry && renderer"
        :is="previewComponent(renderer)"
        :node-id="view.node"
        :port="view.port"
        :type-id="typeId"
        :summary="entry.summary"
        :width="width"
      />
      <p v-else class="text-[11px] text-muted-foreground">
        {{ exec.state === 'done' ? t('preview.no_output') : t('preview.waiting') }}
      </p>
    </div>
  </figure>
</template>
