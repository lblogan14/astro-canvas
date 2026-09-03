<script setup lang="ts">
import { computed } from 'vue'

import { TEXTAREA_CLASS } from './classes'

const props = withDefaults(
  defineProps<{
    id: string
    modelValue: string
    language?: string
    placeholder?: string
    disabled?: boolean
    invalid?: boolean
    kind?: string
    minRows?: number
    maxRows?: number
  }>(),
  {
    language: 'plain',
    placeholder: '',
    disabled: false,
    invalid: false,
    kind: 'code',
    minRows: 2,
    maxRows: 8,
  },
)

const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()

const rows = computed(() => {
  const lines = props.modelValue.split('\n').length
  return Math.min(props.maxRows, Math.max(props.minRows, lines))
})

function onInput(event: Event) {
  emit('update:modelValue', (event.target as HTMLTextAreaElement).value)
}
</script>

<template>
  <div class="flex min-w-0" :data-widget="kind">
    <textarea
      :id="id"
      :class="TEXTAREA_CLASS"
      :value="modelValue"
      :rows="rows"
      :placeholder="placeholder || undefined"
      :disabled="disabled"
      :aria-invalid="invalid || undefined"
      :data-language="language"
      autocomplete="off"
      spellcheck="false"
      wrap="off"
      @input="onInput"
    />
  </div>
</template>
