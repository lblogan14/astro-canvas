<script setup lang="ts">
/**
 * Dashboard mode (design 8.4): a draggable, resizable grid of pinned views and promoted-param
 * panels, with **linked selection** between the views — dragging a wavelength range on a curve
 * highlights the rows of every table fed by the same upstream node (glue/Jdaviz-like).
 *
 * The grid is locked by default: a dashboard is something you *use*, and only *Edit* turns the
 * tiles into handles. Layout changes stay in a local draft until *Save layout* writes
 * `layouts.dashboard`, which keeps opening a template from dirtying it.
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { GridItem, GridLayout } from 'grid-layout-plus'
import { Ban, Download, Lock, LockOpen, Play, Save, Workflow, X } from '@lucide/vue'

import { Button } from '@/components/ui/button'
import { useLinkedStore } from '@/stores/linked'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'
import PromotedField from './PromotedField.vue'
import ViewTile from './ViewTile.vue'
import {
  type DashboardLayout,
  type DashboardTile,
  defaultDashboardLayout,
  readDashboardLayout,
} from './layouts'
import { useMode } from './useMode'

const { t } = useI18n()
const workflow = useWorkflowStore()
const ui = useUiStore()
const links = useLinkedStore()
const mode = useMode()

const editing = ref(false)
const draft = ref<DashboardLayout | null>(null)
const exported = ref<string | null>(null)

const layout = computed<DashboardLayout>(
  () =>
    draft.value ??
    readDashboardLayout(workflow.layouts) ??
    defaultDashboardLayout(workflow.promotedList, workflow.views),
)

/** Grid items in `grid-layout-plus`'s shape, one per resolvable tile. */
interface Tile extends DashboardTile {
  i: string
  item: NonNullable<ReturnType<typeof mode.resolve>['resolved'][number]>
}

const tiles = computed<Tile[]>(() => {
  const out: Tile[] = []
  for (const tile of layout.value.items) {
    const [item] = mode.resolve([tile.ref]).resolved
    if (item) out.push({ ...tile, i: tile.ref, item })
  }
  return out
})
const missing = computed(() => mode.resolve(layout.value.items.map((tile) => tile.ref)).missing)
const isEmpty = computed(() => tiles.value.length === 0 && missing.value.length === 0)
const nodeIds = computed(() => mode.nodesOf(tiles.value.map((tile) => tile.item)))
const problems = computed(() => mode.problemsOf(nodeIds.value))

// The live selection belongs to the tiles on screen; adding or removing one drops it.
watch(
  () => layout.value.items.map((tile) => tile.ref).join('|'),
  () => links.clear(),
)

function beginEdit(): void {
  draft.value = {
    ...layout.value,
    items: layout.value.items.map((tile) => ({ ...tile })),
  }
  editing.value = true
}

/**
 * grid-layout-plus reports every position it settles on, including the ones it just took from
 * us, so the draft is only rewritten when a tile actually moved — writing back unconditionally
 * feeds the grid a new array and it emits again, forever.
 */
function onLayoutUpdated(
  next: readonly { i: string; x: number; y: number; w: number; h: number }[],
) {
  if (!editing.value) return
  const byRef = new Map(next.map((tile) => [tile.i, tile]))
  let changed = false
  const items = layout.value.items.map((tile) => {
    const moved = byRef.get(tile.ref)
    if (!moved) return tile
    if (moved.x === tile.x && moved.y === tile.y && moved.w === tile.w && moved.h === tile.h)
      return tile
    changed = true
    return { ...tile, x: moved.x, y: moved.y, w: moved.w, h: moved.h }
  })
  if (changed) draft.value = { ...layout.value, items }
}

function removeTile(ref: string): void {
  if (!draft.value) beginEdit()
  draft.value = {
    ...layout.value,
    items: layout.value.items.filter((tile) => tile.ref !== ref),
  }
}

function saveLayout(): void {
  workflow.setLayout('dashboard', layout.value, 'command.layout_dashboard')
  workflow.scheduleSave()
  draft.value = null
  editing.value = false
  ui.notify(t('modes.layout_saved'))
}

function discard(): void {
  draft.value = null
  editing.value = false
}

async function exportResults(): Promise<void> {
  const dir = await mode.exportResults()
  exported.value = dir
  if (dir) ui.notify(t('modes.exported', { dir }))
}

const selectionLabel = computed(() => {
  const selection = links.selection
  if (!selection) return null
  return selection.kind === 'range'
    ? t('dashboard.range', {
        axis: selection.axis,
        lo: selection.lo.toPrecision(6),
        hi: selection.hi.toPrecision(6),
      })
    : t('dashboard.rows', { n: selection.rows.length })
})
</script>

<template>
  <div class="flex h-full min-h-0 flex-col bg-background" data-testid="dashboard-mode">
    <div class="flex shrink-0 flex-wrap items-center gap-1 border-b px-2 py-1.5">
      <Button
        v-if="!mode.running.value"
        size="sm"
        :disabled="!workflow.isOpen"
        data-testid="dashboard-run"
        @click="mode.run()"
      >
        <Play /> {{ t('modes.run') }}
      </Button>
      <Button
        v-else
        size="sm"
        variant="destructive"
        data-testid="dashboard-cancel"
        @click="mode.cancel()"
      >
        <Ban /> {{ t('toolbar.cancel') }}
      </Button>

      <span
        v-if="selectionLabel"
        class="inline-flex items-center gap-1 rounded bg-primary/10 px-1.5 py-0.5 text-[11px] text-primary"
        data-testid="dashboard-selection"
      >
        {{ selectionLabel }}
        <button
          type="button"
          :aria-label="t('dashboard.clear_selection')"
          data-testid="dashboard-clear-selection"
          @click="links.clear()"
        >
          <X class="size-3" />
        </button>
      </span>

      <span class="flex-1" />

      <Button
        size="sm"
        variant="ghost"
        :aria-pressed="editing"
        :title="editing ? t('dashboard.lock_hint') : t('dashboard.unlock_hint')"
        data-testid="dashboard-edit"
        @click="editing ? discard() : beginEdit()"
      >
        <LockOpen v-if="editing" /> <Lock v-else />
        {{ editing ? t('dashboard.lock') : t('dashboard.unlock') }}
      </Button>
      <Button
        v-if="editing || draft"
        size="sm"
        variant="ghost"
        data-testid="dashboard-save-layout"
        @click="saveLayout"
      >
        <Save /> {{ t('modes.save_layout') }}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        :disabled="mode.exportRefs.value.length === 0"
        data-testid="dashboard-export"
        @click="exportResults"
      >
        <Download /> {{ t('modes.export') }}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        data-testid="dashboard-show-graph"
        @click="ui.setMode('canvas')"
      >
        <Workflow /> {{ t('modes.show_graph') }}
      </Button>
    </div>

    <p
      v-if="isEmpty"
      class="p-6 text-center text-xs text-muted-foreground"
      data-testid="dashboard-empty"
    >
      {{ t('modes.empty') }}
    </p>

    <div v-else class="min-h-0 flex-1 overflow-auto p-2">
      <GridLayout
        :layout="tiles"
        :col-num="layout.cols"
        :row-height="layout.row_height"
        :is-draggable="editing"
        :is-resizable="editing"
        :margin="[8, 8]"
        :responsive="false"
        vertical-compact
        @layout-updated="onLayoutUpdated"
      >
        <GridItem
          v-for="tile in tiles"
          :key="tile.i"
          :i="tile.i"
          :x="tile.x"
          :y="tile.y"
          :w="tile.w"
          :h="tile.h"
          drag-allow-from=".ac-tile-handle"
          :data-testid="`dashboard-tile-${tile.ref}`"
        >
          <div class="relative h-full">
            <ViewTile
              v-if="tile.item.kind === 'view'"
              :view="tile.item.view"
              :label="tile.item.label"
              linked
              compact
            />
            <section
              v-else
              class="flex h-full flex-col overflow-hidden rounded-lg border bg-card"
              :data-testid="`dashboard-param-${tile.item.ref}`"
            >
              <h2
                class="ac-tile-handle flex h-6 shrink-0 items-center border-b px-2 text-[11px] font-medium"
                :class="editing ? 'cursor-move' : ''"
              >
                {{ tile.item.label }}
              </h2>
              <div class="min-h-0 flex-1 overflow-auto p-2">
                <PromotedField :item="tile.item" compact />
              </div>
            </section>
            <span
              v-if="editing"
              class="ac-tile-handle absolute inset-x-0 top-0 h-6 cursor-move"
              aria-hidden="true"
            />
            <button
              v-if="editing"
              type="button"
              class="absolute top-0.5 right-6 z-10 inline-flex size-5 items-center justify-center rounded bg-background/80 text-muted-foreground hover:text-destructive"
              :aria-label="t('dashboard.remove_tile', { label: tile.item.label })"
              :data-testid="`dashboard-remove-${tile.ref}`"
              @click="removeTile(tile.ref)"
            >
              <X class="size-3" />
            </button>
          </div>
        </GridItem>
      </GridLayout>

      <ul
        v-if="problems.length"
        class="mt-2 space-y-0.5 rounded-lg border border-destructive/40 bg-destructive/5 p-2 text-[11px] text-destructive"
        data-testid="dashboard-problems"
      >
        <li v-for="(problem, index) in problems" :key="index">
          {{ problem.node }}: {{ problem.message }}
        </li>
      </ul>
      <ul
        v-if="missing.length"
        class="mt-2 space-y-0.5 rounded-lg border border-amber-500/40 bg-amber-500/5 p-2 text-[11px] text-amber-700"
        data-testid="dashboard-missing"
      >
        <li v-for="ref in missing" :key="ref">{{ t('modes.missing_item', { ref }) }}</li>
      </ul>
      <p
        v-if="exported"
        class="mt-2 text-[11px] text-muted-foreground"
        data-testid="dashboard-exported"
      >
        {{ t('modes.exported', { dir: exported }) }}
      </p>
    </div>
  </div>
</template>
