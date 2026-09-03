<script setup lang="ts">
import { computed } from 'vue'

import { INPUT_CLASS } from './classes'

export interface SelectOption {
  value: unknown
  label: string
}

const props = withDefaults(
  defineProps<{
    id: string
    modelValue: unknown
    options: SelectOption[]
    disabled?: boolean
    invalid?: boolean
  }>(),
  { disabled: false, invalid: false },
)

const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()

/** Option values may be non-strings; the `<select>` works on the option index instead. */
const selectedIndex = computed(() => {
  const index = props.options.findIndex(
    (option) =>
      option.value === props.modelValue ||
      JSON.stringify(option.value) === JSON.stringify(props.modelValue),
  )
  return index === -1 ? '' : String(index)
})

function onChange(event: Event) {
  const raw = (event.target as HTMLSelectElement).value
  if (raw === '') return
  const option = props.options[Number(raw)]
  if (option) emit('update:modelValue', option.value)
}
</script>

<template>
  <div class="flex min-w-0 items-center" data-widget="select">
    <select
      :id="id"
      :class="INPUT_CLASS"
      :value="selectedIndex"
      :disabled="disabled"
      :aria-invalid="invalid || undefined"
      @change="onChange"
    >
      <option v-if="selectedIndex === ''" value="" disabled hidden></option>
      <option v-for="(option, index) in options" :key="index" :value="String(index)">
        {{ option.label }}
      </option>
    </select>
  </div>
</template>
