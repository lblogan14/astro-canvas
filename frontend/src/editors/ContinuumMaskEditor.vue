<script setup lang="ts">
/**
 * `continuum-mask` editor for `rbcodes.continuum.fit`: the velocity slice with shaded mask
 * ranges (drag horizontally to add, click a band to remove, or type a range), a live fit
 * preview computed by the server with the candidate params (`preview.compute`, tagged
 * `editor`), the BIC-per-order table, and Apply writing `masks`, `order`, `method` and
 * `optimize_order` to the node in one undo step.
 */
import { computed, onBeforeUnmount, ref, toRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { X } from '@lucide/vue'

import { Button } from '@/components/ui/button'
import { useExecutionStore } from '@/stores/execution'
import { useSessionStore } from '@/stores/session'
import { useWorkflowStore } from '@/stores/workflow'

import {
  CONTINUUM_METHODS,
  type ContinuumSettings,
  addMask,
  bicRows,
  continuumOverlay,
  formatMask,
  maskAt,
  paramsFromSettings,
  removeMask,
  settingsEqual,
  settingsFromParams,
} from './continuumMask'
import EditorPlot from './EditorPlot.vue'
import { EDITOR_TAG, type EditorProps } from './registry'
import { useUpstream } from './useUpstream'

/** Debounce before a candidate is sent to the server (the fit itself takes ~20 ms). */
const PREVIEW_DEBOUNCE_MS = 80

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

const settings = ref<ContinuumSettings>(settingsFromParams(params.value))
const committed = computed(() => settingsFromParams(params.value))
const dirty = computed(() => !settingsEqual(settings.value, committed.value))

const manualLo = ref<number | null>(null)
const manualHi = ref<number | null>(null)

const previewContinuum = computed(
  () => execution.view(props.nodeId, 'continuum', EDITOR_TAG)?.summary,
)
const previewStatus = computed(() => execution.compute(props.nodeId, EDITOR_TAG))
const pending = ref(false)

const x = computed(() => spectrum.series.value?.wave ?? null)
const flux = computed(() => spectrum.series.value?.flux ?? null)
const error = computed(() => spectrum.series.value?.error ?? null)
const overlay = computed(() => {
  if (!x.value) return []
  const fit = continuumOverlay(previewContinuum.value, x.value)
  return fit
    ? [{ ...fit, name: t('widgets.continuum'), color: '#1C9C5A', dash: 'solid' as const }]
    : []
})
const bands = computed(() => settings.value.masks.map(([lo, hi]) => ({ lo, hi })))
const rows = computed(() => bicRows(previewContinuum.value))
const fittedOrder = computed(() => {
  const order = previewContinuum.value?.['order']
  return typeof order === 'number' ? order : null
})
const fitError = computed(() => {
  const p = previewContinuum.value?.['params']
  const value =
    typeof p === 'object' && p !== null ? (p as Record<string, unknown>)['fit_error'] : undefined
  return typeof value === 'number' ? value : null
})

let timer: ReturnType<typeof setTimeout> | null = null

function requestPreview(): void {
  if (timer !== null) clearTimeout(timer)
  timer = setTimeout(() => {
    timer = null
    pending.value = true
    session.requestCompute({
      node_id: props.nodeId,
      params: paramsFromSettings(settings.value),
      tag: EDITOR_TAG,
      viewport: { n_out: 20000 },
    })
  }, PREVIEW_DEBOUNCE_MS)
}

watch(previewStatus, () => {
  pending.value = false
})
watch(settings, requestPreview, { deep: true, immediate: true })
watch(committed, (next) => {
  // The document changed underneath (undo, another client): follow it unless we have edits.
  if (!dirty.value) settings.value = { ...next, masks: [...next.masks] }
})

onBeforeUnmount(() => {
  if (timer !== null) clearTimeout(timer)
  execution.clearTag(props.nodeId, EDITOR_TAG)
})

function onSelect(lo: number, hi: number): void {
  settings.value = { ...settings.value, masks: addMask(settings.value.masks, lo, hi) }
}

function onClick(xValue: number): void {
  const index = maskAt(settings.value.masks, xValue)
  if (index !== -1) removeAt(index)
}

function removeAt(index: number): void {
  settings.value = { ...settings.value, masks: removeMask(settings.value.masks, index) }
}

function addManual(): void {
  if (manualLo.value === null || manualHi.value === null) return
  if (!Number.isFinite(manualLo.value) || !Number.isFinite(manualHi.value)) return
  if (manualLo.value === manualHi.value) return
  onSelect(manualLo.value, manualHi.value)
  manualLo.value = null
  manualHi.value = null
}

function setMethod(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  if (CONTINUUM_METHODS.includes(value as ContinuumSettings['method'])) {
    settings.value = { ...settings.value, method: value as ContinuumSettings['method'] }
  }
}

function setOrder(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  if (value === 'auto') {
    settings.value = { ...settings.value, optimizeOrder: true }
    return
  }
  const order = Number(value)
  if (Number.isFinite(order)) {
    settings.value = { ...settings.value, optimizeOrder: false, order }
  }
}

function pickOrder(order: number): void {
  settings.value = { ...settings.value, optimizeOrder: false, order }
}

function apply(): void {
  if (!node.value) return
  workflow.setParams(props.nodeId, paramsFromSettings(settings.value))
  emit('close')
}

function reset(): void {
  const next = committed.value
  settings.value = { ...next, masks: [...next.masks] }
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-col gap-2" data-testid="editor-continuum-mask">
    <p class="text-xs text-muted-foreground">{{ t('editor.continuum.hint') }}</p>
    <div class="grid min-h-0 flex-1 grid-cols-[1fr_16rem] gap-3">
      <div class="min-h-0">
        <EditorPlot
          v-if="x && flux"
          :x="x"
          :y="flux"
          :error="error"
          :overlays="overlay"
          :bands="bands"
          :x-label="t('editor.axis_velocity')"
          :y-label="t('editor.axis_flux')"
          dragmode="select"
          @select="onSelect"
          @click="onClick"
        />
        <p v-else class="p-4 text-xs text-muted-foreground" data-testid="editor-waiting">
          {{ spectrum.source.value ? t('editor.waiting_upstream') : t('editor.no_input') }}
        </p>
      </div>

      <aside class="flex min-h-0 flex-col gap-3 overflow-auto text-xs">
        <section>
          <h3 class="mb-1 text-[10px] font-medium text-muted-foreground uppercase">
            {{ t('editor.continuum.masks') }}
          </h3>
          <ul v-if="settings.masks.length" class="space-y-1" data-testid="mask-list">
            <li
              v-for="(mask, i) in settings.masks"
              :key="`${mask[0]}-${mask[1]}`"
              class="flex items-center justify-between rounded border px-2 py-1 font-mono"
              data-testid="mask-item"
            >
              <span>{{ formatMask(mask) }}</span>
              <button
                type="button"
                class="inline-flex size-5 items-center justify-center rounded hover:bg-muted"
                :aria-label="t('editor.continuum.remove_mask')"
                data-testid="mask-remove"
                @click="removeAt(i)"
              >
                <X class="size-3" />
              </button>
            </li>
          </ul>
          <p v-else class="text-muted-foreground">{{ t('editor.continuum.no_masks') }}</p>
          <div class="mt-2 flex items-end gap-1">
            <input
              v-model.number="manualLo"
              class="h-7 w-20 rounded border bg-background px-1 font-mono"
              type="number"
              step="10"
              :placeholder="t('editor.range.vmin')"
              data-testid="mask-lo"
            />
            <input
              v-model.number="manualHi"
              class="h-7 w-20 rounded border bg-background px-1 font-mono"
              type="number"
              step="10"
              :placeholder="t('editor.range.vmax')"
              data-testid="mask-hi"
            />
            <Button size="xs" variant="outline" data-testid="mask-add" @click="addManual">
              {{ t('editor.continuum.add_mask') }}
            </Button>
          </div>
        </section>

        <section class="grid grid-cols-2 gap-2">
          <label class="flex flex-col gap-1">
            <span class="text-[10px] font-medium text-muted-foreground uppercase">
              {{ t('editor.continuum.method') }}
            </span>
            <select
              class="h-7 rounded border bg-background px-1"
              :value="settings.method"
              data-testid="continuum-method"
              @change="setMethod"
            >
              <option v-for="m in CONTINUUM_METHODS" :key="m" :value="m">
                {{ t(`editor.continuum.methods.${m}`) }}
              </option>
            </select>
          </label>
          <label class="flex flex-col gap-1">
            <span class="text-[10px] font-medium text-muted-foreground uppercase">
              {{ t('editor.continuum.order') }}
            </span>
            <select
              class="h-7 rounded border bg-background px-1"
              :value="settings.optimizeOrder ? 'auto' : String(settings.order)"
              data-testid="continuum-order"
              @change="setOrder"
            >
              <option value="auto">{{ t('editor.continuum.order_auto') }}</option>
              <option v-for="o in 16" :key="o" :value="String(o - 1)">{{ o - 1 }}</option>
            </select>
          </label>
        </section>

        <section>
          <h3 class="mb-1 text-[10px] font-medium text-muted-foreground uppercase">
            {{ t('editor.continuum.bic_table') }}
          </h3>
          <table v-if="rows.length" class="w-full font-mono" data-testid="bic-table">
            <thead>
              <tr class="text-muted-foreground">
                <th class="text-left">{{ t('editor.continuum.order') }}</th>
                <th class="text-right">BIC</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in rows"
                :key="row.order"
                class="cursor-pointer hover:bg-muted"
                :class="row.best ? 'font-semibold text-foreground' : ''"
                :data-best="row.best ? 'true' : undefined"
                @click="pickOrder(row.order)"
              >
                <td>{{ row.order }}</td>
                <td class="text-right">{{ row.bic.toFixed(2) }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="text-muted-foreground">{{ t('editor.continuum.no_bic') }}</p>
        </section>

        <p class="text-muted-foreground" data-testid="editor-fit-status" :data-pending="pending">
          <template v-if="pending">{{ t('editor.continuum.fitting') }}</template>
          <template v-else-if="previewStatus && !previewStatus.ok">
            <span class="text-destructive">{{ previewStatus.error }}</span>
          </template>
          <template v-else-if="previewStatus">
            {{
              t('editor.continuum.fit_done', {
                order: fittedOrder ?? '–',
                ms: Math.round(previewStatus.elapsedMs),
                err: fitError !== null ? fitError.toFixed(4) : '–',
              })
            }}
          </template>
        </p>
      </aside>
    </div>
    <div class="flex items-center justify-end gap-2 border-t pt-2">
      <Button size="sm" variant="ghost" :disabled="!dirty" @click="reset">
        {{ t('editor.reset') }}
      </Button>
      <Button size="sm" :disabled="!dirty" data-testid="editor-apply" @click="apply">
        {{ t('editor.apply') }}
      </Button>
    </div>
  </div>
</template>
