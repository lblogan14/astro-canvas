<script setup lang="ts">
import { computed } from 'vue'

import { typeLabel } from '@/canvas/ports'
import type { PreviewProps } from '@/previews/registry'

const props = defineProps<PreviewProps>()

function formatScalar(value: unknown): string {
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : value.toPrecision(6).replace(/\.?0+$/, '')
  }
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'string') return value
  if (value === null || value === undefined) return '—'
  try {
    return JSON.stringify(value).slice(0, 80)
  } catch {
    return String(value)
  }
}

const text = computed(() => {
  const data = props.summary['data'] as Record<string, unknown> | undefined
  if (data && 'value' in data) return formatScalar(data['value'])
  if (typeof props.summary['python_type'] === 'string') return `<${props.summary['python_type']}>`
  if (props.port === '$preview') return JSON.stringify(props.summary).slice(0, 80)
  return typeLabel(props.typeId)
})
</script>

<template>
  <span
    class="inline-flex max-w-full items-center gap-1 rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]"
    data-preview="value-chip"
    :data-summary-port="port"
  >
    <span class="text-muted-foreground">{{ port }}</span>
    <span class="truncate" :title="text">{{ text }}</span>
  </span>
</template>
