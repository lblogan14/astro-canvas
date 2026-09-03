<script setup lang="ts">
import { INPUT_CLASS } from './classes'

withDefaults(
  defineProps<{
    id: string
    modelValue: string
    placeholder?: string
    maxlength?: number
    disabled?: boolean
    invalid?: boolean
    kind?: string
  }>(),
  { placeholder: '', disabled: false, invalid: false, kind: 'text' },
)

const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()

function onInput(event: Event) {
  emit('update:modelValue', (event.target as HTMLInputElement).value)
}
</script>

<template>
  <div class="flex min-w-0 items-center" :data-widget="kind">
    <input
      :id="id"
      type="text"
      :class="INPUT_CLASS"
      :value="modelValue"
      :placeholder="placeholder || undefined"
      :maxlength="maxlength"
      :disabled="disabled"
      :aria-invalid="invalid || undefined"
      autocomplete="off"
      spellcheck="false"
      @input="onInput"
    />
  </div>
</template>
