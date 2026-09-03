<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { PreviewProps } from '@/previews/registry'
import { UPlotLine, seriesFromSummary } from '@/widgets'

const props = defineProps<PreviewProps>()
const { t } = useI18n()

/** Stacked collections show their first item; single spectra show themselves. */
const series = computed(() => {
  const items = props.summary['items']
  const first = Array.isArray(items) && items.length ? (items[0] as Record<string, unknown>) : null
  return seriesFromSummary(first ?? props.summary)
})
const count = computed(() =>
  typeof props.summary['count'] === 'number' ? props.summary['count'] : null,
)
</script>

<template>
  <div data-preview="spectrum-thumb">
    <UPlotLine :series="series" :height="72" :show-error="true" :show-continuum="true" />
    <p class="mt-0.5 flex justify-between text-[10px] text-muted-foreground">
      <span v-if="series">{{ t('preview.points', { n: series.n }) }}</span>
      <span v-if="count !== null">×{{ count }}</span>
      <span v-if="series?.range" class="font-mono">
        {{ series.range[0].toFixed(0) }}–{{ series.range[1].toFixed(0) }} {{ series.waveUnit }}
      </span>
    </p>
  </div>
</template>
