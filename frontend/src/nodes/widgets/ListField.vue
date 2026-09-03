<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import { ICON_BUTTON_CLASS, INPUT_CLASS } from './classes'

const props = withDefaults(
  defineProps<{
    id: string
    modelValue: unknown[]
    itemType: 'number' | 'string'
    disabled?: boolean
    invalid?: boolean
    label?: string
  }>(),
  { disabled: false, invalid: false, label: '' },
)

const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()

const { t } = useI18n()

function display(item: unknown): string {
  if (item === null || item === undefined) return ''
  return typeof item === 'string' ? item : String(item)
}

function onItemInput(index: number, event: Event) {
  const raw = (event.target as HTMLInputElement).value
  let next: unknown = raw
  if (props.itemType === 'number') {
    const parsed = Number(raw.trim())
    if (raw.trim() === '' || !Number.isFinite(parsed)) return
    next = parsed
  }
  const items = [...props.modelValue]
  items[index] = next
  emit('update:modelValue', items)
}

function add() {
  emit('update:modelValue', [...props.modelValue, props.itemType === 'number' ? 0 : ''])
}

function remove(index: number) {
  emit(
    'update:modelValue',
    props.modelValue.filter((_, i) => i !== index),
  )
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-1" data-widget="list">
    <ul class="m-0 flex list-none flex-col gap-1 p-0">
      <li v-for="(item, index) in modelValue" :key="index" class="flex items-center gap-1">
        <input
          :id="index === 0 ? id : `${id}-${index}`"
          :type="itemType === 'number' ? 'number' : 'text'"
          :step="itemType === 'number' ? 'any' : undefined"
          :class="INPUT_CLASS"
          :value="display(item)"
          :disabled="disabled"
          :aria-invalid="invalid || undefined"
          :aria-label="t('autoform.list_item', { label: label || id, index: index + 1 })"
          @input="onItemInput(index, $event)"
        />
        <button
          type="button"
          :class="ICON_BUTTON_CLASS"
          :disabled="disabled"
          :aria-label="t('autoform.list_remove', { index: index + 1 })"
          @click="remove(index)"
        >
          <span aria-hidden="true">−</span>
        </button>
      </li>
    </ul>
    <button
      :id="modelValue.length === 0 ? id : undefined"
      type="button"
      :class="[ICON_BUTTON_CLASS, 'w-auto self-start px-2']"
      :disabled="disabled"
      :aria-label="t('autoform.list_add', { label: label || id })"
      @click="add"
    >
      <span aria-hidden="true">+</span>
      <span class="ml-1">{{ t('autoform.add') }}</span>
    </button>
  </div>
</template>
