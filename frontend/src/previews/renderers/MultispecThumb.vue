<script setup lang="ts">
/**
 * `multispec-thumb` preview for `rbcodes.MultispecView`: a mini stacked view of the viewer's
 * panels with the absorber systems drawn as coloured vertical ticks and the identified lines in
 * amber. Self-contained inline SVG (no chart library) so a canvas full of these stays cheap.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { cssColor, formatZabs, parseView } from '@/editors/multispec'
import type { PreviewProps } from '@/previews/registry'

const props = defineProps<PreviewProps>()
const { t } = useI18n()

const MAX_PANELS = 4
const PANEL_HEIGHT = 26
const GAP = 2

const parsed = computed(() => parseView(props.summary))
const width = computed(() => Math.max(120, Math.round(props.width)))
const panels = computed(() => parsed.value?.panels.slice(0, MAX_PANELS) ?? [])
const height = computed(() => Math.max(PANEL_HEIGHT, panels.value.length * (PANEL_HEIGHT + GAP)))

const range = computed<[number, number] | null>(() => parsed.value?.range ?? null)

function sx(x: number): number {
  const r = range.value
  if (!r || r[1] === r[0]) return 0
  return ((x - r[0]) / (r[1] - r[0])) * width.value
}

/** One `M`/`L` path per panel, scaled into its own band. */
const paths = computed(() =>
  panels.value.map((panel, index) => {
    let lo = Number.POSITIVE_INFINITY
    let hi = Number.NEGATIVE_INFINITY
    for (let i = 0; i < panel.flux.length; i += 1) {
      const f = panel.flux[i]
      if (f === undefined || !Number.isFinite(f)) continue
      if (f < lo) lo = f
      if (f > hi) hi = f
    }
    if (!(lo < hi)) return ''
    const top = index * (PANEL_HEIGHT + GAP)
    const parts: string[] = []
    let pen = false
    for (let i = 0; i < panel.wave.length; i += 1) {
      const w = panel.wave[i]
      const f = panel.flux[i]
      if (w === undefined || f === undefined || !Number.isFinite(f)) {
        pen = false
        continue
      }
      const y = top + PANEL_HEIGHT - 1 - ((f - lo) / (hi - lo)) * (PANEL_HEIGHT - 2)
      parts.push(`${pen ? 'L' : 'M'}${sx(w).toFixed(1)} ${y.toFixed(1)}`)
      pen = true
    }
    return parts.join(' ')
  }),
)

/**
 * The identified lines as amber ticks. Absorber systems are not drawn: their transitions depend
 * on a line list the preview does not fetch, so they appear as coloured chips under the stack.
 */
const ticks = computed<number[]>(() => {
  const view = parsed.value
  const r = range.value
  if (!view || !r) return []
  return view.identified
    .filter((line) => line.waveObs >= r[0] && line.waveObs <= r[1])
    .map((line) => sx(line.waveObs))
})

const MAX_CHIPS = 4
const chips = computed(() => parsed.value?.absorbers.slice(0, MAX_CHIPS) ?? [])

const caption = computed(() => {
  const view = parsed.value
  if (!view) return ''
  return t('preview.multispec.caption', {
    panels: view.count,
    absorbers: view.absorbers.length,
    lines: view.identified.length,
  })
})
</script>

<template>
  <div
    data-preview="multispec-thumb"
    :data-panels="parsed?.count ?? 0"
    :data-absorbers="parsed?.absorbers.length ?? 0"
    :data-lines="parsed?.identified.length ?? 0"
  >
    <svg
      v-if="panels.length"
      class="block w-full rounded bg-muted/40"
      :viewBox="`0 0 ${width} ${height}`"
      :height="height"
      preserveAspectRatio="none"
      role="img"
      :aria-label="caption"
    >
      <line
        v-for="(x, i) in ticks"
        :key="`t${i}`"
        :x1="x"
        :x2="x"
        y1="0"
        :y2="height"
        stroke="#F59E0B"
        stroke-width="1"
        data-marker
      />
      <path
        v-for="(d, i) in paths"
        :key="`p${i}`"
        :d="d"
        fill="none"
        stroke="#5B8DEF"
        stroke-width="0.9"
      />
    </svg>
    <p v-else class="text-[10px] text-muted-foreground">{{ t('preview.no_output') }}</p>
    <p v-if="chips.length" class="mt-0.5 flex flex-wrap gap-1 text-[10px] text-muted-foreground">
      <span
        v-for="(absorber, i) in chips"
        :key="i"
        class="inline-flex items-center gap-1 font-mono"
        data-testid="multispec-thumb-absorber"
      >
        <span
          class="inline-block h-2 w-2 rounded-full"
          :style="{ background: cssColor(absorber.color) }"
        />
        {{ formatZabs(absorber.zabs) }}
      </span>
    </p>
    <p class="mt-0.5 flex justify-between gap-2 text-[10px] text-muted-foreground">
      <span>{{ caption }}</span>
      <span v-if="parsed" class="font-mono" data-testid="multispec-thumb-z">
        z = {{ formatZabs(parsed.z) }}
      </span>
    </p>
  </div>
</template>
