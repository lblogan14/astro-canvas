<script setup lang="ts">
/**
 * `moment-thumbs`: the three moment maps (and the SNR map) of `rbcodes.MomentMaps` side by side,
 * painted with one shared colour map so the row reads as one measurement. Each map keeps its own
 * scaling — an integrated flux, a velocity in km/s and a dispersion do not share a range — and the
 * limits are printed under it.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { type ColormapName } from '@/lib/colormaps'
import {
  DEFAULT_RENDER,
  type RenderOptions,
  decodeTile,
  isTileSummary,
  limitsFor,
} from '@/lib/tile'
import type { PreviewProps } from '@/previews/registry'
import { ImageView, formatCompact } from '@/widgets'

const props = defineProps<PreviewProps>()
const { t } = useI18n()

/** Velocity maps are diverging; the flux and SNR maps are sequential. */
const COLORMAPS: Record<string, ColormapName> = {
  m0: 'viridis',
  m1: 'rdbu',
  m2: 'magma',
  snr: 'gray',
}

interface MapEntry {
  key: string
  unit: string
  tile: ReturnType<typeof decodeTile>
  options: RenderOptions
  limits: [number, number]
}

const maps = computed<MapEntry[]>(() => {
  const raw = props.summary['maps']
  if (!Array.isArray(raw)) return []
  const out: MapEntry[] = []
  for (const item of raw) {
    if (typeof item !== 'object' || item === null) continue
    const record = item as Record<string, unknown>
    if (!isTileSummary(record['tile'])) continue
    const key = typeof record['key'] === 'string' ? record['key'] : 'm0'
    const tile = decodeTile(record['tile'])
    const options: RenderOptions = {
      ...DEFAULT_RENDER,
      colormap: COLORMAPS[key] ?? DEFAULT_RENDER.colormap,
    }
    out.push({
      key,
      unit: typeof record['unit'] === 'string' ? record['unit'] : '',
      tile,
      options,
      limits: limitsFor(tile, options.scale),
    })
  }
  return out
})

const shape = computed(() => {
  const value = props.summary['shape']
  return Array.isArray(value) && value.length === 2
    ? { ny: Number(value[0]), nx: Number(value[1]) }
    : null
})

const window = computed(() => {
  const value = props.summary['window']
  return Array.isArray(value) && value.length === 2 && typeof value[0] === 'number'
    ? { lo: format(value[0] as number), hi: format(value[1] as number) }
    : null
})

/** A short height keeps a three-map row inside a normal node body. */
const height = computed(() => (maps.value.length > 2 ? 74 : 96))

function format(value: number): string {
  return Number.isFinite(value) ? formatCompact(value, 4) : '—'
}
</script>

<template>
  <div data-preview="moment-thumbs" :data-maps="maps.length" class="flex flex-col gap-1">
    <div class="grid gap-1" :style="{ gridTemplateColumns: `repeat(${maps.length || 1}, 1fr)` }">
      <figure v-for="map in maps" :key="map.key" class="min-w-0" :data-map="map.key">
        <ImageView
          :tile="map.tile"
          :controls="false"
          :interactive="false"
          :options="map.options"
          :height="height"
          class="overflow-hidden rounded"
        />
        <figcaption class="mt-0.5 truncate text-[10px] text-muted-foreground">
          <span class="font-medium text-foreground">{{ t(`preview.moment.${map.key}`) }}</span>
          <span v-if="map.unit"> · {{ map.unit }}</span>
        </figcaption>
        <p class="truncate font-mono text-[9px] text-muted-foreground">
          {{ format(map.limits[0]) }} … {{ format(map.limits[1]) }}
        </p>
      </figure>
    </div>
    <p class="flex justify-between text-[10px] text-muted-foreground">
      <span v-if="window">{{ t('preview.band', window) }}</span>
      <span v-else />
      <span v-if="shape" class="font-mono">{{ t('preview.shape', shape) }}</span>
    </p>
    <p v-if="!maps.length" class="text-[10px] text-muted-foreground">
      {{ t('preview.no_output') }}
    </p>
  </div>
</template>
