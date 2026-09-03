<script setup lang="ts">
/** Workspace-relative path with a picker popover over the workspace file tree. */
import { defineAsyncComponent, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { PopoverContent, PopoverPortal, PopoverRoot, PopoverTrigger } from 'reka-ui'

import type { WorkspaceEntry } from '@/api/types'

import TextField from './TextField.vue'
import { ICON_BUTTON_CLASS } from './classes'

// Lazy: the tree pulls in the workspace store; plain forms should not pay for it.
const WorkspaceTree = defineAsyncComponent(() => import('@/app/workspace/WorkspaceTree.vue'))

withDefaults(
  defineProps<{
    id: string
    modelValue: string
    placeholder?: string
    disabled?: boolean
    invalid?: boolean
  }>(),
  { placeholder: '', disabled: false, invalid: false },
)

const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()

const { t } = useI18n()
const open = ref(false)
const filter = ref('')

function pick(entry: WorkspaceEntry): void {
  emit('update:modelValue', entry.path)
  open.value = false
}
</script>

<template>
  <div class="flex min-w-0 items-center gap-1" data-widget="path">
    <TextField
      :id="id"
      class="min-w-0 flex-1"
      kind="path-text"
      :model-value="modelValue"
      :placeholder="placeholder || t('autoform.path_placeholder')"
      :disabled="disabled"
      :invalid="invalid"
      @update:model-value="emit('update:modelValue', $event)"
    />
    <PopoverRoot v-model:open="open">
      <PopoverTrigger
        type="button"
        :class="ICON_BUTTON_CLASS"
        :disabled="disabled"
        :aria-label="t('autoform.browse')"
        :title="t('workspace.browse')"
        data-testid="path-browse"
      >
        <svg
          aria-hidden="true"
          viewBox="0 0 16 16"
          class="h-3.5 w-3.5"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linejoin="round"
        >
          <path d="M1.5 4.5v8h13v-6.5h-6l-1.5-1.5h-5.5z" />
        </svg>
      </PopoverTrigger>
      <PopoverPortal>
        <PopoverContent
          side="bottom"
          align="end"
          :side-offset="4"
          class="nodrag nowheel z-50 flex max-h-80 w-80 flex-col rounded-md border bg-popover p-2 text-xs text-popover-foreground shadow-md"
          data-testid="path-picker"
        >
          <p class="mb-1 font-medium">{{ t('workspace.picker_title') }}</p>
          <input
            v-model="filter"
            type="search"
            class="mb-1 h-6 w-full rounded border bg-background px-1.5"
            :placeholder="t('library.search')"
          />
          <div class="min-h-0 flex-1 overflow-auto">
            <WorkspaceTree path="" selectable :filter="filter" @pick="pick" />
          </div>
          <p class="mt-1 text-[10px] text-muted-foreground">{{ t('workspace.picker_hint') }}</p>
        </PopoverContent>
      </PopoverPortal>
    </PopoverRoot>
  </div>
</template>
