<script setup lang="ts">
/** A group (Vue Flow parent node) with an editable title and a colour swatch. */
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { NodeProps } from '@vue-flow/core'
import { NodeResizer, type OnResizeStart } from '@vue-flow/node-resizer'
import { Ungroup } from '@lucide/vue'

import { OKABE_ITO } from '@/canvas/ports'
import { useWorkflowStore } from '@/stores/workflow'
import type { GroupNodeData } from './toFlow'

const props = defineProps<NodeProps<GroupNodeData>>()
defineOptions({ inheritAttrs: false })
const { t } = useI18n()
const workflow = useWorkflowStore()

const group = computed(() => workflow.groups[props.data.groupId])
const color = computed(() => group.value?.color ?? OKABE_ITO.skyBlue)
const SWATCHES = [
  OKABE_ITO.skyBlue,
  OKABE_ITO.orange,
  OKABE_ITO.green,
  OKABE_ITO.yellow,
  OKABE_ITO.purple,
  OKABE_ITO.grey,
]

const editing = ref(false)
const draft = ref('')
const input = ref<HTMLInputElement | null>(null)

function startRename(): void {
  draft.value = group.value?.title ?? ''
  editing.value = true
  void nextTick(() => input.value?.select())
}

function commitRename(): void {
  if (!editing.value) return
  editing.value = false
  if (draft.value !== group.value?.title)
    workflow.updateGroup(props.data.groupId, { title: draft.value })
}

function onResizeEnd(event: OnResizeStart): void {
  const { x, y, width, height } = event.params
  workflow.updateGroup(props.data.groupId, {
    pos: [Math.round(x), Math.round(y)],
    size: [Math.round(width), Math.round(height)],
  })
}
</script>

<template>
  <div
    v-if="group"
    class="ac-group h-full w-full rounded-xl border-2 border-dashed"
    :style="{ borderColor: color, background: `color-mix(in oklab, ${color} 10%, transparent)` }"
    :data-group-id="data.groupId"
    data-testid="group"
  >
    <NodeResizer
      :is-visible="selected"
      :min-width="120"
      :min-height="80"
      @resize-end="onResizeEnd"
    />
    <header
      class="flex h-8 items-center gap-2 rounded-t-[10px] px-3 text-xs font-semibold"
      :style="{ background: `color-mix(in oklab, ${color} 25%, transparent)` }"
      @dblclick.stop="startRename"
    >
      <input
        v-if="editing"
        ref="input"
        v-model="draft"
        class="nodrag h-6 min-w-0 flex-1 rounded border bg-background px-1 text-xs font-normal"
        :aria-label="t('group.rename')"
        @keydown.enter.prevent="commitRename"
        @keydown.escape.prevent="editing = false"
        @blur="commitRename"
      />
      <span v-else class="min-w-0 flex-1 truncate">{{ group.title || t('group.untitled') }}</span>
      <span v-if="selected" class="nodrag flex items-center gap-1">
        <button
          v-for="swatch in SWATCHES"
          :key="swatch"
          type="button"
          class="size-3.5 rounded-full border border-background"
          :style="{ background: swatch }"
          :aria-label="t('group.color', { color: swatch })"
          :aria-pressed="swatch === color"
          @click="workflow.updateGroup(data.groupId, { color: swatch })"
        />
        <button
          type="button"
          class="ml-1 inline-flex size-5 items-center justify-center rounded hover:bg-background/60"
          :title="t('group.ungroup')"
          @click="workflow.ungroup([data.groupId])"
        >
          <Ungroup class="size-3.5" />
        </button>
      </span>
    </header>
  </div>
</template>
