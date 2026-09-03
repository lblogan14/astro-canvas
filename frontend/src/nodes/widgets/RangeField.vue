<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import NumberField from './NumberField.vue'
import { UNIT_CLASS } from './classes'

const props = withDefaults(
  defineProps<{
    id: string
    modelValue: [number, number] | null
    unit?: string | null
    min?: number
    max?: number
    step?: number
    integer?: boolean
    disabled?: boolean
    invalid?: boolean
    label?: string
  }>(),
  { unit: null, integer: false, disabled: false, invalid: false, label: '' },
)

const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()

const { t } = useI18n()

const lo = computed(() => props.modelValue?.[0] ?? null)
const hi = computed(() => props.modelValue?.[1] ?? null)

function update(index: 0 | 1, value: unknown) {
  if (typeof value !== 'number') return
  const next: [number, number] = [lo.value ?? props.min ?? 0, hi.value ?? props.max ?? 0]
  next[index] = value
  emit('update:modelValue', next)
}
</script>

<template>
  <div class="flex min-w-0 items-center gap-1" data-widget="range">
    <NumberField
      :id="id"
      kind="range-lo"
      :model-value="lo"
      :min="min"
      :max="max"
      :step="step"
      :integer="integer"
      :disabled="disabled"
      :invalid="invalid"
      :aria-label="t('autoform.range_low', { label: label || id })"
      @update:model-value="update(0, $event)"
    />
    <span class="shrink-0 text-xs text-muted-foreground" aria-hidden="true">–</span>
    <NumberField
      :id="`${id}-hi`"
      kind="range-hi"
      :model-value="hi"
      :min="min"
      :max="max"
      :step="step"
      :integer="integer"
      :disabled="disabled"
      :invalid="invalid"
      :aria-label="t('autoform.range_high', { label: label || id })"
      @update:model-value="update(1, $event)"
    />
    <span v-if="unit" :class="UNIT_CLASS" aria-hidden="true">{{ unit }}</span>
  </div>
</template>
