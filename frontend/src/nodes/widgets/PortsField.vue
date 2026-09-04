<script setup lang="ts">
/**
 * Declares the ports of a node that carries its own (the code node): a name and a port type per
 * row. The list *is* the node's shape — adding a row grows a handle on the canvas — so the type
 * choices come from the registry rather than being free text.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Plus, X } from '@lucide/vue'

import { isValidPortName } from '@/nodes/dynamicPorts'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { ICON_BUTTON_CLASS, INPUT_CLASS } from './classes'

const props = withDefaults(
  defineProps<{
    id: string
    modelValue: unknown[]
    disabled?: boolean
    invalid?: boolean
    label?: string
  }>(),
  { disabled: false, invalid: false, label: '' },
)

const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()

const { t } = useI18n()
const schema = useNodesSchemaStore()

interface Row {
  name: string
  type: string
}

const rows = computed<Row[]>(() =>
  props.modelValue.map((item) => {
    const record = (item ?? {}) as Record<string, unknown>
    return {
      name: typeof record['name'] === 'string' ? record['name'] : '',
      type: typeof record['type'] === 'string' ? record['type'] : 'astro.Any',
    }
  }),
)

/** Port types, most useful first: `astro.Any` accepts anything, so it heads the list. */
const options = computed(() => {
  const ids = schema.types.map((type) => type.id).sort((a, b) => a.localeCompare(b))
  return ['astro.Any', ...ids.filter((id) => id !== 'astro.Any')]
})

function commit(next: Row[]): void {
  emit(
    'update:modelValue',
    next.map((row) => ({ name: row.name, type: row.type })),
  )
}

function setName(index: number, value: string): void {
  const next = rows.value.map((row, i) => (i === index ? { ...row, name: value } : row))
  commit(next)
}

function setType(index: number, value: string): void {
  const next = rows.value.map((row, i) => (i === index ? { ...row, type: value } : row))
  commit(next)
}

function add(): void {
  commit([...rows.value, { name: '', type: 'astro.Any' }])
}

function remove(index: number): void {
  commit(rows.value.filter((_, i) => i !== index))
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-1" data-widget="ports">
    <ul class="m-0 flex list-none flex-col gap-1 p-0">
      <li v-for="(row, index) in rows" :key="index" class="flex items-center gap-1">
        <input
          :id="index === 0 ? id : `${id}-${index}`"
          :class="INPUT_CLASS"
          :value="row.name"
          :disabled="disabled"
          :aria-invalid="row.name !== '' && !isValidPortName(row.name)"
          :aria-label="t('widgets.ports.name')"
          :placeholder="t('widgets.ports.name')"
          :data-testid="`port-name-${index}`"
          @input="setName(index, ($event.target as HTMLInputElement).value)"
        />
        <select
          :class="INPUT_CLASS"
          :value="row.type"
          :disabled="disabled"
          :aria-label="t('widgets.ports.type')"
          :data-testid="`port-type-${index}`"
          @change="setType(index, ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="option in options" :key="option" :value="option">{{ option }}</option>
        </select>
        <button
          type="button"
          :class="ICON_BUTTON_CLASS"
          :disabled="disabled"
          :title="t('widgets.ports.remove')"
          :aria-label="t('widgets.ports.remove')"
          :data-testid="`port-remove-${index}`"
          @click="remove(index)"
        >
          <X class="size-3" />
        </button>
      </li>
    </ul>
    <button
      type="button"
      class="self-start text-[11px] underline"
      :disabled="disabled"
      :data-testid="`${id}-add`"
      @click="add"
    >
      <Plus class="inline size-3" /> {{ t('widgets.ports.add') }}
    </button>
  </div>
</template>
