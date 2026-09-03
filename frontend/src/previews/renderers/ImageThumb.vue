<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { DEFAULT_RENDER, decodeTile, isTileSummary } from '@/lib/tile'
import type { PreviewProps } from '@/previews/registry'
import { ImageView } from '@/widgets'

const props = defineProps<PreviewProps>()
const { t } = useI18n()

const tile = computed(() =>
  isTileSummary(props.summary['tile']) ? decodeTile(props.summary['tile']) : null,
)
const shape = computed(() => {
  const s = props.summary['shape']
  return Array.isArray(s) && s.length === 2 ? { ny: Number(s[0]), nx: Number(s[1]) } : null
})
const caption = computed(() => {
  const object = props.summary['object']
  return typeof object === 'string' && object ? object : ''
})
</script>

<template>
  <div data-preview="image-thumb">
    <ImageView
      :tile="tile"
      :controls="false"
      :interactive="false"
      :options="DEFAULT_RENDER"
      :height="110"
      class="overflow-hidden rounded"
    />
    <p class="mt-0.5 flex justify-between text-[10px] text-muted-foreground">
      <span class="truncate">{{ caption }}</span>
      <span v-if="shape" class="font-mono">{{ t('preview.shape', shape) }}</span>
    </p>
  </div>
</template>
