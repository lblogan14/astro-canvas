<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import NumberField from './NumberField.vue'

const props = withDefaults(
  defineProps<{
    id: string
    modelValue: number | null
    min: number
    max: number
    step?: number
    unit?: string | null
    integer?: boolean
    precision?: number
    disabled?: boolean
    invalid?: boolean
    label?: string
  }>(),
  { unit: null, integer: false, disabled: false, invalid: false, label: '' },
)

const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()

const { t } = useI18n()

const sliderStep = computed(() => props.step ?? (props.integer ? 1 : (props.max - props.min) / 100))
const sliderValue = computed(() => props.modelValue ?? props.min)

function onSlide(event: Event) {
  const parsed = Number((event.target as HTMLInputElement).value)
  if (Number.isFinite(parsed)) emit('update:modelValue', parsed)
}
</script>

<template>
  <div class="flex min-w-0 items-center gap-2" data-widget="slider">
    <input
      type="range"
      class="h-6 min-w-0 flex-1 cursor-pointer accent-primary disabled:cursor-not-allowed disabled:opacity-50"
      :aria-label="t('autoform.slider_for', { label: label || id })"
      :aria-invalid="invalid || undefined"
      :value="sliderValue"
      :min="min"
      :max="max"
      :step="sliderStep"
      :disabled="disabled"
      @input="onSlide"
    />
    <div class="w-20 shrink-0">
      <NumberField
        :id="id"
        :model-value="modelValue"
        :min="min"
        :max="max"
        :step="step"
        :unit="unit"
        :integer="integer"
        :precision="precision"
        :disabled="disabled"
        :invalid="invalid"
        @update:model-value="emit('update:modelValue', $event)"
      />
    </div>
  </div>
</template>
