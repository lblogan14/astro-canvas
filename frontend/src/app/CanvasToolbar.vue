<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuPortal,
  DropdownMenuRoot,
  DropdownMenuTrigger,
} from 'reka-ui'
import {
  Boxes,
  Check,
  ChevronDown,
  FolderOpen,
  Library,
  LoaderCircle,
  Maximize,
  PanelBottom,
  PanelRight,
  Play,
  Redo2,
  Share2,
  Square,
  Star,
  TriangleAlert,
  Undo2,
  Upload,
  Workflow,
  Zap,
} from '@lucide/vue'

import { useRouter } from 'vue-router'

import { Button } from '@/components/ui/button'
import { useCanvasAdapter } from '@/canvas/CanvasAdapter'
import BundleDialog from '@/manager/BundleDialog.vue'
import { bundleFrom, dropBundle } from '@/manager/importBundle'
import { useAuthStore } from '@/stores/auth'
import { useExecutionStore } from '@/stores/execution'
import { useSessionStore } from '@/stores/session'
import { type AppMode, useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'

const { t } = useI18n()
const workflow = useWorkflowStore()
const execution = useExecutionStore()
const session = useSessionStore()
const ui = useUiStore()
const auth = useAuthStore()
const canvas = useCanvasAdapter()
const router = useRouter()

const bundleOpen = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

function chooseBundle(): void {
  fileInput.value?.click()
}

async function onBundleChosen(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = bundleFrom(input.files)
  input.value = ''
  if (file) await dropBundle(file)
}

const nameDraft = ref(workflow.name)
watch(
  () => workflow.name,
  (name) => {
    nameDraft.value = name
  },
)

function commitName(): void {
  workflow.rename(nameDraft.value)
  nameDraft.value = workflow.name
}

const running = computed(() => execution.isRunning)
const saveLabel = computed(() => t(`toolbar.save.${workflow.saveState}`))

async function toggleRun(): Promise<void> {
  if (running.value) await session.cancel()
  else await session.run()
}

/** Menu order: the graph first, then the four composed layouts (design 8.1). */
const LAYOUTS: readonly AppMode[] = ['canvas', 'app', 'wizard', 'dashboard', 'batch']
</script>

<template>
  <div
    class="flex h-11 shrink-0 items-center gap-1 border-b bg-background px-2"
    role="toolbar"
    :aria-label="t('toolbar.label')"
  >
    <Button
      variant="ghost"
      size="icon-sm"
      :aria-pressed="ui.sidebarOpen && ui.sidebarPanel === 'library'"
      :title="t('toolbar.library')"
      @click="ui.showSidebar('library')"
    >
      <Library />
    </Button>
    <Button
      variant="ghost"
      size="icon-sm"
      :aria-pressed="ui.sidebarOpen && ui.sidebarPanel === 'workflows'"
      :title="t('toolbar.workflows')"
      data-testid="toggle-workflows"
      @click="ui.showSidebar('workflows')"
    >
      <Workflow />
    </Button>
    <Button
      variant="ghost"
      size="icon-sm"
      :aria-pressed="ui.sidebarOpen && ui.sidebarPanel === 'workspace'"
      :title="t('toolbar.workspace')"
      data-testid="toggle-workspace"
      @click="ui.showSidebar('workspace')"
    >
      <FolderOpen />
    </Button>

    <Button
      variant="ghost"
      size="icon-sm"
      :aria-pressed="ui.sidebarOpen && ui.sidebarPanel === 'params'"
      :title="t('promote.panel_title')"
      data-testid="toggle-params"
      @click="ui.showSidebar('params')"
    >
      <Star />
    </Button>

    <span class="mx-1 h-5 w-px bg-border" aria-hidden="true" />

    <input
      v-model="nameDraft"
      class="h-7 w-56 rounded-md border border-transparent bg-transparent px-2 text-sm font-medium hover:border-input focus:border-input focus:outline-none"
      :placeholder="t('toolbar.name_placeholder')"
      :aria-label="t('toolbar.workflow_name')"
      :disabled="!workflow.isOpen"
      data-testid="workflow-name"
      @keydown.enter.prevent="($event.target as HTMLInputElement).blur()"
      @blur="commitName"
    />

    <span
      class="text-xs text-muted-foreground"
      data-testid="save-state"
      :data-state="workflow.saveState"
    >
      <LoaderCircle v-if="workflow.saveState === 'saving'" class="inline size-3 animate-spin" />
      <TriangleAlert
        v-else-if="workflow.saveState === 'error'"
        class="inline size-3 text-destructive"
      />
      <Check v-else-if="workflow.saveState === 'saved'" class="inline size-3" />
      {{ saveLabel }}
    </span>

    <span class="flex-1" />

    <Button
      variant="ghost"
      size="icon-sm"
      :disabled="!workflow.canUndo"
      :title="t('toolbar.undo', { label: workflow.undoLabel ? t(workflow.undoLabel) : '' })"
      data-testid="undo"
      @click="workflow.undo()"
    >
      <Undo2 />
    </Button>
    <Button
      variant="ghost"
      size="icon-sm"
      :disabled="!workflow.canRedo"
      :title="t('toolbar.redo', { label: workflow.redoLabel ? t(workflow.redoLabel) : '' })"
      data-testid="redo"
      @click="workflow.redo()"
    >
      <Redo2 />
    </Button>
    <Button
      variant="ghost"
      size="icon-sm"
      :title="t('toolbar.fit_view')"
      @click="canvas?.fitView()"
    >
      <Maximize />
    </Button>

    <DropdownMenuRoot>
      <DropdownMenuTrigger as-child>
        <Button variant="ghost" size="sm" :title="t('toolbar.layout')" data-testid="layout-menu">
          {{ t(`toolbar.layout_${ui.mode}`) }} <ChevronDown class="size-3" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuPortal>
        <DropdownMenuContent
          align="end"
          :side-offset="4"
          class="z-50 min-w-40 rounded-md border bg-popover p-1 text-xs text-popover-foreground shadow-md"
        >
          <DropdownMenuItem
            v-for="layout in LAYOUTS"
            :key="layout"
            class="ac-menu-item"
            :data-testid="`layout-${layout}`"
            @select="ui.setMode(layout)"
          >
            <Check v-if="layout === ui.mode" class="size-3.5" />
            <span v-else class="size-3.5" />
            {{ t(`toolbar.layout_${layout}`) }}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenuPortal>
    </DropdownMenuRoot>

    <span class="mx-1 h-5 w-px bg-border" aria-hidden="true" />

    <Button
      variant="ghost"
      size="sm"
      :aria-pressed="execution.autoRun"
      :title="t('toolbar.auto_run_hint')"
      :disabled="!workflow.isOpen"
      data-testid="auto-run"
      @click="session.setAutoRun(!execution.autoRun)"
    >
      <Zap :class="execution.autoRun ? 'text-amber-500' : 'text-muted-foreground'" />
      {{ t('toolbar.auto_run') }}
    </Button>
    <Button
      :variant="running ? 'destructive' : 'default'"
      size="sm"
      :disabled="!workflow.isOpen"
      :title="running ? t('toolbar.cancel') : t('toolbar.run_hint')"
      data-testid="run"
      @click="toggleRun"
    >
      <Square v-if="running" />
      <Play v-else />
      {{ running ? t('toolbar.cancel') : t('toolbar.run') }}
    </Button>

    <DropdownMenuRoot>
      <DropdownMenuTrigger as-child>
        <Button variant="ghost" size="sm" :title="t('bundle.share')" data-testid="share-menu">
          <Share2 /> {{ t('bundle.share') }}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuPortal>
        <DropdownMenuContent
          align="end"
          :side-offset="4"
          class="z-50 min-w-48 rounded-md border bg-popover p-1 text-xs text-popover-foreground shadow-md"
        >
          <DropdownMenuItem
            class="ac-menu-item"
            data-testid="share-export"
            @select="bundleOpen = true"
          >
            <Share2 class="size-3.5" /> {{ t('bundle.export') }}
          </DropdownMenuItem>
          <DropdownMenuItem class="ac-menu-item" data-testid="share-import" @select="chooseBundle">
            <Upload class="size-3.5" /> {{ t('bundle.import') }}
          </DropdownMenuItem>
          <DropdownMenuItem
            v-if="auth.canManagePacks"
            class="ac-menu-item"
            data-testid="share-manager"
            @select="router.push({ name: 'manager' })"
          >
            <Boxes class="size-3.5" /> {{ t('manager.open') }}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenuPortal>
    </DropdownMenuRoot>
    <input
      ref="fileInput"
      type="file"
      accept=".acw,application/zip"
      class="hidden"
      data-testid="bundle-file"
      @change="onBundleChosen"
    />
    <BundleDialog :open="bundleOpen" @close="bundleOpen = false" />

    <span class="mx-1 h-5 w-px bg-border" aria-hidden="true" />

    <Button
      variant="ghost"
      size="icon-sm"
      :aria-pressed="ui.inspectorOpen"
      :title="t('toolbar.inspector')"
      @click="ui.toggleInspector()"
    >
      <PanelRight />
    </Button>
    <Button
      variant="ghost"
      size="icon-sm"
      :aria-pressed="ui.drawerOpen"
      :title="t('toolbar.drawer')"
      data-testid="toggle-drawer"
      @click="ui.toggleDrawer()"
    >
      <PanelBottom />
      <span
        v-if="execution.issueCount || execution.errorNodeIds.length"
        class="absolute -top-0.5 -right-0.5 size-2 rounded-full bg-destructive"
        aria-hidden="true"
      />
    </Button>
  </div>
</template>
