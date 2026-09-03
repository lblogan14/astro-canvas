<script setup lang="ts">
/** Workflows sidebar: list, create, rename, duplicate, delete, open; versions with restore. */
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import {
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuPortal,
  DropdownMenuRoot,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from 'reka-ui'
import { Copy, History, MoreHorizontal, Pencil, Plus, RotateCcw, Trash2 } from '@lucide/vue'

import type { WorkflowSummary } from '@/api/types'
import { Button } from '@/components/ui/button'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'
import { useWorkflowsStore } from '@/stores/workflows'

const { t, d } = useI18n()
const router = useRouter()
const workflows = useWorkflowsStore()
const workflow = useWorkflowStore()
const session = useSessionStore()
const ui = useUiStore()

const renaming = ref<string | null>(null)
const renameDraft = ref('')
const showVersions = ref(false)

onMounted(() => void workflows.refresh())
watch(
  () => workflow.saveState,
  (state) => {
    if (state === 'saved') void workflows.refresh()
  },
)

const currentId = computed(() => workflow.id)

async function create(): Promise<void> {
  const id = await session.createWorkflow(t('workflows.untitled'))
  await workflows.refresh()
  await router.push({ name: 'workflow', params: { id } })
}

function open(item: WorkflowSummary): void {
  if (item.id === currentId.value) return
  void router.push({ name: 'workflow', params: { id: item.id } })
}

function startRename(item: WorkflowSummary): void {
  renaming.value = item.id
  renameDraft.value = item.name
}

async function commitRename(item: WorkflowSummary): Promise<void> {
  if (renaming.value !== item.id) return
  renaming.value = null
  const name = renameDraft.value.trim()
  if (!name || name === item.name) return
  if (item.id === currentId.value) {
    workflow.rename(name)
    await workflow.saveNow()
  } else {
    const { api } = await import('@/api/client')
    const doc = await api.getWorkflow(item.id)
    await api.putWorkflow({ ...doc, name })
  }
  await workflows.refresh()
}

async function duplicate(item: WorkflowSummary): Promise<void> {
  const id = await workflows.duplicate(item.id)
  ui.notify(t('workflows.duplicated', { name: item.name }))
  await router.push({ name: 'workflow', params: { id } })
}

async function remove(item: WorkflowSummary): Promise<void> {
  if (!window.confirm(t('workflows.confirm_delete', { name: item.name }))) return
  await workflows.remove(item.id)
  if (item.id === currentId.value) {
    session.closeWorkflow()
    const next = workflows.items[0]
    await router.push(next ? { name: 'workflow', params: { id: next.id } } : { name: 'home' })
  }
}

async function toggleVersions(): Promise<void> {
  showVersions.value = !showVersions.value
  if (showVersions.value && currentId.value) await workflows.loadVersions(currentId.value)
}

async function restore(versionId: number): Promise<void> {
  if (!currentId.value) return
  const doc = await workflows.fetchVersion(currentId.value, versionId)
  workflow.replaceContent(doc)
  ui.notify(t('workflows.restored', { id: versionId }))
}

function formatDate(iso: string): string {
  try {
    return d(new Date(iso), 'short')
  } catch {
    return iso
  }
}
</script>

<template>
  <section
    class="flex h-full flex-col"
    :aria-label="t('workflows.title')"
    data-testid="workflows-panel"
  >
    <div class="flex items-center justify-between border-b p-2">
      <h2 class="px-1 text-xs font-semibold">{{ t('workflows.title') }}</h2>
      <Button size="xs" variant="outline" data-testid="new-workflow" @click="create">
        <Plus /> {{ t('workflows.new') }}
      </Button>
    </div>
    <div class="min-h-0 flex-1 overflow-auto p-1">
      <p v-if="workflows.error" class="p-2 text-xs text-destructive">{{ workflows.error }}</p>
      <p
        v-else-if="!workflows.items.length && !workflows.loading"
        class="p-3 text-xs text-muted-foreground"
      >
        {{ t('workflows.empty') }}
      </p>
      <ul class="space-y-px" role="list">
        <li
          v-for="item in workflows.items"
          :key="item.id"
          class="group flex items-center gap-1 rounded-md hover:bg-muted"
          :class="{ 'bg-muted': item.id === currentId }"
          :data-workflow-id="item.id"
          :aria-current="item.id === currentId ? 'true' : undefined"
        >
          <input
            v-if="renaming === item.id"
            v-model="renameDraft"
            class="mx-1 h-7 min-w-0 flex-1 rounded border bg-background px-1 text-xs"
            :aria-label="t('workflows.rename')"
            @keydown.enter.prevent="commitRename(item)"
            @keydown.escape.prevent="renaming = null"
            @blur="commitRename(item)"
          />
          <button
            v-else
            type="button"
            class="flex min-w-0 flex-1 flex-col items-start rounded-md px-2 py-1 text-left focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            @click="open(item)"
            @dblclick="startRename(item)"
          >
            <span class="w-full truncate text-xs font-medium">{{ item.name }}</span>
            <span class="text-[10px] text-muted-foreground">
              {{ t('workflows.nodes_count', item.node_count) }} · {{ formatDate(item.modified) }}
            </span>
          </button>
          <DropdownMenuRoot>
            <DropdownMenuTrigger
              class="mr-1 inline-flex size-6 shrink-0 items-center justify-center rounded text-muted-foreground opacity-0 group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100 hover:text-foreground"
              :aria-label="t('workflows.actions', { name: item.name })"
            >
              <MoreHorizontal class="size-3.5" />
            </DropdownMenuTrigger>
            <DropdownMenuPortal>
              <DropdownMenuContent
                align="end"
                :side-offset="4"
                class="z-50 min-w-40 rounded-md border bg-popover p-1 text-xs text-popover-foreground shadow-md"
              >
                <DropdownMenuItem class="ac-menu-item" @select="startRename(item)">
                  <Pencil class="size-3.5" /> {{ t('workflows.rename') }}
                </DropdownMenuItem>
                <DropdownMenuItem class="ac-menu-item" @select="duplicate(item)">
                  <Copy class="size-3.5" /> {{ t('workflows.duplicate') }}
                </DropdownMenuItem>
                <DropdownMenuSeparator class="my-1 h-px bg-border" />
                <DropdownMenuItem class="ac-menu-item text-destructive" @select="remove(item)">
                  <Trash2 class="size-3.5" /> {{ t('workflows.delete') }}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenuPortal>
          </DropdownMenuRoot>
        </li>
      </ul>
    </div>

    <div v-if="currentId" class="border-t">
      <button
        type="button"
        class="flex w-full items-center gap-2 px-3 py-2 text-xs font-semibold hover:bg-muted"
        :aria-expanded="showVersions"
        data-testid="toggle-versions"
        @click="toggleVersions"
      >
        <History class="size-3.5" /> {{ t('workflows.versions') }}
        <span class="ml-auto text-muted-foreground">{{ showVersions ? '−' : '+' }}</span>
      </button>
      <ul v-if="showVersions" class="max-h-48 space-y-px overflow-auto px-1 pb-1" role="list">
        <li v-if="!workflows.versions.length" class="px-2 py-1 text-[11px] text-muted-foreground">
          {{ t('workflows.no_versions') }}
        </li>
        <li
          v-for="version in workflows.versions"
          :key="version.id"
          class="flex items-center gap-2 rounded-md px-2 py-1 text-[11px] hover:bg-muted"
          :data-version-id="version.id"
        >
          <span class="min-w-0 flex-1 truncate">
            {{ version.label || t('workflows.version_label', { id: version.id }) }}
            <span class="text-muted-foreground"> · {{ formatDate(version.created) }}</span>
          </span>
          <button
            type="button"
            class="inline-flex size-6 items-center justify-center rounded text-muted-foreground hover:bg-background hover:text-foreground"
            :aria-label="t('workflows.restore', { id: version.id })"
            @click="restore(version.id)"
          >
            <RotateCcw class="size-3.5" />
          </button>
        </li>
      </ul>
    </div>
  </section>
</template>
