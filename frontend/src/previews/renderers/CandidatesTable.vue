<script setup lang="ts">
/**
 * `candidates-table` preview for `rbcodes.ZCandidates` (the output of `rbcodes.zfind.rank`):
 * the first rows of the ranked candidate table with the accepted one highlighted.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { formatScore, formatZ } from '@/editors/zAccept'
import type { PreviewProps } from '@/previews/registry'

const props = withDefaults(defineProps<PreviewProps & { selectedRows?: number[] }>(), {
  selectedRows: () => [],
})
const emit = defineEmits<{ 'select-rows': [rows: number[]] }>()
const { t } = useI18n()

/** Rows highlighted by a linked selection (dashboard mode); empty everywhere else. */
const selected = computed(() => new Set(props.selectedRows))

const MAX_ROWS = 6

interface Row {
  index: number
  source: number
  z: number
  zErr: number | null
  score: number
  method: string
}

const rows = computed<Row[]>(() => {
  const raw = props.summary['rows']
  if (!Array.isArray(raw)) return []
  const out: Row[] = []
  for (const item of raw) {
    if (typeof item !== 'object' || item === null) continue
    const r = item as Record<string, unknown>
    if (typeof r['z'] !== 'number') continue
    out.push({
      index: typeof r['index'] === 'number' ? r['index'] : out.length,
      source: typeof r['source'] === 'number' ? r['source'] : 0,
      z: r['z'],
      zErr: typeof r['z_err'] === 'number' ? r['z_err'] : null,
      score: typeof r['score'] === 'number' ? r['score'] : Number.NaN,
      method: typeof r['method'] === 'string' ? r['method'] : '',
    })
  }
  return out
})
const accepted = computed(() =>
  typeof props.summary['accepted'] === 'number' ? props.summary['accepted'] : null,
)
const total = computed(() =>
  typeof props.summary['n'] === 'number' ? props.summary['n'] : rows.value.length,
)
const shown = computed(() => rows.value.slice(0, MAX_ROWS))
</script>

<template>
  <div data-preview="candidates-table" :data-accepted="accepted ?? undefined">
    <table v-if="shown.length" class="w-full text-[10px] leading-4">
      <tbody>
        <tr
          v-for="(row, position) in shown"
          :key="row.index"
          class="cursor-pointer"
          :class="[
            row.index === accepted ? 'font-semibold text-foreground' : 'text-muted-foreground',
            selected.has(position) ? 'bg-primary/15 text-foreground' : '',
          ]"
          :data-index="row.index"
          :data-row="position"
          :data-linked="selected.has(position) ? 'true' : undefined"
          :aria-selected="selected.has(position) || row.index === accepted"
          @click="emit('select-rows', selected.has(position) ? [] : [position])"
        >
          <td class="pr-1 font-mono">{{ row.index === accepted ? '●' : '' }}{{ row.index }}</td>
          <td class="pr-1 font-mono">{{ formatZ(row.z, row.zErr) }}</td>
          <td class="pr-1 text-right font-mono">{{ formatScore(row.score) }}</td>
          <td class="truncate" :title="row.method">{{ row.method }}</td>
        </tr>
      </tbody>
    </table>
    <p v-else class="text-[10px] text-muted-foreground">{{ t('preview.no_output') }}</p>
    <p class="mt-0.5 text-[10px] text-muted-foreground">
      {{ t('preview.zfind.candidates', { n: total }) }}
      <span v-if="accepted !== null">
        · {{ t('preview.zfind.accepted', { index: accepted }) }}</span
      >
    </p>
  </div>
</template>
