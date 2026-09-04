<script setup lang="ts">
/** Path back out of nested subgraphs; shown only while a subgraph body is open. */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Boxes, ChevronRight } from '@lucide/vue'

import { useSelectionStore } from '@/stores/selection'
import { useWorkflowStore } from '@/stores/workflow'

const { t } = useI18n()
const workflow = useWorkflowStore()
const selection = useSelectionStore()

const crumbs = computed(() => workflow.breadcrumbs)

function go(depth: number): void {
  workflow.exitSubgraph(depth)
  selection.clear()
}
</script>

<template>
  <nav
    v-if="crumbs.length"
    class="absolute top-2 left-2 z-20 flex items-center gap-1 rounded-md border bg-popover/95 px-2 py-1 text-xs shadow-sm backdrop-blur"
    :aria-label="t('subgraph.breadcrumb')"
    data-testid="subgraph-breadcrumb"
    :data-depth="crumbs.length"
  >
    <Boxes class="size-3.5 text-muted-foreground" aria-hidden="true" />
    <button
      type="button"
      class="rounded px-1 py-0.5 hover:bg-muted"
      data-testid="breadcrumb-root"
      @click="go(0)"
    >
      {{ workflow.name || t('workflows.untitled') }}
    </button>
    <template v-for="(crumb, index) in crumbs" :key="crumb.nodeId">
      <ChevronRight class="size-3 text-muted-foreground" aria-hidden="true" />
      <button
        type="button"
        class="rounded px-1 py-0.5 hover:bg-muted"
        :class="index === crumbs.length - 1 ? 'font-medium' : ''"
        :data-testid="`breadcrumb-${index}`"
        @click="go(index + 1)"
      >
        {{ crumb.label }}
      </button>
    </template>
  </nav>
</template>
