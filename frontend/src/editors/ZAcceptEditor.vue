<script setup lang="ts">
/**
 * `z-accept` editor for `rbcodes.zfind.rank`: the score/chi-square curve of each connected scan
 * with its candidates marked (click a candidate on the curve or in the table), the searched
 * spectrum below with a curated line list overlaid at the hovered/selected redshift (emission
 * ticks green, absorption red), and Apply writing the accepted row index to `accepted`.
 * Candidates are numbered exactly like the backend's `combine_candidates`, so the index the
 * node stores is the one shown here.
 */
import { computed, onBeforeUnmount, ref, toRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { Button } from '@/components/ui/button'
import { useExecutionStore } from '@/stores/execution'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useSessionStore } from '@/stores/session'
import { useWorkflowStore } from '@/stores/workflow'

import EditorPlot, { type PlotMarker, type PlotOverlay } from './EditorPlot.vue'
import { EDITOR_TAG, type EditorProps } from './registry'
import { useUpstream } from './useUpstream'
import {
  CURATED_LINELISTS,
  type ZCandidate,
  combineCandidates,
  curatedLinesFromSummary,
  curveSeries,
  defaultLinelist,
  formatScore,
  formatZ,
  lineTicks,
  nearestCandidate,
  parseZFind,
} from './zAccept'

const LINELIST_NODE = 'rbcodes.zfind.curated_linelist'
const LINELIST_KEY = `type:${LINELIST_NODE}`
const PORTS = ['results', 'results_2', 'results_3', 'results_4'] as const
const SELECTED_COLOR = '#F59E0B'
const OTHER_COLOR = '#9CA3AF'
const EMISSION_COLOR = '#1C9C5A'
const ABSORPTION_COLOR = '#D64545'

const props = defineProps<EditorProps>()
const emit = defineEmits<{ close: [] }>()

const { t } = useI18n()
const workflow = useWorkflowStore()
const execution = useExecutionStore()
const session = useSessionStore()
const schema = useNodesSchemaStore()
const nodeId = toRef(props, 'nodeId')

const node = computed(() => workflow.nodes[props.nodeId])
const params = computed<Record<string, unknown>>(() => node.value?.params ?? {})
const committed = computed<number | null>(() =>
  typeof params.value['accepted'] === 'number' ? params.value['accepted'] : null,
)

const upstreams = PORTS.map((port) => useUpstream(nodeId, port))
const sources = computed(() => upstreams.map((u) => parseZFind(u.entry.value?.summary)))
const connected = computed(() => upstreams.filter((u) => u.source.value !== null).length)
const candidates = computed<ZCandidate[]>(() => combineCandidates(sources.value))

const selected = ref<number | null>(committed.value)
const current = computed<ZCandidate | null>(
  () => candidates.value[selected.value ?? 0] ?? candidates.value[0] ?? null,
)
const activeSource = ref(0)
const previewZ = ref<number | null>(null)
const overlayZ = computed(() => previewZ.value ?? current.value?.z ?? null)
const dirty = computed(() => selected.value !== null && selected.value !== (committed.value ?? 0))

const active = computed(() => sources.value[activeSource.value] ?? null)
const curve = computed(() => (active.value ? curveSeries(active.value, 0) : null))
const curveOverlays = computed<PlotOverlay[]>(() => {
  const source = active.value
  if (!source) return []
  return source.curves.slice(1).map((c, i) => ({
    x: source.z,
    y: c.values.map((v) => v ?? Number.NaN),
    name: c.label,
    color: ['#8B5CF6', '#0EA5E9', '#10B981', '#EC4899'][i % 4],
    dash: 'solid' as const,
  }))
})
const curveMarkers = computed<PlotMarker[]>(() =>
  candidates.value
    .filter((c) => c.source === activeSource.value)
    .map((c) => ({
      x: c.z,
      label: `#${c.index}`,
      color: c.index === current.value?.index ? SELECTED_COLOR : OTHER_COLOR,
      dash: c.index === current.value?.index ? 'solid' : 'dot',
    })),
)
const statisticLabel = computed(() =>
  t(`editor.zaccept.statistic.${active.value?.statistic ?? 'chi2'}`),
)

const spectrum = computed(() => active.value?.spectrum ?? null)
const spectrumOverlays = computed<PlotOverlay[]>(() => {
  const s = spectrum.value
  if (!s?.continuum) return []
  return [{ x: s.wave, y: s.continuum, name: t('widgets.continuum'), color: EMISSION_COLOR }]
})

const linelist = ref<string>('zfind_galaxy')
const linelistOptions = computed<string[]>(() => {
  const spec = schema.byId[LINELIST_NODE]?.params.find((p) => p.name === 'name')
  const values = spec?.json_schema['enum']
  return Array.isArray(values) ? values.map(String) : [...CURATED_LINELISTS]
})
const lines = computed(() =>
  curatedLinesFromSummary(execution.view(LINELIST_KEY, 'out', EDITOR_TAG)?.summary),
)
const ticks = computed(() =>
  overlayZ.value === null || !spectrum.value
    ? []
    : lineTicks(lines.value, overlayZ.value, spectrum.value.range),
)
const spectrumMarkers = computed<PlotMarker[]>(() =>
  ticks.value.map((tick) => ({
    x: tick.x,
    label: tick.name,
    color: tick.kind === 'emission' ? EMISSION_COLOR : ABSORPTION_COLOR,
    dash: tick.kind === 'emission' ? 'solid' : 'dash',
  })),
)

function loadLines(): void {
  session.requestCompute({
    node_type: LINELIST_NODE,
    params: { name: linelist.value },
    tag: EDITOR_TAG,
    viewport: { rows: 200 },
  })
}
watch(linelist, loadLines, { immediate: true })
onBeforeUnmount(() => execution.clearTag(LINELIST_KEY, EDITOR_TAG))

// Follow the first scan's line list once it arrives (a curated preset when it is one).
let linelistSeeded = false
watch(
  () => sources.value[0]?.linelist,
  (label) => {
    if (linelistSeeded || label === undefined) return
    linelistSeeded = true
    linelist.value = defaultLinelist(label)
  },
  { immediate: true },
)
// Show the source of the current candidate whenever the selection changes.
watch(
  () => current.value?.source,
  (source) => {
    if (source !== undefined) activeSource.value = source
  },
  { immediate: true },
)
watch(committed, (next) => {
  // The document changed underneath (undo, another client): follow it unless we have edits.
  if (!dirty.value) selected.value = next
})

function select(candidate: ZCandidate): void {
  selected.value = candidate.index
  activeSource.value = candidate.source
}

function onCurveClick(x: number): void {
  const nearest = nearestCandidate(candidates.value, activeSource.value, x)
  if (nearest) select(nearest)
}

function showSource(index: number): void {
  activeSource.value = index
}

function onLinelist(event: Event): void {
  linelist.value = (event.target as HTMLSelectElement).value
}

function sourceLabel(index: number): string {
  const source = sources.value[index]
  const method = source?.curves[0]?.label ?? source?.solutions[0]?.method
  return method ?? t('editor.zaccept.source', { n: index + 1 })
}

function apply(): void {
  if (!node.value || selected.value === null) return
  workflow.setParams(props.nodeId, { accepted: selected.value })
  emit('close')
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-col gap-2" data-testid="editor-z-accept">
    <p class="text-xs text-muted-foreground">{{ t('editor.zaccept.hint') }}</p>
    <div class="grid min-h-0 flex-1 grid-cols-[1fr_20rem] gap-3">
      <div class="grid min-h-0 grid-rows-2 gap-2">
        <div class="min-h-0" data-testid="zaccept-curve" :data-source="activeSource">
          <EditorPlot
            v-if="curve"
            :x="curve.x"
            :y="curve.y"
            :overlays="curveOverlays"
            :markers="curveMarkers"
            :step="false"
            x-label="z"
            :y-label="statisticLabel"
            dragmode="pan"
            @click="onCurveClick"
          />
          <p v-else class="p-4 text-xs text-muted-foreground" data-testid="editor-waiting">
            {{ connected ? t('editor.waiting_upstream') : t('editor.no_input') }}
          </p>
        </div>
        <div class="min-h-0" data-testid="zaccept-spectrum" :data-lines="ticks.length">
          <EditorPlot
            v-if="spectrum"
            :x="spectrum.wave"
            :y="spectrum.flux"
            :error="spectrum.error"
            :overlays="spectrumOverlays"
            :markers="spectrumMarkers"
            :x-label="t('editor.axis_wavelength')"
            :y-label="t('editor.axis_flux')"
            dragmode="pan"
          />
          <p v-else class="p-4 text-xs text-muted-foreground">
            {{ t('editor.zaccept.no_spectrum') }}
          </p>
        </div>
      </div>
      <aside class="flex min-h-0 flex-col gap-3 overflow-auto text-xs">
        <section v-if="connected > 1">
          <h3 class="mb-1 text-[10px] font-medium text-muted-foreground uppercase">
            {{ t('editor.zaccept.sources') }}
          </h3>
          <div class="flex flex-wrap gap-1">
            <template v-for="(source, index) in sources" :key="index">
              <button
                v-if="source"
                type="button"
                class="rounded border px-2 py-0.5 hover:bg-muted"
                :class="index === activeSource ? 'bg-muted font-semibold' : ''"
                data-testid="zaccept-source"
                :data-source="index"
                :aria-pressed="index === activeSource"
                @click="showSource(index)"
              >
                {{ sourceLabel(index) }}
              </button>
            </template>
          </div>
        </section>
        <section class="min-h-0 flex-1 overflow-auto">
          <h3 class="mb-1 text-[10px] font-medium text-muted-foreground uppercase">
            {{ t('editor.zaccept.candidates') }}
          </h3>
          <table v-if="candidates.length" class="w-full" data-testid="zaccept-candidates">
            <thead class="text-left text-[10px] text-muted-foreground">
              <tr>
                <th>#</th>
                <th>z</th>
                <th class="text-right">{{ t('editor.zaccept.score') }}</th>
                <th>{{ t('editor.zaccept.method') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="c in candidates"
                :key="c.index"
                class="cursor-pointer hover:bg-muted"
                :class="c.index === current?.index ? 'bg-muted/60 font-semibold' : ''"
                data-testid="zaccept-candidate"
                :data-index="c.index"
                :data-source="c.source"
                :aria-selected="c.index === current?.index"
                @click="select(c)"
                @mouseenter="previewZ = c.z"
                @mouseleave="previewZ = null"
              >
                <td class="font-mono">{{ c.index }}</td>
                <td class="font-mono">{{ formatZ(c.z, c.zErr) }}</td>
                <td class="text-right font-mono">{{ formatScore(c.score) }}</td>
                <td class="max-w-[7rem] truncate" :title="c.method">{{ c.method }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="text-muted-foreground">{{ t('editor.zaccept.no_candidates') }}</p>
        </section>
        <label class="flex flex-col gap-1">
          <span class="text-[10px] font-medium text-muted-foreground uppercase">
            {{ t('editor.zaccept.linelist') }}
          </span>
          <select
            class="h-7 rounded border bg-background px-1"
            :value="linelist"
            data-testid="zaccept-linelist"
            @change="onLinelist"
          >
            <option v-for="name in linelistOptions" :key="name" :value="name">{{ name }}</option>
          </select>
          <span class="text-muted-foreground">{{
            t('editor.zaccept.lines_shown', { n: ticks.length, total: lines.length })
          }}</span>
        </label>
        <section v-if="current" data-testid="zaccept-selected" :data-index="current.index">
          <h3 class="mb-1 text-[10px] font-medium text-muted-foreground uppercase">
            {{ t('editor.zaccept.selected') }}
          </h3>
          <p class="font-mono">z = {{ formatZ(current.z, current.zErr) }}</p>
          <p class="text-muted-foreground">
            {{ t(`editor.zaccept.statistic.${sources[current.source]?.statistic ?? 'chi2'}`) }} =
            {{ formatScore(current.score) }} · {{ current.method }} ·
            {{ t('editor.zaccept.features', { n: current.nFeatures }) }}
          </p>
          <p v-if="active?.warnings.length" class="mt-1 text-amber-700">
            {{ active.warnings.join(' ') }}
          </p>
        </section>
      </aside>
    </div>
    <div class="flex items-center justify-end gap-2 border-t pt-2">
      <span v-if="current" class="mr-auto text-xs text-muted-foreground">
        {{ t('editor.zaccept.will_write', { index: current.index }) }}
      </span>
      <Button size="sm" :disabled="!dirty" data-testid="editor-apply" @click="apply">
        {{ t('editor.apply') }}
      </Button>
    </div>
  </div>
</template>
