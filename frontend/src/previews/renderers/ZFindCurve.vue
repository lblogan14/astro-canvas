<script setup lang="ts">
/**
 * `zfind-curve` preview for `rbcodes.ZFindResult` / `AbsorberResult`: the score (or chi-square,
 * or significance) curve versus redshift as an inline SVG with the ranked candidates marked,
 * the best one highlighted. Self-contained (no chart library) so hundreds of nodes stay cheap.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { formatScore, formatZ, parseZFind } from '@/editors/zAccept'
import type { PreviewProps } from '@/previews/registry'

const props = defineProps<PreviewProps>()
const { t } = useI18n()

const HEIGHT = 72
const MAX_MARKERS = 5

const parsed = computed(() => parseZFind(props.summary))
const width = computed(() => Math.max(120, Math.round(props.width)))

const curve = computed(() => parsed.value?.curves[0] ?? null)

interface Extent {
  x0: number
  x1: number
  y0: number
  y1: number
}

const extent = computed<Extent | null>(() => {
  const p = parsed.value
  const c = curve.value
  if (!p || !c || p.z.length === 0) return null
  let y0 = Number.POSITIVE_INFINITY
  let y1 = Number.NEGATIVE_INFINITY
  for (const v of c.values) {
    if (v === null) continue
    if (v < y0) y0 = v
    if (v > y1) y1 = v
  }
  if (!(y0 <= y1)) return null
  if (y0 === y1) {
    y0 -= 1
    y1 += 1
  }
  const pad = (y1 - y0) * 0.08
  const x0 = p.zRange?.[0] ?? p.z[0] ?? 0
  const x1 = p.zRange?.[1] ?? p.z[p.z.length - 1] ?? 1
  return { x0, x1: x1 === x0 ? x0 + 1 : x1, y0: y0 - pad, y1: y1 + pad }
})

function sx(x: number, e: Extent): number {
  return ((x - e.x0) / (e.x1 - e.x0)) * width.value
}

function sy(y: number, e: Extent): number {
  return HEIGHT - ((y - e.y0) / (e.y1 - e.y0)) * HEIGHT
}

/** SVG path with a `M` after every gap (null values). */
const path = computed(() => {
  const p = parsed.value
  const c = curve.value
  const e = extent.value
  if (!p || !c || !e) return ''
  const parts: string[] = []
  let pen = false
  for (let i = 0; i < p.z.length; i += 1) {
    const y = c.values[i]
    const x = p.z[i]
    if (y === null || y === undefined || x === undefined || !Number.isFinite(x)) {
      pen = false
      continue
    }
    parts.push(`${pen ? 'L' : 'M'}${sx(x, e).toFixed(1)} ${sy(y, e).toFixed(1)}`)
    pen = true
  }
  return parts.join(' ')
})

const markers = computed(() => {
  const p = parsed.value
  const e = extent.value
  if (!p || !e) return []
  return p.solutions.slice(0, MAX_MARKERS).map((s, i) => ({ x: sx(s.z, e), best: i === 0, z: s.z }))
})

const best = computed(() => parsed.value?.solutions[0] ?? null)
const statisticLabel = computed(() => {
  const s = parsed.value?.statistic ?? 'chi2'
  return t(`preview.zfind.statistic.${s}`)
})
</script>

<template>
  <div data-preview="zfind-curve" :data-candidates="parsed?.solutions.length ?? 0">
    <svg
      v-if="path"
      class="block w-full rounded bg-muted/40"
      :viewBox="`0 0 ${width} ${HEIGHT}`"
      :height="HEIGHT"
      preserveAspectRatio="none"
      role="img"
      :aria-label="statisticLabel"
    >
      <line
        v-for="(m, i) in markers"
        :key="i"
        :x1="m.x"
        :x2="m.x"
        y1="0"
        :y2="HEIGHT"
        :stroke="m.best ? '#F59E0B' : '#9CA3AF'"
        :stroke-width="m.best ? 1.5 : 1"
        :stroke-dasharray="m.best ? undefined : '3 3'"
        data-marker
      />
      <path :d="path" fill="none" stroke="#5B8DEF" stroke-width="1" />
    </svg>
    <p v-else class="text-[10px] text-muted-foreground">{{ t('preview.no_output') }}</p>
    <p class="mt-0.5 flex justify-between gap-2 text-[10px] text-muted-foreground">
      <span v-if="best" class="truncate font-mono" data-testid="zfind-best">
        z = {{ formatZ(best.z, best.zErr) }}
      </span>
      <span v-if="best" class="font-mono">{{ statisticLabel }} {{ formatScore(best.score) }}</span>
      <span v-if="parsed">{{ t('preview.zfind.candidates', { n: parsed.solutions.length }) }}</span>
    </p>
  </div>
</template>
