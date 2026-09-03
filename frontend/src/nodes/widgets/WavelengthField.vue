<script setup lang="ts">
import NumberField from './NumberField.vue'

withDefaults(
  defineProps<{
    id: string
    modelValue: number | null
    min?: number
    max?: number
    step?: number
    unit?: string | null
    precision?: number
    disabled?: boolean
    invalid?: boolean
  }>(),
  { min: 0, step: 0.01, unit: 'Å', disabled: false, invalid: false },
)

const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()

/** The backend spells the unit out (`Angstrom`); show the symbol. */
function unitSymbol(unit: string | null): string | null {
  if (unit === null) return null
  return /^(angstrom|angstroms|aa)$/i.test(unit) ? 'Å' : unit
}
</script>

<template>
  <NumberField
    :id="id"
    kind="wavelength"
    :model-value="modelValue"
    :min="min"
    :max="max"
    :step="step"
    :precision="precision"
    :unit="unitSymbol(unit)"
    :disabled="disabled"
    :invalid="invalid"
    @update:model-value="emit('update:modelValue', $event)"
  />
</template>
