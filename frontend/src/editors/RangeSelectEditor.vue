<script setup lang="ts">
/**
 * `range-select` editor: drag the vmin/vmax handles (or type them) on the spectrum in velocity
 * around the node's transition. Used by `rbcodes.absorption.slice` (input: rest-frame spectrum
 * plus a Transition) and `rbcodes.absorption.compute_ew` (input: the normalised velocity slice).
 */
import { computed, ref, toRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { Button } from '@/components/ui/button'
import { useWorkflowStore } from '@/stores/workflow'

import EditorPlot from './EditorPlot.vue'
import {
  clampRange,
  extent,
  readRange,
  roundVelocity,
  velocityAxis,
  viewWindow,
} from './rangeSelect'
import type { EditorProps } from './registry'
import { useUpstream } from './useUpstream'

const props = defineProps<EditorProps>()
const emit = defineEmits<{ close: [] }>()

const { t } = useI18n()
const workflow = useWorkflowStore()
const nodeId = toRef(props, 'nodeId')

const node = computed(() => workflow.nodes[props.nodeId])
const params = computed<Record<string, unknown>>(() => node.value?.params ?? {})
const defaults = computed(() => {
  const spec = props.spec
  const lo = spec.params.find((p) => p.name === 'vmin')?.default
  const hi = spec.params.find((p) => p.name === 'vmax')?.default
  return {
    vmin: typeof lo === 'number' ? lo : -200,
    vmax: typeof hi === 'number' ? hi : 200,
  }
})

const spectrum = useUpstream(nodeId, 'spec')
const transition = useUpstream(nodeId, 'transition')

/** Rest wavelength the velocity axis is centred on: the Transition port, else the slice's. */
const wrest = computed<number | null>(() => {
  const fromPort = transition.data.value?.['wrest']
  if (typeof fromPort === 'number') return fromPort
  return spectrum.series.value?.v0Wrest ?? null
})

const velocity = computed<Float64Array | null>(() => {
  const s = spectrum.series.value
  if (!s) return null
  if (s.frame === 'velocity') return velocityAxis(s.wave, 'velocity', 0, null)
  if (wrest.value === null) return null
  return velocityAxis(s.wave, s.frame, wrest.value, s.z)
})
const bounds = computed(() => (velocity.value ? extent(velocity.value) : null))

const range = ref<[number, number]>(readRange(params.value, defaults.value))
watch(
  () => [params.value['vmin'], params.value['vmax']],
  () => {
    range.value = readRange(params.value, defaults.value)
  },
)

const dirty = computed(() => {
  const [lo, hi] = readRange(params.value, defaults.value)
  return lo !== range.value[0] || hi !== range.value[1]
})
const view = computed<[number, number] | null>(() =>
  bounds.value ? viewWindow(range.value, bounds.value, 1.0) : null,
)
const flux = computed(() => spectrum.series.value?.flux ?? null)
const error = computed(() => spectrum.series.value?.error ?? null)
const isNormalized = computed(() => spectrum.series.value?.fluxUnit === 'normalized')

function setRange(lo: number, hi: number): void {
  const [a, b] = clampRange(lo, hi, bounds.value)
  range.value = [roundVelocity(a), roundVelocity(b)]
}

function onInput(which: 0 | 1, event: Event): void {
  const value = Number((event.target as HTMLInputElement).value)
  if (!Number.isFinite(value)) return
  const next: [number, number] = [...range.value]
  next[which] = value
  setRange(next[0], next[1])
}

function apply(): void {
  if (!node.value) return
  workflow.setParams(props.nodeId, { vmin: range.value[0], vmax: range.value[1] })
  emit('close')
}

function reset(): void {
  range.value = readRange(params.value, defaults.value)
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-col gap-2" data-testid="editor-range-select">
    <p class="text-xs text-muted-foreground">{{ t('editor.range.hint') }}</p>
    <div class="min-h-0 flex-1">
      <EditorPlot
        v-if="velocity && flux"
        :x="velocity"
        :y="flux"
        :error="error"
        :range="range"
        :x-range="view"
        :y-range="isNormalized ? [-0.1, 1.6] : null"
        :x-label="t('editor.axis_velocity')"
        :y-label="isNormalized ? t('editor.axis_normalized') : t('editor.axis_flux')"
        dragmode="pan"
        @range-change="setRange"
        @select="setRange"
      />
      <p v-else class="p-4 text-xs text-muted-foreground" data-testid="editor-waiting">
        {{ spectrum.source.value ? t('editor.waiting_upstream') : t('editor.no_input') }}
      </p>
    </div>
    <div class="flex flex-wrap items-end gap-3 border-t pt-2 text-xs">
      <label class="flex flex-col gap-1">
        <span class="text-muted-foreground">{{ t('editor.range.vmin') }}</span>
        <input
          class="h-7 w-28 rounded border bg-background px-2 font-mono"
          type="number"
          step="10"
          :value="range[0]"
          data-testid="range-vmin"
          @change="onInput(0, $event)"
        />
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-muted-foreground">{{ t('editor.range.vmax') }}</span>
        <input
          class="h-7 w-28 rounded border bg-background px-2 font-mono"
          type="number"
          step="10"
          :value="range[1]"
          data-testid="range-vmax"
          @change="onInput(1, $event)"
        />
      </label>
      <span class="font-mono text-muted-foreground" data-testid="range-width">
        {{ t('editor.range.width', { width: roundVelocity(range[1] - range[0]) }) }}
      </span>
      <span class="ml-auto flex gap-2">
        <Button size="sm" variant="ghost" :disabled="!dirty" @click="reset">
          {{ t('editor.reset') }}
        </Button>
        <Button size="sm" :disabled="!dirty" data-testid="editor-apply" @click="apply">
          {{ t('editor.apply') }}
        </Button>
      </span>
    </div>
  </div>
</template>
