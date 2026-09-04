<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { PreviewProps } from '@/previews/registry'
import { DataTable, type TableHead } from '@/widgets'

const props = withDefaults(defineProps<PreviewProps & { selectedRows?: number[] }>(), {
  selectedRows: () => [],
})
const emit = defineEmits<{ 'select-rows': [rows: number[]] }>()
const { t } = useI18n()

/** Rows highlighted by a linked selection (dashboard mode); empty everywhere else. */
const selected = computed(() => new Set(props.selectedRows))

const head = computed<TableHead | null>(() => {
  const columns = props.summary['columns']
  const rows = props.summary['head']
  if (!Array.isArray(columns) || typeof rows !== 'object' || rows === null) return null
  const limited: Record<string, unknown[]> = {}
  for (const name of columns as string[]) {
    const values = (rows as Record<string, unknown>)[name]
    limited[name] = Array.isArray(values) ? values.slice(0, 5) : []
  }
  return {
    columns: columns as string[],
    rows: limited,
    units: (props.summary['units'] as Record<string, string> | undefined) ?? {},
    nRows: typeof props.summary['n_rows'] === 'number' ? props.summary['n_rows'] : undefined,
  }
})
</script>

<template>
  <div data-preview="table-head">
    <div class="max-h-32 overflow-hidden rounded border">
      <DataTable
        :head="head"
        :units="head?.units ?? {}"
        :page-size="5"
        :selected-rows="selectedRows"
        compact
        @select-row="(row: number) => emit('select-rows', selected.has(row) ? [] : [row])"
      />
    </div>
    <p class="mt-0.5 flex justify-between text-[10px] text-muted-foreground">
      <span v-if="head?.nRows !== undefined">{{ t('preview.rows', { n: head.nRows }) }}</span>
      <span v-if="head">{{ t('preview.columns', { n: head.columns.length }) }}</span>
    </p>
  </div>
</template>
