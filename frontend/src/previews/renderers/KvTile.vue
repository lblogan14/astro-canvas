<script setup lang="ts">
import { computed } from 'vue'

import type { PreviewProps } from '@/previews/registry'
import { KeyValueTile } from '@/widgets'

const props = defineProps<PreviewProps>()

/** Scalar/JSON summaries carry `{type, data: {...}}`; other types are flat. */
const data = computed<Record<string, unknown>>(() => {
  const inner = props.summary['data']
  if (typeof inner === 'object' && inner !== null && !Array.isArray(inner)) {
    return inner as Record<string, unknown>
  }
  return props.summary
})

const ORDER = [
  'W',
  'W_e',
  'logN',
  'logN_e',
  'N',
  'N_e',
  'vel_centroid',
  'vel_disp',
  'SNR',
  'z',
  'z_err',
  'name',
  'wrest',
  'fval',
]
</script>

<template>
  <KeyValueTile :data="data" :order="ORDER" compact data-preview="kv-tile" />
</template>
