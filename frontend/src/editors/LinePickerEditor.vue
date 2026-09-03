<script setup lang="ts">
/**
 * `line-picker` editor for `rbcodes.absorption.set_transition`: click a feature on the
 * rest-frame spectrum, pick one of the nearest transitions of the chosen rbcodes line list,
 * see its doublet partner marked, and Apply writes `wrest` (with `linelist` and `method`).
 * The line list itself comes from the server through `preview.compute` on
 * `rbcodes.lines.line_list`, so no atomic data is duplicated in the client.
 */
import { computed, onBeforeUnmount, ref, toRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { Button } from '@/components/ui/button'
import { useExecutionStore } from '@/stores/execution'
import { useSessionStore } from '@/stores/session'
import { useWorkflowStore } from '@/stores/workflow'

import EditorPlot, { type PlotMarker } from './EditorPlot.vue'
import {
  type Candidate,
  doubletPartner,
  linesFromSummary,
  nearestTransitions,
  toPlotX,
  toRestWavelength,
} from './linePicker'
import { EDITOR_TAG, type EditorProps } from './registry'
import { useUpstream } from './useUpstream'

const LINE_LIST_NODE = 'rbcodes.lines.line_list'
const LINE_LIST_KEY = `type:${LINE_LIST_NODE}`

const props = defineProps<EditorProps>()
const emit = defineEmits<{ close: [] }>()

const { t } = useI18n()
const workflow = useWorkflowStore()
const execution = useExecutionStore()
const session = useSessionStore()
const nodeId = toRef(props, 'nodeId')

const node = computed(() => workflow.nodes[props.nodeId])
const params = computed<Record<string, unknown>>(() => node.value?.params ?? {})
const spectrum = useUpstream(nodeId, 'spec')

const linelist = ref<string>(
  typeof params.value['linelist'] === 'string' ? (params.value['linelist'] as string) : 'atom',
)
const linelistOptions = computed<string[]>(() => {
  const spec = props.spec.params.find((p) => p.name === 'linelist')
  const values = spec?.json_schema['enum']
  return Array.isArray(values) ? values.map(String) : ['atom']
})

const lines = computed(() =>
  linesFromSummary(execution.view(LINE_LIST_KEY, 'out', EDITOR_TAG)?.summary),
)
const clicked = ref<number | null>(
  typeof params.value['wrest'] === 'number' ? (params.value['wrest'] as number) : null,
)
const selected = ref<number | null>(clicked.value)
const candidates = computed<Candidate[]>(() =>
  clicked.value === null ? [] : nearestTransitions(lines.value, clicked.value, 8),
)
const selectedLine = computed(() =>
  selected.value === null
    ? null
    : (lines.value.find((l) => Math.abs(l.wrest - selected.value!) < 1e-3) ?? null),
)
const hint = computed(() => (selected.value === null ? null : doubletPartner(selected.value)))
const dirty = computed(
  () =>
    selected.value !== null &&
    (selected.value !== params.value['wrest'] || linelist.value !== params.value['linelist']),
)

const frame = computed(() => spectrum.series.value?.frame ?? 'rest')
const z = computed(() => spectrum.series.value?.z ?? null)
const v0 = computed(() => spectrum.series.value?.v0Wrest ?? null)
const markers = computed<PlotMarker[]>(() => {
  const out: PlotMarker[] = []
  if (selected.value !== null) {
    const x = toPlotX(selected.value, frame.value, z.value, v0.value)
    if (x !== null)
      out.push({ x, label: selectedLine.value?.name ?? '', color: '#F59E0B', dash: 'solid' })
  }
  if (hint.value) {
    const x = toPlotX(hint.value.partner, frame.value, z.value, v0.value)
    if (x !== null)
      out.push({
        x,
        label: `${hint.value.species} ${Math.round(hint.value.partner)}`,
        color: '#8B5CF6',
      })
  }
  return out
})
const view = computed<[number, number] | null>(() => {
  if (selected.value === null) return null
  const x = toPlotX(selected.value, frame.value, z.value, v0.value)
  if (x === null) return null
  const half = frame.value === 'velocity' ? 3000 : x * 0.02
  return [x - half, x + half]
})

function loadLines(): void {
  session.requestCompute({
    node_type: LINE_LIST_NODE,
    params: { name: linelist.value },
    tag: EDITOR_TAG,
    viewport: { rows: 5000 },
  })
}
watch(linelist, loadLines, { immediate: true })
onBeforeUnmount(() => execution.clearTag(LINE_LIST_KEY, EDITOR_TAG))

function onClick(x: number): void {
  const rest = toRestWavelength(x, frame.value, z.value, v0.value)
  if (rest === null) return
  clicked.value = rest
  const nearest = nearestTransitions(lines.value, rest, 1)[0]
  if (nearest) selected.value = nearest.wrest
}

function pick(candidate: Candidate): void {
  selected.value = candidate.wrest
}

function onLinelist(event: Event): void {
  linelist.value = (event.target as HTMLSelectElement).value
}

function apply(): void {
  if (!node.value || selected.value === null) return
  workflow.setParams(props.nodeId, {
    wrest: selected.value,
    linelist: linelist.value,
    method: 'closest',
  })
  emit('close')
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-col gap-2" data-testid="editor-line-picker">
    <p class="text-xs text-muted-foreground">{{ t('editor.lines.hint') }}</p>
    <div class="grid min-h-0 flex-1 grid-cols-[1fr_18rem] gap-3">
      <div class="min-h-0">
        <EditorPlot
          v-if="spectrum.series.value"
          :x="spectrum.series.value.wave"
          :y="spectrum.series.value.flux"
          :error="spectrum.series.value.error"
          :markers="markers"
          :x-range="view"
          :x-label="frame === 'velocity' ? t('editor.axis_velocity') : t('editor.axis_wavelength')"
          :y-label="t('editor.axis_flux')"
          dragmode="pan"
          @click="onClick"
        />
        <p v-else class="p-4 text-xs text-muted-foreground" data-testid="editor-waiting">
          {{ spectrum.source.value ? t('editor.waiting_upstream') : t('editor.no_input') }}
        </p>
      </div>
      <aside class="flex min-h-0 flex-col gap-3 overflow-auto text-xs">
        <label class="flex flex-col gap-1">
          <span class="text-[10px] font-medium text-muted-foreground uppercase">
            {{ t('editor.lines.linelist') }}
          </span>
          <select
            class="h-7 rounded border bg-background px-1"
            :value="linelist"
            data-testid="picker-linelist"
            @change="onLinelist"
          >
            <option v-for="name in linelistOptions" :key="name" :value="name">{{ name }}</option>
          </select>
          <span class="text-muted-foreground">{{
            t('editor.lines.count', { n: lines.length })
          }}</span>
        </label>
        <section>
          <h3 class="mb-1 text-[10px] font-medium text-muted-foreground uppercase">
            {{ t('editor.lines.candidates') }}
          </h3>
          <table v-if="candidates.length" class="w-full" data-testid="line-candidates">
            <tbody>
              <tr
                v-for="c in candidates"
                :key="c.wrest"
                class="cursor-pointer hover:bg-muted"
                :class="c.wrest === selected ? 'font-semibold' : ''"
                :data-wrest="c.wrest"
                :aria-selected="c.wrest === selected"
                @click="pick(c)"
              >
                <td>{{ c.name }}</td>
                <td class="text-right font-mono">{{ c.wrest.toFixed(2) }}</td>
                <td class="text-right font-mono text-muted-foreground">
                  {{ c.deltaKms > 0 ? '+' : '' }}{{ Math.round(c.deltaKms) }}
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else class="text-muted-foreground">{{ t('editor.lines.click_first') }}</p>
        </section>
        <section v-if="selectedLine" data-testid="picker-selected">
          <h3 class="mb-1 text-[10px] font-medium text-muted-foreground uppercase">
            {{ t('editor.lines.selected') }}
          </h3>
          <p class="font-mono">
            {{ selectedLine.name }} · {{ selectedLine.wrest.toFixed(3) }} Å · f =
            {{ selectedLine.fval }}
          </p>
          <p v-if="hint" class="mt-1 text-muted-foreground" data-testid="doublet-hint">
            {{
              t('editor.lines.doublet', {
                species: hint.species,
                partner: hint.partner.toFixed(2),
                offset: Math.round(hint.offsetKms),
              })
            }}
          </p>
        </section>
      </aside>
    </div>
    <div class="flex items-center justify-end gap-2 border-t pt-2">
      <Button size="sm" :disabled="!dirty" data-testid="editor-apply" @click="apply">
        {{ t('editor.apply') }}
      </Button>
    </div>
  </div>
</template>
