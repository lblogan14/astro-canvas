<script setup lang="ts">
/**
 * The Vue Flow canvas: renders the workflow store, forwards interactions back into it and
 * registers a `CanvasAdapter` for the shell. Only `canvas/vueflow/*` imports `@vue-flow/*`.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, provide, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  type Connection,
  ConnectionMode,
  type EdgeChange,
  type EdgeUpdateEvent,
  type GraphNode,
  type NodeChange,
  type NodeDragEvent,
  type OnConnectStartParams,
  type ValidConnectionFunc,
  VueFlow,
  useVueFlow,
} from '@vue-flow/core'
import { Background, BackgroundVariant } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'

import {
  CANVAS_LOD_KEY,
  type CanvasAdapter,
  type FitViewOptions,
  LOD_ZOOM_THRESHOLD,
  type Point,
  registerCanvasAdapter,
} from '@/canvas/CanvasAdapter'
import { NODE_DRAG_TYPE } from '@/canvas/dnd'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useSelectionStore } from '@/stores/selection'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'
import FlowNode from './FlowNode.vue'
import GroupNode from './GroupNode.vue'
import { GROUP_NODE, groupIdOf, isGroupNodeId, useFlowElements } from './toFlow'

const { t } = useI18n()
const workflow = useWorkflowStore()
const schema = useNodesSchemaStore()
const selection = useSelectionStore()
const ui = useUiStore()

const { nodes, edges } = useFlowElements()
const container = ref<HTMLElement | null>(null)

const flow = useVueFlow('main')
const {
  fitView,
  zoomIn,
  zoomOut,
  screenToFlowCoordinate,
  flowToScreenCoordinate,
  viewport,
  dimensions,
  addSelectedNodes,
  removeSelectedNodes,
  getSelectedNodes,
  findNode,
  onConnect,
  onConnectStart,
  onConnectEnd,
  onNodeDragStop,
  onSelectionDragStop,
  onEdgeUpdate,
  onNodesChange,
  onEdgesChange,
  onNodesInitialized,
} = flow

const zoom = computed(() => viewport.value.zoom)
const lod = computed(() => zoom.value < LOD_ZOOM_THRESHOLD)
provide(CANVAS_LOD_KEY, lod)

// --- selection ----------------------------------------------------------------------------------

function syncSelection(): void {
  const nodeIds = getSelectedNodes.value.map((n) => n.id)
  const edgeIds = flow.getSelectedEdges.value.map((e) => e.id)
  selection.set(nodeIds, edgeIds)
}

// Our hooks run before Vue Flow's own `applyDefault` handler (it registers on mount), so read
// the selection on the next tick, once the changes have been applied.
onNodesChange((changes: NodeChange[]) => {
  if (changes.some((c) => c.type === 'select')) void nextTick(syncSelection)
})
onEdgesChange((changes: EdgeChange[]) => {
  if (changes.some((c) => c.type === 'select')) void nextTick(syncSelection)
})

// --- moves ---------------------------------------------------------------------------------------

function commitMoves(dragged: GraphNode[]): void {
  const groups: { id: string; pos: [number, number] }[] = []
  const moves: { id: string; pos: [number, number] }[] = []
  for (const node of dragged) {
    const { x, y } = node.computedPosition
    if (node.type === GROUP_NODE)
      groups.push({ id: groupIdOf(node.id), pos: [Math.round(x), Math.round(y)] })
    else moves.push({ id: node.id, pos: [Math.round(x), Math.round(y)] })
  }
  const touchedGroups = new Set<string>()
  for (const move of moves) {
    const gid = workflow.groupOf(move.id)
    if (gid) touchedGroups.add(gid)
  }
  const apply = (): void => {
    for (const g of groups) workflow.moveGroup(g.id, g.pos)
    if (moves.length) workflow.moveNodes(moves)
    for (const gid of touchedGroups) if (!groups.some((g) => g.id === gid)) workflow.fitGroup(gid)
  }
  if (groups.length + (moves.length ? 1 : 0) + touchedGroups.size > 1)
    workflow.transaction('command.move', apply)
  else apply()
}

onNodeDragStop(({ nodes: dragged }: NodeDragEvent) => commitMoves(dragged))
onSelectionDragStop(({ nodes: dragged }: NodeDragEvent) => commitMoves(dragged))

// --- connections ---------------------------------------------------------------------------------

let connecting: OnConnectStartParams | null = null
let connected = false
let lastReject: string | null = null

function toQuery(connection: Connection) {
  return {
    source: connection.source,
    sourcePort: connection.sourceHandle ?? '',
    target: connection.target,
    targetPort: connection.targetHandle ?? '',
  }
}

const isValidConnection: ValidConnectionFunc = (connection) => {
  const verdict = workflow.validateConnection(toQuery(connection))
  if (!verdict.ok) lastReject = verdict.reason
  return verdict.ok
}

onConnectStart((params) => {
  connecting = params
  connected = false
  lastReject = null
})

onConnect((connection: Connection) => {
  connected = true
  const { verdict } = workflow.connect(toQuery(connection))
  if (!verdict.ok) ui.notify(t(`canvas.reject.${verdict.reason}`), 'error')
})

onConnectEnd((event) => {
  const start = connecting
  connecting = null
  if (connected || !start?.nodeId) return
  const target = (event?.target ?? null) as Element | null
  if (target?.classList.contains('vue-flow__pane') && start.handleType === 'source') {
    const source = workflow.nodes[start.nodeId]
    const spec = source ? schema.byId[source.type] : undefined
    const sourceType = spec?.outputs.find((p) => p.name === start.handleId)?.type
    const point =
      event instanceof MouseEvent
        ? { x: event.clientX, y: event.clientY }
        : { x: dimensions.value.width / 2, y: dimensions.value.height / 2 }
    ui.openPalette({
      sourceNodeId: start.nodeId,
      sourcePort: start.handleId ?? '',
      sourceType: sourceType ?? null,
      at: point,
    })
    return
  }
  if (lastReject) ui.notify(t(`canvas.reject.${lastReject}`), 'error')
})

onEdgeUpdate(({ edge, connection }: EdgeUpdateEvent) => {
  const query = toQuery(connection)
  const verdict = workflow.validateConnection(query, edge.id)
  if (!verdict.ok) {
    ui.notify(t(`canvas.reject.${verdict.reason}`), 'error')
    return
  }
  workflow.transaction('command.connect', () => {
    workflow.disconnect([edge.id])
    workflow.connect(query)
  })
})

// --- drag & drop from the library -----------------------------------------------------------------

function onDragOver(event: DragEvent): void {
  if (event.dataTransfer?.types.includes(NODE_DRAG_TYPE)) {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'copy'
  }
}

function onDrop(event: DragEvent): void {
  const typeId = event.dataTransfer?.getData(NODE_DRAG_TYPE)
  const spec = typeId ? schema.byId[typeId] : undefined
  if (!spec) return
  event.preventDefault()
  const point = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
  const id = workflow.addNode(spec, [Math.round(point.x - 100), Math.round(point.y - 16)])
  selection.set([id])
}

// --- fit on load ----------------------------------------------------------------------------------

let pendingFit = false
watch(
  () => workflow.id,
  () => {
    pendingFit = true
  },
  { immediate: true },
)
onNodesInitialized(() => {
  if (pendingFit) {
    pendingFit = false
    void fitView({ padding: 0.2, maxZoom: 1 })
  }
})

// --- adapter --------------------------------------------------------------------------------------

const adapter: CanvasAdapter = {
  zoom,
  fitView(options?: FitViewOptions) {
    void fitView({
      padding: options?.padding ?? 0.2,
      duration: options?.duration ?? 200,
      maxZoom: 1.5,
      ...(options?.nodeIds ? { nodes: options.nodeIds } : {}),
    })
  },
  zoomIn: () => void zoomIn({ duration: 150 }),
  zoomOut: () => void zoomOut({ duration: 150 }),
  screenToFlow: (point: Point) => screenToFlowCoordinate(point),
  flowToScreen: (point: Point) => flowToScreenCoordinate(point),
  viewportCenter() {
    // Measure the container directly: Vue Flow's `dimensions` can lag behind a layout change.
    const rect = container.value?.getBoundingClientRect()
    return screenToFlowCoordinate({
      x: (rect?.left ?? 0) + (rect?.width ?? dimensions.value.width) / 2,
      y: (rect?.top ?? 0) + (rect?.height ?? dimensions.value.height) / 2,
    })
  },
  selectNodes(ids: string[]) {
    const targets = ids.map((id) => findNode(id)).filter((n): n is GraphNode => n !== undefined)
    // Freshly added nodes reach Vue Flow on the next render; keep the store's choice meanwhile.
    if (ids.length && !targets.length) return
    removeSelectedNodes(getSelectedNodes.value)
    if (targets.length) addSelectedNodes(targets)
    else syncSelection()
  },
  focus() {
    container.value?.focus()
  },
}

// Selection changes requested by the shell (palette, paste, duplicate) are pushed into Vue Flow.
watch(
  () => selection.nodeIds,
  (ids) => {
    const current = getSelectedNodes.value.map((n) => n.id)
    if (ids.length === current.length && ids.every((id) => current.includes(id))) return
    adapter.selectNodes(ids)
  },
  // `post`: nodes added in the same commit have reached Vue Flow by then.
  { flush: 'post' },
)

onMounted(() => registerCanvasAdapter(adapter))
onBeforeUnmount(() => registerCanvasAdapter(null))

function miniMapColor(node: GraphNode): string {
  return node.type === GROUP_NODE ? 'transparent' : 'var(--muted-foreground)'
}

const hasDocument = computed(() => workflow.isOpen)
const isGroupSelected = computed(() => selection.nodeIds.some(isGroupNodeId))
</script>

<template>
  <div
    ref="container"
    class="ac-canvas relative h-full w-full outline-none"
    tabindex="-1"
    data-testid="canvas"
    :data-lod="lod"
    :data-group-selected="isGroupSelected"
    @dragover="onDragOver"
    @drop="onDrop"
  >
    <VueFlow
      id="main"
      :nodes="nodes"
      :edges="edges"
      :is-valid-connection="isValidConnection"
      :connection-mode="ConnectionMode.Strict"
      :delete-key-code="null"
      :only-render-visible-elements="true"
      :edges-updatable="true"
      :snap-to-grid="true"
      :snap-grid="[8, 8]"
      :min-zoom="0.1"
      :max-zoom="2.5"
      :zoom-on-double-click="false"
      :elevate-edges-on-select="true"
      :default-edge-options="{ type: 'default', updatable: true }"
    >
      <template #node-astro="nodeProps">
        <FlowNode v-bind="nodeProps" />
      </template>
      <template #node-group="nodeProps">
        <GroupNode v-bind="nodeProps" />
      </template>
      <Background :variant="BackgroundVariant.Dots" :gap="20" :size="1.2" />
      <MiniMap pannable zoomable position="bottom-right" :node-color="miniMapColor" />
      <Controls position="bottom-left" :show-interactive="false" />
    </VueFlow>
    <div
      v-if="!hasDocument"
      class="pointer-events-none absolute inset-0 flex items-center justify-center"
    >
      <div class="rounded-lg border bg-card/90 px-6 py-4 text-center shadow-sm">
        <p class="text-sm font-medium">{{ t('canvas.empty_title') }}</p>
        <p class="mt-1 text-xs text-muted-foreground">{{ t('canvas.empty_hint') }}</p>
      </div>
    </div>
  </div>
</template>
