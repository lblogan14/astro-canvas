<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Star, Zap } from '@lucide/vue'

import type { NodeSpec } from '@/api/types'
import { setNodeDragData } from '@/canvas/dnd'
import { portStyle } from '@/canvas/ports'

const props = defineProps<{ spec: NodeSpec; favorite: boolean; showCategory?: boolean }>()
const emit = defineEmits<{ add: [spec: NodeSpec]; 'toggle-favorite': [spec: NodeSpec] }>()
const { t } = useI18n()

function accent(): string {
  const type = props.spec.outputs[0]?.type ?? props.spec.inputs[0]?.type ?? 'astro.Any'
  return portStyle(type).color
}
</script>

<template>
  <li class="group flex items-center gap-1 rounded-md hover:bg-muted" :data-node-type="spec.id">
    <button
      type="button"
      class="flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1 text-left text-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      draggable="true"
      :title="`${spec.description || spec.name}\n${spec.id}`"
      :aria-label="t('library.add_hint', { name: spec.name })"
      @dragstart="setNodeDragData($event, spec.id)"
      @dblclick="emit('add', spec)"
      @keydown.enter.prevent="emit('add', spec)"
    >
      <span
        class="size-2 shrink-0 rounded-full"
        :style="{ background: accent() }"
        aria-hidden="true"
      />
      <span class="min-w-0 flex-1">
        <span class="block truncate font-medium">{{ spec.name }}</span>
        <span v-if="showCategory" class="block truncate text-[10px] text-muted-foreground">
          {{ spec.category }}
        </span>
      </span>
      <Zap
        v-if="spec.cost === 'expensive'"
        class="size-3 shrink-0 text-muted-foreground"
        :title="t('node.cost.expensive')"
      />
      <span
        class="shrink-0 rounded bg-muted px-1 text-[10px] text-muted-foreground group-hover:bg-background"
      >
        {{ spec.pack }}
      </span>
    </button>
    <button
      type="button"
      class="mr-1 inline-flex size-6 shrink-0 items-center justify-center rounded text-muted-foreground opacity-0 group-hover:opacity-100 focus-visible:opacity-100 hover:text-foreground"
      :class="{ 'opacity-100 text-amber-500': favorite }"
      :aria-label="
        favorite
          ? t('library.unfavorite', { name: spec.name })
          : t('library.favorite', { name: spec.name })
      "
      :aria-pressed="favorite"
      @click.stop="emit('toggle-favorite', spec)"
    >
      <Star class="size-3.5" :fill="favorite ? 'currentColor' : 'none'" />
    </button>
  </li>
</template>
