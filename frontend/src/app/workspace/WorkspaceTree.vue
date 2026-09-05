<script setup lang="ts">
/**
 * Recursive, lazily loaded folder tree over the workspace store. Files are draggable onto the
 * canvas; `selectable` mode (the file picker) emits `pick` on click instead.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ChevronDown,
  ChevronRight,
  File,
  FileText,
  Folder,
  FolderOpen,
  Image,
  Table,
} from '@lucide/vue'

import type { WorkspaceEntry } from '@/api/types'
import { setFileDragData } from '@/canvas/dnd'
import { useWorkspaceStore } from '@/stores/workspace'

const props = withDefaults(
  defineProps<{
    path: string
    depth?: number
    selectable?: boolean
    /** Only show files whose name matches (case-insensitive substring). */
    filter?: string
  }>(),
  { depth: 0, selectable: false, filter: '' },
)

const emit = defineEmits<{
  pick: [entry: WorkspaceEntry]
  activate: [entry: WorkspaceEntry]
}>()

const { t } = useI18n()
const workspace = useWorkspaceStore()

const entries = computed(() => {
  const list = workspace.entriesOf(props.path) ?? []
  const needle = props.filter.trim().toLowerCase()
  if (!needle) return list
  return list.filter((e) => e.is_dir || e.name.toLowerCase().includes(needle))
})
const loading = computed(() => workspace.loading.has(props.path))

function iconFor(entry: WorkspaceEntry) {
  if (entry.is_dir) return workspace.expanded.has(entry.path) ? FolderOpen : Folder
  const mime = entry.mime ?? ''
  const name = entry.name.toLowerCase()
  if (mime === 'application/fits' || name.endsWith('.fits') || name.endsWith('.fit')) return Image
  if (mime.startsWith('text/') || name.endsWith('.csv') || name.endsWith('.ecsv')) return Table
  if (name.endsWith('.json') || name.endsWith('.dat') || name.endsWith('.txt')) return FileText
  return File
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

function onClick(entry: WorkspaceEntry): void {
  if (entry.is_dir) {
    void workspace.toggle(entry.path)
    return
  }
  workspace.select(entry.path)
  if (props.selectable) emit('pick', entry)
}

function onDoubleClick(entry: WorkspaceEntry): void {
  if (!entry.is_dir) emit('activate', entry)
}

function onKeydown(event: KeyboardEvent, entry: WorkspaceEntry): void {
  if (event.key === 'Enter') {
    event.preventDefault()
    if (entry.is_dir) void workspace.toggle(entry.path)
    else if (props.selectable) emit('pick', entry)
    else emit('activate', entry)
  } else if (event.key === 'ArrowRight' && entry.is_dir) {
    void workspace.expand(entry.path)
  } else if (event.key === 'ArrowLeft' && entry.is_dir) {
    workspace.collapse(entry.path)
  }
}

function onDragStart(event: DragEvent, entry: WorkspaceEntry): void {
  if (entry.is_dir) {
    event.preventDefault()
    return
  }
  setFileDragData(event, entry.path)
}
</script>

<template>
  <!-- The root list is the tree; every nested level is a `group` inside its own `treeitem`, and
       `aria-level` belongs on the items rather than on the list (ARIA 1.2). -->
  <ul class="space-y-px" :role="depth === 0 ? 'tree' : 'group'">
    <li
      v-if="loading && !entries.length"
      role="none"
      class="px-2 py-1 text-[11px] text-muted-foreground"
    >
      {{ t('common.loading') }}
    </li>
    <li v-else-if="!entries.length" role="none" class="px-2 py-1 text-[11px] text-muted-foreground">
      {{ t('workspace.empty') }}
    </li>
    <li
      v-for="entry in entries"
      :key="entry.path"
      role="treeitem"
      :aria-level="depth + 1"
      :aria-selected="workspace.selectedPath === entry.path"
      :aria-expanded="entry.is_dir ? workspace.expanded.has(entry.path) : undefined"
    >
      <div
        class="flex h-6 cursor-pointer items-center gap-1 rounded pr-1 text-xs hover:bg-sidebar-accent"
        :class="{ 'bg-sidebar-accent font-medium': workspace.selectedPath === entry.path }"
        :style="{ paddingLeft: `${depth * 12 + 4}px` }"
        :draggable="!entry.is_dir"
        :title="entry.path"
        tabindex="0"
        data-testid="workspace-entry"
        :data-path="entry.path"
        :data-dir="entry.is_dir"
        @click="onClick(entry)"
        @dblclick="onDoubleClick(entry)"
        @keydown="onKeydown($event, entry)"
        @dragstart="onDragStart($event, entry)"
      >
        <span class="inline-flex size-4 shrink-0 items-center justify-center text-muted-foreground">
          <template v-if="entry.is_dir">
            <ChevronDown v-if="workspace.expanded.has(entry.path)" class="size-3" />
            <ChevronRight v-else class="size-3" />
          </template>
        </span>
        <component
          :is="iconFor(entry)"
          class="size-3.5 shrink-0 text-muted-foreground"
          aria-hidden="true"
        />
        <span class="min-w-0 flex-1 truncate">{{ entry.name }}</span>
        <span v-if="!entry.is_dir" class="shrink-0 font-mono text-[10px] text-muted-foreground">
          {{ formatSize(entry.size) }}
        </span>
      </div>
      <WorkspaceTree
        v-if="entry.is_dir && workspace.expanded.has(entry.path)"
        :path="entry.path"
        :depth="depth + 1"
        :selectable="selectable"
        :filter="filter"
        @pick="emit('pick', $event)"
        @activate="emit('activate', $event)"
      />
    </li>
  </ul>
</template>
