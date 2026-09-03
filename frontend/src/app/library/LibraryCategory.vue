<script setup lang="ts">
import { ref } from 'vue'
import { ChevronRight } from '@lucide/vue'

import type { NodeSpec } from '@/api/types'
import type { CategoryNode } from '@/stores/nodesSchema'
import LibraryItem from './LibraryItem.vue'

defineProps<{ category: CategoryNode; favorites: Set<string>; depth: number }>()
const emit = defineEmits<{ add: [spec: NodeSpec]; 'toggle-favorite': [spec: NodeSpec] }>()
const open = ref(true)
</script>

<template>
  <li>
    <button
      type="button"
      class="flex w-full items-center gap-1 rounded-md px-1 py-1 text-left text-xs font-semibold text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      :aria-expanded="open"
      :style="{ paddingLeft: `${4 + depth * 10}px` }"
      @click="open = !open"
    >
      <ChevronRight
        class="size-3 transition-transform"
        :class="{ 'rotate-90': open }"
        aria-hidden="true"
      />
      {{ category.label }}
      <span class="ml-auto font-normal">{{ category.nodes.length }}</span>
    </button>
    <ul v-show="open" class="space-y-px" :style="{ paddingLeft: `${8 + depth * 10}px` }">
      <LibraryCategory
        v-for="child in category.children"
        :key="child.path"
        :category="child"
        :favorites="favorites"
        :depth="depth + 1"
        @add="emit('add', $event)"
        @toggle-favorite="emit('toggle-favorite', $event)"
      />
      <LibraryItem
        v-for="spec in category.nodes"
        :key="spec.id"
        :spec="spec"
        :favorite="favorites.has(spec.id)"
        @add="emit('add', $event)"
        @toggle-favorite="emit('toggle-favorite', $event)"
      />
    </ul>
  </li>
</template>
