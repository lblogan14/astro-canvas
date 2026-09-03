<script setup lang="ts">
/** The editor page: toolbar, sidebars, canvas, inspector, drawer, palette and shortcuts. */
import { computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { FlowCanvas } from '@/canvas/vueflow'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useSelectionStore } from '@/stores/selection'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'
import { useWorkflowsStore } from '@/stores/workflows'
import { setFileDropTranslator } from '@/canvas/fileDrop'
import { useWorkspaceStore } from '@/stores/workspace'
import BottomDrawer from './drawer/BottomDrawer.vue'
import CommandPalette from './CommandPalette.vue'
import InspectorPanel from './inspector/InspectorPanel.vue'
import NodeLibrary from './library/NodeLibrary.vue'
import { useShortcutActions, useShortcuts } from './shortcuts'
import CanvasToolbar from './CanvasToolbar.vue'
import ViewerSheet from './viewer/ViewerSheet.vue'
import { EditorHost } from '@/editors'
import WorkflowsPanel from './workflows/WorkflowsPanel.vue'
import WorkspacePanel from './workspace/WorkspacePanel.vue'

const LAST_KEY = 'astro-canvas-last-workflow'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const schema = useNodesSchemaStore()
const session = useSessionStore()
const workflow = useWorkflowStore()
const workflows = useWorkflowsStore()
const selection = useSelectionStore()
const ui = useUiStore()

useShortcuts(useShortcutActions())

const routeId = computed(() => {
  const id = route.params.id
  return typeof id === 'string' && id ? id : null
})

async function openFromRoute(): Promise<void> {
  const id = routeId.value
  if (id) {
    if (workflow.id === id) return
    try {
      await session.openWorkflow(id)
      selection.clear()
      try {
        window.localStorage.setItem(LAST_KEY, id)
      } catch {
        // ignore storage errors
      }
    } catch {
      ui.notify(t('workflows.open_failed', { id }), 'error')
      await router.replace({ name: 'home' })
    }
    return
  }
  // No id: reopen the last workflow, else the most recent one, else create one.
  await workflows.refresh()
  let last: string | null = null
  try {
    last = window.localStorage.getItem(LAST_KEY)
  } catch {
    last = null
  }
  const candidate = workflows.items.find((w) => w.id === last) ?? workflows.items[0]
  if (candidate) {
    await router.replace({ name: 'workflow', params: { id: candidate.id } })
    return
  }
  if (ui.isOnline) {
    const id = await session.createWorkflow(t('workflows.untitled'))
    await router.replace({ name: 'workflow', params: { id } })
  }
}

const workspace = useWorkspaceStore()
setFileDropTranslator((key, params) => t(key, params ?? {}))

onMounted(async () => {
  session.connect()
  if (!schema.isReady) await schema.load()
  void workspace.load()
  await openFromRoute()
})

watch(routeId, () => void openFromRoute())

// Drop runtime records and selection entries for nodes that vanished.
watch(
  () => workflow.nodeCount,
  () => {
    selection.prune(
      (id) => id.startsWith('group:') || workflow.nodes[id] !== undefined,
      (id) => workflow.edges[id] !== undefined,
    )
  },
)

// Flush pending edits when the tab closes.
function onBeforeUnload(): void {
  if (workflow.isDirty) void workflow.saveNow()
}
onMounted(() => window.addEventListener('beforeunload', onBeforeUnload))
</script>

<template>
  <div class="flex h-full flex-col">
    <CanvasToolbar />
    <div class="relative flex min-h-0 flex-1">
      <aside
        v-if="ui.sidebarOpen"
        class="w-64 shrink-0 border-r bg-sidebar text-sidebar-foreground"
        data-testid="sidebar"
        :data-panel="ui.sidebarPanel"
      >
        <NodeLibrary v-if="ui.sidebarPanel === 'library'" />
        <WorkspacePanel v-else-if="ui.sidebarPanel === 'workspace'" />
        <WorkflowsPanel v-else />
      </aside>

      <div class="relative flex min-w-0 flex-1 flex-col">
        <div class="relative min-h-0 flex-1">
          <FlowCanvas />
          <CommandPalette />
          <ViewerSheet />
          <EditorHost />
          <div
            v-if="ui.toast"
            class="pointer-events-none absolute bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-md border px-3 py-2 text-xs shadow-md"
            :class="
              ui.toast.kind === 'error'
                ? 'border-destructive/40 bg-destructive/10 text-destructive'
                : 'bg-popover text-popover-foreground'
            "
            role="status"
            data-testid="toast"
          >
            {{ ui.toast.message }}
          </div>
        </div>
        <div v-if="ui.drawerOpen" class="h-56 shrink-0">
          <BottomDrawer />
        </div>
      </div>

      <aside
        v-if="ui.inspectorOpen"
        class="w-72 shrink-0 border-l bg-sidebar text-sidebar-foreground"
      >
        <InspectorPanel />
      </aside>
    </div>
  </div>
</template>
