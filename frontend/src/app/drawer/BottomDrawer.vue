<script setup lang="ts">
/** Bottom drawer: run log, node errors / compile issues, and `/api/system` stats. */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { X } from '@lucide/vue'

import { api } from '@/api/client'
import type { SystemInfo } from '@/api/types'
import { useExecutionStore } from '@/stores/execution'
import { useSelectionStore } from '@/stores/selection'
import { type DrawerTab, useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'

const { t, n } = useI18n()
const ui = useUiStore()
const execution = useExecutionStore()
const selection = useSelectionStore()
const workflow = useWorkflowStore()

const TABS: DrawerTab[] = ['log', 'errors', 'system']

/**
 * Roving tabindex plus Left/Right/Home/End, which is what `role="tablist"` promises a keyboard
 * user. Only the selected tab is in the tab order; the arrows move between them.
 */
function onTabKey(event: KeyboardEvent, tab: DrawerTab): void {
  const keys: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1 }
  const index = TABS.indexOf(tab)
  let next = index
  if (event.key in keys) next = (index + keys[event.key]! + TABS.length) % TABS.length
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = TABS.length - 1
  else return
  event.preventDefault()
  const target = TABS[next]
  if (target === undefined) return
  ui.drawerTab = target
  document.getElementById(`drawer-tab-${target}`)?.focus()
}
const system = ref<SystemInfo | null>(null)
const systemError = ref<string | null>(null)

watch(
  () => [ui.drawerOpen, ui.drawerTab] as const,
  async ([open, tab]) => {
    if (open && tab === 'system') {
      try {
        system.value = await api.getSystem()
        systemError.value = null
      } catch (err) {
        systemError.value = err instanceof Error ? err.message : String(err)
      }
    }
  },
  { immediate: true },
)

const problems = computed(() => {
  const rows: { nodeId: string; code: string; message: string; hint: string | null }[] = []
  for (const [nodeId, issues] of Object.entries(execution.issues)) {
    for (const issue of issues)
      rows.push({ nodeId, code: issue.code, message: issue.message, hint: null })
  }
  for (const nodeId of execution.errorNodeIds) {
    const error = execution.node(nodeId).error
    // The hint is the whole point of the errors tab: it is what the user can do next.
    if (error) rows.push({ nodeId, code: 'error', message: error.message, hint: error.hint })
  }
  return rows
})

function nodeTitle(nodeId: string): string {
  return workflow.nodes[nodeId]?.title ?? nodeId
}

function formatTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString()
}

function gib(bytes: number): string {
  return n(bytes / 1024 ** 3, { maximumFractionDigits: 1 })
}
</script>

<template>
  <section
    class="flex h-full flex-col border-t bg-background text-xs"
    :aria-label="t('drawer.title')"
    data-testid="drawer"
  >
    <div class="flex items-center gap-1 border-b px-2">
      <!-- Only the tabs go inside the tablist: Clear and Close are not tabs (`aria-required-
           children`), and a tablist that contains them is what axe flags. -->
      <div class="flex items-center gap-1" role="tablist" :aria-label="t('drawer.title')">
        <button
          v-for="tab in TABS"
          :key="tab"
          :id="`drawer-tab-${tab}`"
          type="button"
          role="tab"
          class="relative px-2 py-1.5 text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none aria-selected:text-foreground"
          :aria-selected="ui.drawerTab === tab"
          :aria-controls="'drawer-panel'"
          :tabindex="ui.drawerTab === tab ? 0 : -1"
          :data-tab="tab"
          @click="ui.drawerTab = tab"
          @keydown="onTabKey($event, tab)"
        >
          {{ t(`drawer.${tab}`) }}
          <span
            v-if="tab === 'errors' && problems.length"
            class="ml-1 rounded-full bg-destructive/15 px-1.5 text-[10px] text-destructive"
            >{{ problems.length }}</span
          >
          <span
            v-if="ui.drawerTab === tab"
            class="absolute inset-x-1 bottom-0 h-0.5 bg-foreground"
            aria-hidden="true"
          />
        </button>
      </div>
      <span class="flex-1" />
      <button
        v-if="ui.drawerTab === 'log'"
        type="button"
        class="px-2 text-muted-foreground hover:text-foreground"
        @click="execution.clearLog()"
      >
        {{ t('drawer.clear') }}
      </button>
      <button
        type="button"
        class="inline-flex size-6 items-center justify-center rounded text-muted-foreground hover:text-foreground"
        :aria-label="t('common.close')"
        @click="ui.drawerOpen = false"
      >
        <X class="size-3.5" />
      </button>
    </div>

    <div
      id="drawer-panel"
      class="min-h-0 flex-1 overflow-auto font-mono text-[11px]"
      role="tabpanel"
      tabindex="0"
      :aria-labelledby="`drawer-tab-${ui.drawerTab}`"
    >
      <template v-if="ui.drawerTab === 'log'">
        <p v-if="!execution.log.length" class="p-3 font-sans text-muted-foreground">
          {{ t('drawer.empty_log') }}
        </p>
        <ol v-else class="divide-y">
          <li
            v-for="entry in execution.log"
            :key="entry.id"
            class="flex gap-3 px-3 py-0.5"
            :class="{
              'text-destructive': entry.level === 'error',
              'text-amber-700 dark:text-amber-400': entry.level === 'warning',
            }"
          >
            <span class="shrink-0 text-muted-foreground">{{ formatTime(entry.ts) }}</span>
            <span class="w-14 shrink-0 uppercase">{{ entry.level }}</span>
            <button
              v-if="entry.nodeId"
              type="button"
              class="shrink-0 underline-offset-2 hover:underline"
              @click="selection.set([entry.nodeId])"
            >
              {{ nodeTitle(entry.nodeId) }}
            </button>
            <span class="min-w-0 break-words">{{ entry.message }}</span>
          </li>
        </ol>
      </template>

      <template v-else-if="ui.drawerTab === 'errors'">
        <p v-if="!problems.length" class="p-3 font-sans text-muted-foreground">
          {{ t('drawer.no_errors') }}
        </p>
        <ul v-else class="divide-y">
          <li v-for="(row, i) in problems" :key="i" class="flex gap-3 px-3 py-1">
            <button
              type="button"
              class="shrink-0 font-semibold hover:underline"
              @click="selection.set([row.nodeId])"
            >
              {{ nodeTitle(row.nodeId) }}
            </button>
            <code class="shrink-0 rounded bg-muted px-1">{{ row.code }}</code>
            <span class="min-w-0 break-words">
              {{ row.message }}
              <span v-if="row.hint" class="text-muted-foreground">— {{ row.hint }}</span>
            </span>
          </li>
        </ul>
      </template>

      <template v-else>
        <p v-if="systemError" class="p-3 text-destructive">{{ systemError }}</p>
        <dl v-else-if="system" class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 p-3 font-sans">
          <dt class="text-muted-foreground">{{ t('drawer.system.version') }}</dt>
          <dd>{{ system.version }}</dd>
          <dt class="text-muted-foreground">{{ t('drawer.system.python') }}</dt>
          <dd>{{ system.python }}</dd>
          <dt class="text-muted-foreground">{{ t('drawer.system.platform') }}</dt>
          <dd>{{ system.platform }}</dd>
          <dt class="text-muted-foreground">{{ t('drawer.system.workspace') }}</dt>
          <dd class="font-mono">{{ system.workspace }}</dd>
          <dt class="text-muted-foreground">{{ t('drawer.system.disk') }}</dt>
          <dd>
            {{
              t('drawer.system.disk_value', {
                free: gib(system.disk_free_bytes),
                total: gib(system.disk_total_bytes),
              })
            }}
          </dd>
          <dt class="text-muted-foreground">{{ t('drawer.system.packs') }}</dt>
          <dd>
            <span
              v-for="pack in system.packs"
              :key="pack.name"
              class="mr-2 rounded bg-muted px-1.5"
            >
              {{ pack.name }} {{ pack.version }} ({{ pack.node_count }})
            </span>
          </dd>
        </dl>
        <p v-else class="p-3 font-sans text-muted-foreground">{{ t('common.loading') }}</p>
      </template>
    </div>
  </section>
</template>
