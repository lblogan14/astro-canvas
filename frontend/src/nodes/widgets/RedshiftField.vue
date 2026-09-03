<script setup lang="ts">
import NumberField from './NumberField.vue'

withDefaults(
  defineProps<{
    id: string
    modelValue: number | null
    min?: number
    max?: number
    step?: number
    precision?: number
    disabled?: boolean
    invalid?: boolean
  }>(),
  { min: -0.1, max: 20, step: 1e-4, precision: 4, disabled: false, invalid: false },
)

const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()
</script>

<template>
  <NumberField
    :id="id"
    kind="redshift"
    :model-value="modelValue"
    :min="min"
    :max="max"
    :step="step"
    :precision="precision"
    unit="z"
    :disabled="disabled"
    :invalid="invalid"
    @update:model-value="emit('update:modelValue', $event)"
  />
</template>
