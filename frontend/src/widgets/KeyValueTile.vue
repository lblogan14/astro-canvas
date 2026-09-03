<script setup lang="ts">
/** A compact grid of key/value pairs (measurements, chips, file info). */
import { computed } from 'vue'

import { formatKvValue } from './formatValue'

const props = withDefaults(
  defineProps<{
    data: Record<string, unknown>
    units?: Record<string, string>
    /** Keys to show first (others follow alphabetically); `null` = insertion order. */
    order?: string[] | null
    /** Hide nested objects/arrays (they are summarised as their type). */
    compact?: boolean
    title?: string
  }>(),
  { units: () => ({}), order: null, compact: false, title: '' },
)

const entries = computed(() => {
  const keys = Object.keys(props.data)
  const ordered = props.order
    ? [
        ...props.order.filter((k) => keys.includes(k)),
        ...keys.filter((k) => !props.order?.includes(k)).sort(),
      ]
    : keys
  return ordered
    .filter((key) => !key.startsWith('$') && key !== 'type')
    .map((key) => ({ key, value: formatKvValue(props.data[key]), unit: props.units[key] ?? '' }))
})
</script>

<template>
  <div class="text-[11px]" data-widget="kv-tile">
    <p v-if="title" class="mb-1 font-medium">{{ title }}</p>
    <dl class="grid grid-cols-[auto_1fr] gap-x-2 gap-y-px">
      <template v-for="entry in entries" :key="entry.key">
        <dt class="truncate text-muted-foreground" :title="entry.key">{{ entry.key }}</dt>
        <dd class="truncate font-mono" :title="entry.value" :data-key="entry.key">
          {{ entry.value
          }}<span v-if="entry.unit" class="ml-1 text-muted-foreground">{{ entry.unit }}</span>
        </dd>
      </template>
    </dl>
  </div>
</template>
