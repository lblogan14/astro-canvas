<script setup lang="ts">
/** Node Library sidebar: fuzzy search, category tree, favourites, drag/double-click to add. */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Fuse from 'fuse.js'
import { Search, X } from '@lucide/vue'

import type { NodeSpec } from '@/api/types'
import { useCanvasAdapter } from '@/canvas/CanvasAdapter'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useSelectionStore } from '@/stores/selection'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'
import LibraryCategory from './LibraryCategory.vue'
import LibraryItem from './LibraryItem.vue'

const { t } = useI18n()
const schema = useNodesSchemaStore()
const workflow = useWorkflowStore()
const selection = useSelectionStore()
const ui = useUiStore()
const canvas = useCanvasAdapter()

const query = ref('')

const fuse = computed(
  () =>
    new Fuse(schema.specs, {
      keys: [
        { name: 'name', weight: 3 },
        { name: 'id', weight: 2 },
        { name: 'category', weight: 1 },
        { name: 'description', weight: 1 },
      ],
      threshold: 0.4,
      ignoreLocation: true,
    }),
)

const results = computed<NodeSpec[]>(() => {
  const q = query.value.trim()
  if (!q) return []
  return fuse.value.search(q, { limit: 40 }).map((r) => r.item)
})

const favorites = computed(() => schema.specs.filter((s) => ui.favoriteSet.has(s.id)))

function addAtCenter(spec: NodeSpec): void {
  if (!workflow.isOpen) return
  const center = canvas.value?.viewportCenter() ?? { x: 0, y: 0 }
  const jitter = Math.round(Math.random() * 40 - 20)
  const id = workflow.addNode(spec, [
    Math.round(center.x - 120 + jitter),
    Math.round(center.y - 40 + jitter),
  ])
  selection.set([id])
}
</script>

<template>
  <section class="flex h-full flex-col" :aria-label="t('library.title')" data-testid="node-library">
    <div class="relative border-b p-2">
      <Search
        class="pointer-events-none absolute top-1/2 left-4 size-3.5 -translate-y-1/2 text-muted-foreground"
      />
      <input
        v-model="query"
        type="search"
        class="h-8 w-full rounded-md border bg-background pr-7 pl-7 text-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        :placeholder="t('library.search')"
        :aria-label="t('library.search')"
        data-testid="library-search"
      />
      <button
        v-if="query"
        type="button"
        class="absolute top-1/2 right-4 -translate-y-1/2 text-muted-foreground hover:text-foreground"
        :aria-label="t('common.clear')"
        @click="query = ''"
      >
        <X class="size-3.5" />
      </button>
    </div>

    <div class="min-h-0 flex-1 overflow-auto p-1">
      <p v-if="schema.status === 'loading'" class="p-3 text-xs text-muted-foreground">
        {{ t('common.loading') }}
      </p>
      <p v-else-if="schema.status === 'error'" class="p-3 text-xs text-destructive">
        {{ schema.error }}
      </p>

      <template v-else-if="query">
        <ul v-if="results.length" class="space-y-px" role="list">
          <LibraryItem
            v-for="spec in results"
            :key="spec.id"
            :spec="spec"
            :favorite="ui.favoriteSet.has(spec.id)"
            show-category
            @add="addAtCenter"
            @toggle-favorite="ui.toggleFavorite($event.id)"
          />
        </ul>
        <p v-else class="p-3 text-xs text-muted-foreground">
          {{ t('library.no_results', { query }) }}
        </p>
      </template>

      <template v-else>
        <template v-if="favorites.length">
          <h3
            class="px-2 pt-1 pb-0.5 text-[10px] font-semibold tracking-wide text-muted-foreground uppercase"
          >
            {{ t('library.favorites') }}
          </h3>
          <ul class="mb-2 space-y-px" role="list">
            <LibraryItem
              v-for="spec in favorites"
              :key="spec.id"
              :spec="spec"
              favorite
              show-category
              @add="addAtCenter"
              @toggle-favorite="ui.toggleFavorite($event.id)"
            />
          </ul>
        </template>
        <ul class="space-y-px" role="tree">
          <LibraryCategory
            v-for="category in schema.categories"
            :key="category.path"
            :category="category"
            :favorites="ui.favoriteSet"
            :depth="0"
            @add="addAtCenter"
            @toggle-favorite="ui.toggleFavorite($event.id)"
          />
        </ul>
      </template>
    </div>
    <p class="border-t px-3 py-1.5 text-[10px] text-muted-foreground">
      {{ t('library.drag_hint') }}
    </p>
  </section>
</template>
