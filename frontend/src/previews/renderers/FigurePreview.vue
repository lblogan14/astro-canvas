<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { PreviewProps } from '@/previews/registry'

const props = defineProps<PreviewProps>()
const { t } = useI18n()

const kind = computed(() =>
  typeof props.summary['kind'] === 'string' ? props.summary['kind'] : 'figure',
)
const png = computed(() =>
  typeof props.summary['png_b64'] === 'string'
    ? `data:image/png;base64,${props.summary['png_b64']}`
    : null,
)
const traces = computed(() => {
  const fig = props.summary['plotly'] as { data?: unknown[] } | undefined
  return Array.isArray(fig?.data) ? fig.data.length : null
})
const size = computed(() => (typeof props.summary['size'] === 'number' ? props.summary['size'] : 0))
</script>

<template>
  <div data-preview="figure" class="text-[11px]">
    <img v-if="png" :src="png" alt="" class="max-h-32 w-full rounded object-contain" />
    <div
      v-else
      class="flex h-16 items-center justify-center rounded border border-dashed text-muted-foreground"
    >
      {{ t('preview.figure', { kind })
      }}<span v-if="traces !== null">&nbsp;· {{ traces }} traces</span>
    </div>
    <p class="mt-0.5 text-right font-mono text-[10px] text-muted-foreground">
      {{ (size / 1024).toFixed(1) }} KB
    </p>
  </div>
</template>
