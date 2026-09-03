<script setup lang="ts">
/**
 * Workspace sidebar: the active folder (switch / recent), upload with progress, a lazily loaded
 * file tree (drag files onto the canvas, double-click to add a loader node) and per-file actions.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuPortal,
  DropdownMenuRoot,
  DropdownMenuTrigger,
  PopoverContent,
  PopoverPortal,
  PopoverRoot,
  PopoverTrigger,
} from 'reka-ui'
import {
  Download,
  FolderOpen,
  FolderPlus,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Trash2,
  Upload,
} from '@lucide/vue'

import { api } from '@/api/client'
import type { WorkspaceEntry } from '@/api/types'
import { useCanvasAdapter } from '@/canvas/CanvasAdapter'
import { addLoaderNode } from '@/canvas/fileDrop'
import { useSelectionStore } from '@/stores/selection'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'
import { parentOf, useWorkspaceStore } from '@/stores/workspace'
import WorkspaceTree from './WorkspaceTree.vue'

const { t } = useI18n()
const workspace = useWorkspaceStore()
const workflow = useWorkflowStore()
const selection = useSelectionStore()
const ui = useUiStore()
const canvas = useCanvasAdapter()

const fileInput = ref<HTMLInputElement | null>(null)
const switchOpen = ref(false)
const switchPath = ref('')
const switching = ref(false)
const dragOver = ref(false)

const selectedEntry = computed<WorkspaceEntry | null>(() => {
  const path = workspace.selectedPath
  if (!path) return null
  return workspace.entriesOf(parentOf(path))?.find((e) => e.path === path) ?? null
})
const uploadDir = computed(() => {
  const entry = selectedEntry.value
  if (!entry) return 'uploads'
  return entry.is_dir ? entry.path : parentOf(entry.path) || 'uploads'
})

async function addToCanvas(entry: WorkspaceEntry): Promise<void> {
  if (entry.is_dir || !workflow.isOpen) return
  const center = canvas.value?.viewportCenter() ?? { x: 0, y: 0 }
  const id = await addLoaderNode(entry.path, [
    Math.round(center.x - 120),
    Math.round(center.y - 40),
  ])
  if (id) selection.set([id])
}

function chooseFiles(): void {
  fileInput.value?.click()
}

async function onFilesChosen(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  if (!input.files?.length) return
  await uploadFiles(input.files)
  input.value = ''
}

async function uploadFiles(files: FileList | File[]): Promise<void> {
  const jobs = await workspace.upload(files, uploadDir.value, 'rename')
  for (const job of jobs) {
    if (job.state === 'done') ui.notify(t('workspace.upload_done', { name: job.name }))
    else
      ui.notify(t('workspace.upload_failed', { name: job.name, error: job.error ?? '' }), 'error')
  }
}

function onDrop(event: DragEvent): void {
  dragOver.value = false
  if (event.dataTransfer?.files.length) {
    event.preventDefault()
    void uploadFiles(event.dataTransfer.files)
  }
}

function onDragOver(event: DragEvent): void {
  if (event.dataTransfer?.types.includes('Files')) {
    event.preventDefault()
    dragOver.value = true
  }
}

async function newFolder(): Promise<void> {
  const dir = uploadDir.value === 'uploads' && !selectedEntry.value ? '' : uploadDir.value
  const name = window.prompt(t('workspace.new_folder_prompt', { dir: dir || '/' }))
  if (!name) return
  try {
    await workspace.createFolder(dir ? `${dir}/${name}` : name)
    await workspace.expand(dir)
  } catch (err) {
    ui.notify(err instanceof Error ? err.message : String(err), 'error')
  }
}

async function remove(entry: WorkspaceEntry): Promise<void> {
  if (!window.confirm(t('workspace.confirm_delete', { name: entry.name }))) return
  try {
    await workspace.remove(entry.path, entry.is_dir)
  } catch (err) {
    ui.notify(err instanceof Error ? err.message : String(err), 'error')
  }
}

function download(entry: WorkspaceEntry): void {
  window.open(api.workspaceFileUrl(entry.path), '_blank')
}

async function switchTo(path: string, create: boolean): Promise<void> {
  const target = path.trim()
  if (!target) return
  switching.value = true
  try {
    const info = await workspace.switchWorkspace(target, create)
    switchOpen.value = false
    switchPath.value = ''
    ui.notify(t('workspace.switched', { root: info.root }))
    // Workflows live per workspace: close the current one and let the shell reopen.
    window.location.assign('/')
  } catch (err) {
    ui.notify(
      t('workspace.switch_failed', { error: err instanceof Error ? err.message : String(err) }),
      'error',
    )
  } finally {
    switching.value = false
  }
}
</script>

<template>
  <section
    class="flex h-full flex-col"
    :aria-label="t('workspace.title')"
    data-testid="workspace-panel"
    :data-drag-over="dragOver"
    @dragover="onDragOver"
    @dragleave="dragOver = false"
    @drop="onDrop"
  >
    <header class="flex items-center gap-1 border-b p-2">
      <FolderOpen class="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
      <span
        class="min-w-0 flex-1 truncate text-xs font-medium"
        :title="workspace.root ?? ''"
        data-testid="workspace-root"
      >
        {{ workspace.rootName || t('workspace.title') }}
      </span>
      <PopoverRoot v-model:open="switchOpen">
        <PopoverTrigger
          class="inline-flex size-6 items-center justify-center rounded text-muted-foreground hover:bg-sidebar-accent hover:text-foreground"
          :title="t('workspace.switch')"
          :aria-label="t('workspace.switch')"
          data-testid="workspace-switch"
        >
          <MoreHorizontal class="size-3.5" />
        </PopoverTrigger>
        <PopoverPortal>
          <PopoverContent
            side="bottom"
            align="start"
            :side-offset="4"
            class="z-50 w-80 rounded-md border bg-popover p-3 text-xs text-popover-foreground shadow-md"
          >
            <p class="mb-1 font-medium">{{ t('workspace.switch') }}</p>
            <p class="mb-2 text-muted-foreground">{{ t('workspace.switch_hint') }}</p>
            <input
              v-model="switchPath"
              type="text"
              class="mb-2 h-7 w-full rounded border bg-background px-2 font-mono"
              :placeholder="t('workspace.switch_placeholder')"
              @keydown.enter.prevent="switchTo(switchPath, true)"
            />
            <div class="flex gap-1">
              <button
                type="button"
                class="rounded border px-2 py-1 hover:bg-muted disabled:opacity-50"
                :disabled="switching || !switchPath.trim()"
                @click="switchTo(switchPath, false)"
              >
                {{ t('workspace.open') }}
              </button>
              <button
                type="button"
                class="rounded border px-2 py-1 hover:bg-muted disabled:opacity-50"
                :disabled="switching || !switchPath.trim()"
                @click="switchTo(switchPath, true)"
              >
                {{ t('workspace.create') }}
              </button>
            </div>
            <template v-if="workspace.recent.length > 1">
              <p class="mt-3 mb-1 font-medium">{{ t('workspace.recent') }}</p>
              <ul class="space-y-px">
                <li v-for="path in workspace.recent" :key="path">
                  <button
                    type="button"
                    class="w-full truncate rounded px-1 py-0.5 text-left font-mono hover:bg-muted"
                    :class="{ 'text-muted-foreground': path === workspace.root }"
                    :disabled="path === workspace.root"
                    :title="path"
                    @click="switchTo(path, false)"
                  >
                    {{ path }}
                  </button>
                </li>
              </ul>
            </template>
          </PopoverContent>
        </PopoverPortal>
      </PopoverRoot>
    </header>

    <div class="flex items-center gap-1 border-b px-2 py-1">
      <button
        type="button"
        class="inline-flex h-6 items-center gap-1 rounded border px-1.5 text-[11px] hover:bg-sidebar-accent"
        data-testid="workspace-upload"
        @click="chooseFiles"
      >
        <Upload class="size-3" /> {{ t('workspace.upload') }}
      </button>
      <input ref="fileInput" type="file" multiple class="hidden" @change="onFilesChosen" />
      <button
        type="button"
        class="inline-flex size-6 items-center justify-center rounded text-muted-foreground hover:bg-sidebar-accent hover:text-foreground"
        :title="t('workspace.new_folder')"
        :aria-label="t('workspace.new_folder')"
        @click="newFolder"
      >
        <FolderPlus class="size-3.5" />
      </button>
      <button
        type="button"
        class="inline-flex size-6 items-center justify-center rounded text-muted-foreground hover:bg-sidebar-accent hover:text-foreground"
        :title="t('workspace.refresh')"
        :aria-label="t('workspace.refresh')"
        data-testid="workspace-refresh"
        @click="workspace.refresh(uploadDir === 'uploads' && !selectedEntry ? '' : uploadDir)"
      >
        <RefreshCw class="size-3.5" />
      </button>
      <span class="ml-auto truncate font-mono text-[10px] text-muted-foreground" :title="uploadDir">
        → {{ uploadDir }}
      </span>
    </div>

    <ul
      v-if="workspace.uploads.length"
      class="border-b px-2 py-1 text-[11px]"
      data-testid="upload-list"
    >
      <li v-for="job in workspace.uploads" :key="job.id" class="flex items-center gap-2">
        <span class="min-w-0 flex-1 truncate">{{ job.name }}</span>
        <span v-if="job.state === 'uploading'" class="font-mono text-muted-foreground">
          {{ job.size ? Math.round((job.loaded / job.size) * 100) : 0 }} %
        </span>
        <span v-else-if="job.state === 'error'" class="text-destructive" :title="job.error ?? ''"
          >!</span
        >
        <span v-else class="text-muted-foreground">✓</span>
      </li>
      <li v-if="!workspace.activeUploads.length" class="text-right">
        <button
          type="button"
          class="text-muted-foreground hover:text-foreground"
          @click="workspace.clearUploads()"
        >
          {{ t('common.clear') }}
        </button>
      </li>
    </ul>

    <div class="min-h-0 flex-1 overflow-auto p-1">
      <p v-if="workspace.error" class="p-2 text-xs text-destructive">{{ workspace.error }}</p>
      <WorkspaceTree path="" @activate="addToCanvas" />
      <p class="mt-2 px-2 text-[10px] text-muted-foreground">{{ t('workspace.drop_hint') }}</p>
    </div>

    <footer
      v-if="selectedEntry && !selectedEntry.is_dir"
      class="flex items-center gap-1 border-t p-2"
    >
      <span class="min-w-0 flex-1 truncate text-[11px]" :title="selectedEntry.path">{{
        selectedEntry.name
      }}</span>
      <button
        type="button"
        class="inline-flex h-6 items-center gap-1 rounded border px-1.5 text-[11px] hover:bg-sidebar-accent disabled:opacity-50"
        :disabled="!workflow.isOpen"
        data-testid="workspace-add"
        @click="addToCanvas(selectedEntry)"
      >
        <Plus class="size-3" /> {{ t('workspace.add_to_canvas') }}
      </button>
      <DropdownMenuRoot>
        <DropdownMenuTrigger
          class="inline-flex size-6 items-center justify-center rounded text-muted-foreground hover:bg-sidebar-accent hover:text-foreground"
          :aria-label="t('workspace.actions', { name: selectedEntry.name })"
        >
          <MoreHorizontal class="size-3.5" />
        </DropdownMenuTrigger>
        <DropdownMenuPortal>
          <DropdownMenuContent
            side="top"
            align="end"
            :side-offset="4"
            class="ac-menu z-50 min-w-40 rounded-md border bg-popover p-1 text-xs text-popover-foreground shadow-md"
          >
            <DropdownMenuItem class="ac-menu-item" @select="download(selectedEntry)">
              <Download class="size-3.5" /> {{ t('workspace.download') }}
            </DropdownMenuItem>
            <DropdownMenuItem class="ac-menu-item text-destructive" @select="remove(selectedEntry)">
              <Trash2 class="size-3.5" /> {{ t('workspace.delete') }}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenuPortal>
      </DropdownMenuRoot>
    </footer>
  </section>
</template>
