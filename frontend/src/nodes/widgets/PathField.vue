<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import TextField from './TextField.vue'
import { ICON_BUTTON_CLASS } from './classes'

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
    <!-- Placeholder for the file picker that arrives with the data-source phase. -->
    <button
      type="button"
      :class="ICON_BUTTON_CLASS"
      disabled
      :aria-label="t('autoform.browse')"
      :title="t('autoform.browse_soon')"
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
    </button>
  </div>
</template>
