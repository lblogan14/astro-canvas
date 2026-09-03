<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { DEFAULT_RENDER, decodeTile, isTileSummary } from '@/lib/tile'
import type { PreviewProps } from '@/previews/registry'
import { ImageView, UPlotLine, type SpectrumSeries } from '@/widgets'

const props = defineProps<PreviewProps>()
const { t } = useI18n()

const tile = computed(() =>
  isTileSummary(props.summary['tile']) ? decodeTile(props.summary['tile']) : null,
)
const shape = computed(() => {
  const s = props.summary['shape']
  return Array.isArray(s) && s.length === 3
    ? { nz: Number(s[0]), ny: Number(s[1]), nx: Number(s[2]) }
    : null
})
const spectrum = computed<SpectrumSeries | null>(() => {
  const spec = props.summary['spectrum'] as { wave?: unknown; flux?: unknown } | undefined
  if (!spec || !Array.isArray(spec.wave) || !Array.isArray(spec.flux)) return null
  const wave = spec.wave as number[]
  return {
    wave,
    flux: (spec.flux as (number | null)[]).map((v) => (v === null ? Number.NaN : v)),
    waveUnit:
      typeof props.summary['wave_unit'] === 'string' ? props.summary['wave_unit'] : 'Angstrom',
    fluxUnit: '',
    frame: 'observed',
    z: null,
    v0Wrest: null,
    n: wave.length,
    range: wave.length ? [wave[0] ?? 0, wave[wave.length - 1] ?? 0] : null,
  }
})
const instrument = computed(() =>
  typeof props.summary['instrument'] === 'string' ? props.summary['instrument'] : '',
)
</script>

<template>
  <div data-preview="cube-thumb">
    <div class="flex gap-1">
      <ImageView
        :tile="tile"
        :controls="false"
        :interactive="false"
        :options="DEFAULT_RENDER"
        :height="96"
        class="w-1/2 overflow-hidden rounded"
      />
      <div class="min-w-0 flex-1">
        <UPlotLine :series="spectrum" :height="96" :show-error="false" :show-continuum="false" />
      </div>
    </div>
    <p class="mt-0.5 flex justify-between text-[10px] text-muted-foreground">
      <span>{{ instrument || t('preview.white_light') }}</span>
      <span v-if="shape" class="font-mono">{{ t('preview.cube_shape', shape) }}</span>
    </p>
  </div>
</template>
