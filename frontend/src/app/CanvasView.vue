<script setup lang="ts">
/** The editor page: toolbar, sidebars, canvas, inspector, drawer, palette and shortcuts. */
import { computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { FlowCanvas } from '@/canvas/vueflow'
import SubgraphBreadcrumb from '@/canvas/SubgraphBreadcrumb.vue'
import AppMode from '@/modes/AppMode.vue'
import BatchMode from '@/modes/BatchMode.vue'
import DashboardMode from '@/modes/DashboardMode.vue'
import WizardMode from '@/modes/WizardMode.vue'
import { useAuthStore } from '@/stores/auth'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useSelectionStore } from '@/stores/selection'
import { useSessionStore } from '@/stores/session'
import { isAppMode, useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'
import { useWorkflowsStore } from '@/stores/workflows'
import { setFileDropTranslator } from '@/canvas/fileDrop'
import { useWorkspaceStore } from '@/stores/workspace'
import QuarantineBanner from '@/manager/QuarantineBanner.vue'
import { setBundleHandlers } from '@/manager/importBundle'
import { usePacksStore } from '@/stores/packs'
import BottomDrawer from './drawer/BottomDrawer.vue'
import CommandPalette from './CommandPalette.vue'
import InspectorPanel from './inspector/InspectorPanel.vue'
import NodeLibrary from './library/NodeLibrary.vue'
import ParametersPanel from './params/ParametersPanel.vue'
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
const auth = useAuthStore()

useShortcuts(useShortcutActions())

const routeId = computed(() => {
  const id = route.params.id
  return typeof id === 'string' && id ? id : null
})

/**
 * `/w/:id/:mode` is the source of truth for the layout: the route sets `ui.mode`, and switching
 * mode in the toolbar replaces the URL so the link can be shared or reloaded (brief item 7).
 */
const routeMode = computed(() => (isAppMode(route.params.mode) ? route.params.mode : null))

function syncModeFromRoute(): void {
  const mode = routeMode.value
  if (mode && mode !== ui.mode) ui.setMode(mode)
}

function syncRouteFromMode(): void {
  const id = routeId.value
  if (!id || routeMode.value === ui.mode) return
  void router.replace(
    ui.mode === 'canvas'
      ? { name: 'workflow', params: { id } }
      : { name: 'workflow-mode', params: { id, mode: ui.mode } },
  )
}

async function openFromRoute(): Promise<void> {
  // Nothing is readable before the login on a `--auth users` server, and the router is about
  // to replace this route with /login anyway (design 12).
  if (auth.requiresLogin) return
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
const packs = usePacksStore()
setFileDropTranslator((key, params) => t(key, params ?? {}))
// The canvas drop target and the toolbar's Import both land here (they have no component context).
setBundleHandlers({
  t: (key, params) => (typeof params === 'number' ? t(key, params) : t(key, params ?? {})),
  notify: (message, kind) => ui.notify(message, kind ?? 'info'),
  open: (id) => void router.push({ name: 'workflow', params: { id } }),
})

onMounted(async () => {
  syncModeFromRoute()
  session.connect()
  if (!schema.isReady) await schema.load()
  void workspace.load()
  void packs.refresh()
  await openFromRoute()
})

watch(routeId, () => void openFromRoute())
watch(routeMode, syncModeFromRoute)
watch(() => ui.mode, syncRouteFromMode)

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
        <ParametersPanel v-else-if="ui.sidebarPanel === 'params'" />
        <WorkflowsPanel v-else />
      </aside>

      <div class="relative flex min-w-0 flex-1 flex-col">
        <QuarantineBanner />
        <div class="relative min-h-0 flex-1">
          <BatchMode v-if="ui.mode === 'batch'" />
          <AppMode v-else-if="ui.mode === 'app'" />
          <WizardMode v-else-if="ui.mode === 'wizard'" />
          <DashboardMode v-else-if="ui.mode === 'dashboard'" />
          <template v-else>
            <FlowCanvas />
            <SubgraphBreadcrumb />
          </template>
          <CommandPalette />
          <ViewerSheet />
          <EditorHost />
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
