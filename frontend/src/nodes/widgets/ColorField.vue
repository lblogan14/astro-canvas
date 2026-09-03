<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { INPUT_CLASS } from './classes'

const props = withDefaults(
  defineProps<{
    id: string
    modelValue: string
    disabled?: boolean
    invalid?: boolean
    label?: string
  }>(),
  { disabled: false, invalid: false, label: '' },
)

const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()

const { t } = useI18n()

const HEX = /^#[0-9a-fA-F]{6}$/
const SHORT_HEX = /^#[0-9a-fA-F]{3}$/

function normalize(raw: string): string | null {
  const value = raw.trim()
  if (HEX.test(value)) return value.toLowerCase()
  if (SHORT_HEX.test(value)) {
    const [, r, g, b] = value
    return `#${r}${r}${g}${g}${b}${b}`.toLowerCase()
  }
  return null
}

const text = ref(props.modelValue)
watch(
  () => props.modelValue,
  (next) => {
    if (normalize(text.value) !== normalize(next)) text.value = next
  },
)

/** The swatch input only accepts full six-digit hex; anything else falls back to black. */
function swatch(value: string): string {
  return normalize(value) ?? '#000000'
}

function onPick(event: Event) {
  const value = (event.target as HTMLInputElement).value
  text.value = value
  emit('update:modelValue', value)
}

function onText(event: Event) {
  const raw = (event.target as HTMLInputElement).value
  text.value = raw
  const normalized = normalize(raw)
  if (normalized) emit('update:modelValue', normalized)
}
</script>

<template>
  <div class="flex min-w-0 items-center gap-1" data-widget="color">
    <input
      :id="id"
      type="color"
      class="h-6 w-8 shrink-0 cursor-pointer rounded-md border border-input bg-input/30 p-0.5 disabled:cursor-not-allowed disabled:opacity-50"
      :value="swatch(modelValue)"
      :disabled="disabled"
      :aria-invalid="invalid || undefined"
      @input="onPick"
    />
    <input
      :id="`${id}-hex`"
      type="text"
      :class="[INPUT_CLASS, 'font-mono']"
      :value="text"
      maxlength="7"
      spellcheck="false"
      autocomplete="off"
      :disabled="disabled"
      :aria-invalid="invalid || undefined"
      :aria-label="t('autoform.color_hex', { label: label || id })"
      @input="onText"
    />
  </div>
</template>
