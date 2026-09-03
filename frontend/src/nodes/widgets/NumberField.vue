<script setup lang="ts">
import { ref, watch } from 'vue'

import { INPUT_CLASS, UNIT_CLASS } from './classes'

const props = withDefaults(
  defineProps<{
    id: string
    modelValue: number | null
    min?: number
    max?: number
    step?: number
    unit?: string | null
    integer?: boolean
    precision?: number
    disabled?: boolean
    invalid?: boolean
    kind?: string
    ariaLabel?: string
  }>(),
  { unit: null, integer: false, disabled: false, invalid: false, kind: 'number' },
)

const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()

function format(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return ''
  if (props.precision !== undefined) {
    // Trim trailing zeros so 0.5000 renders as 0.5 while keeping the precision cap.
    return String(Number(value.toFixed(props.precision)))
  }
  return String(value)
}

const text = ref(format(props.modelValue))

watch(
  () => props.modelValue,
  (next) => {
    // Only resync when the displayed text does not already denote the same number,
    // so "1." or "1e" typed mid-way is not clobbered.
    const current = Number.parseFloat(text.value)
    if (next === null ? text.value.trim() !== '' : current !== next) text.value = format(next)
  },
)

function clamp(value: number): number {
  let out = value
  if (props.min !== undefined && out < props.min) out = props.min
  if (props.max !== undefined && out > props.max) out = props.max
  if (props.integer) out = Math.round(out)
  return out
}

function parse(raw: string): number | null | undefined {
  const trimmed = raw.trim()
  if (trimmed === '') return null
  const parsed = Number(trimmed)
  return Number.isFinite(parsed) ? parsed : undefined
}

function onInput(event: Event) {
  const target = event.target as HTMLInputElement
  text.value = target.value
  const parsed = parse(target.value)
  if (parsed === undefined) return
  emit('update:modelValue', parsed)
}

function onBlur() {
  const parsed = parse(text.value)
  if (parsed === undefined || parsed === null) return
  const clamped = clamp(parsed)
  if (clamped !== parsed) {
    text.value = format(clamped)
    emit('update:modelValue', clamped)
  } else if (props.precision !== undefined) {
    text.value = format(parsed)
  }
}
</script>

<template>
  <div class="flex min-w-0 items-center gap-1" :data-widget="kind">
    <input
      :id="id"
      type="number"
      inputmode="decimal"
      :class="INPUT_CLASS"
      :value="text"
      :min="min"
      :max="max"
      :step="step ?? (integer ? 1 : 'any')"
      :disabled="disabled"
      :aria-label="ariaLabel"
      :aria-invalid="invalid || undefined"
      @input="onInput"
      @blur="onBlur"
    />
    <span v-if="unit" :class="UNIT_CLASS" aria-hidden="true">{{ unit }}</span>
  </div>
</template>
