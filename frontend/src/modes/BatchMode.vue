<script setup lang="ts">
/**
 * Batch mode (design §8.4): a table editor whose columns bind to node params, run controls with
 * per-row status pills, and the results grid with CSV/ECSV export.
 *
 * The generalisation of `launch_specgui -b`: importing a specgui `master_batch_table` CSV or
 * JSON maps its columns onto the absorption template automatically, keeping `slice_vmin/vmax`
 * and `ew_vmin/vmax` as separate columns.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Ban, Download, ExternalLink, Play, Plus, Save, Trash2, Upload } from '@lucide/vue'

import { Button } from '@/components/ui/button'
import { toCsv, toEcsv } from '@/modes/batchTable'
import { bindableRefs, useBatchStore } from '@/stores/batch'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'

const { t } = useI18n()
const batch = useBatchStore()
const workflow = useWorkflowStore()
const ui = useUiStore()

const fileInput = ref<HTMLInputElement | null>(null)
const pasteOpen = ref(false)
const pasteText = ref('')

/** Every `"<node>.<param>"` a column may bind to, promoted params first. */
const refs = computed(() =>
  bindableRefs(
    (workflow.doc?.promoted ?? []) as { node: string; param: string }[],
    workflow.nodes as Record<string, { params?: Record<string, unknown> }>,
  ),
)

/** Every `"<node>.<port>"` whose value can be collected into the results table. */
const outputRefs = computed(() => {
  const out: string[] = []
  for (const [nodeId, node] of Object.entries(workflow.nodes)) {
    for (const port of workflow.specs[node.type]?.outputs ?? []) out.push(`${nodeId}.${port.name}`)
  }
  return out
})

const canRun = computed(
  () => workflow.isOpen && batch.rowCount > 0 && batch.collect.length > 0 && !batch.isRunning,
)
const selectedRows = computed(() => [...batch.selected].sort((a, b) => a - b))
const resultColumns = computed(() => batch.results?.columns ?? [])

onMounted(() => {
  if (batch.columns.length === 0) batch.loadLayout()
})

function importFile(event: Event): void {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    const result = batch.importText(String(reader.result ?? ''))
    ui.notify(
      result.preset
        ? t('batch.imported_specgui', { rows: result.rows })
        : t('batch.imported', { rows: result.rows }),
    )
  }
  reader.readAsText(file)
  ;(event.target as HTMLInputElement).value = ''
}

function applyPaste(): void {
  const result = batch.importText(pasteText.value)
  pasteOpen.value = false
  pasteText.value = ''
  ui.notify(t('batch.imported', { rows: result.rows }))
}

function download(kind: 'csv' | 'ecsv'): void {
  const results = batch.results
  if (!results) return
  const columns = results.columns ?? []
  const rows = (results.rows ?? []) as Record<string, never>[]
  const text = kind === 'csv' ? toCsv(columns, rows) : toEcsv(columns, rows)
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${workflow.name || 'batch'}-results.${kind}`
  link.click()
  URL.revokeObjectURL(url)
}

function openRow(index: number): void {
  if (batch.openInCanvas(index)) {
    ui.setMode('canvas')
    ui.notify(t('batch.opened_in_canvas', { row: index + 1 }))
  }
}

function toggleCollect(ref: string): void {
  batch.collect = batch.collect.includes(ref)
    ? batch.collect.filter((r) => r !== ref)
    : [...batch.collect, ref]
}

function cellValue(index: number, column: string): string {
  const value = batch.rows[index]?.[column]
  return value === null || value === undefined ? '' : String(value)
}

function onCell(index: number, column: string, event: Event): void {
  const raw = (event.target as HTMLInputElement).value
  batch.setCell(index, column, raw === '' ? null : raw)
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-col bg-background" data-testid="batch-mode">
    <div class="flex shrink-0 flex-wrap items-center gap-1 border-b px-2 py-1.5">
      <Button size="sm" :disabled="!canRun" data-testid="batch-run" @click="batch.run()">
        <Play /> {{ t('batch.run_all', { n: batch.rowCount }) }}
      </Button>
      <Button
        size="sm"
        variant="secondary"
        :disabled="!canRun || selectedRows.length === 0"
        data-testid="batch-run-selected"
        @click="batch.run(selectedRows)"
      >
        <Play /> {{ t('batch.run_selected', { n: selectedRows.length }) }}
      </Button>
      <Button
        size="sm"
        variant="destructive"
        :disabled="!batch.isRunning"
        data-testid="batch-cancel"
        @click="batch.cancel()"
      >
        <Ban /> {{ t('batch.cancel') }}
      </Button>

      <span class="mx-1 h-5 w-px bg-border" aria-hidden="true" />

      <Button size="sm" variant="ghost" data-testid="batch-add-row" @click="batch.addRow()">
        <Plus /> {{ t('batch.add_row') }}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        :disabled="selectedRows.length === 0"
        data-testid="batch-remove-rows"
        @click="batch.removeRows(selectedRows)"
      >
        <Trash2 /> {{ t('batch.remove_rows') }}
      </Button>
      <Button size="sm" variant="ghost" data-testid="batch-import" @click="fileInput?.click()">
        <Upload /> {{ t('batch.import') }}
      </Button>
      <Button size="sm" variant="ghost" data-testid="batch-paste" @click="pasteOpen = !pasteOpen">
        {{ t('batch.paste') }}
      </Button>
      <input
        ref="fileInput"
        type="file"
        accept=".csv,.ecsv,.tsv,.txt,.json"
        class="hidden"
        data-testid="batch-file"
        @change="importFile"
      />

      <span class="flex-1" />

      <label class="flex items-center gap-1 text-xs text-muted-foreground">
        <input v-model="batch.continueOnError" type="checkbox" data-testid="batch-continue" />
        {{ t('batch.continue_on_error') }}
      </label>
      <Button size="sm" variant="ghost" data-testid="batch-save-layout" @click="batch.saveLayout()">
        <Save /> {{ t('batch.save_layout') }}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        :disabled="!batch.results"
        data-testid="batch-export-csv"
        @click="download('csv')"
      >
        <Download /> CSV
      </Button>
      <Button
        size="sm"
        variant="ghost"
        :disabled="!batch.results"
        data-testid="batch-export-ecsv"
        @click="download('ecsv')"
      >
        <Download /> ECSV
      </Button>
    </div>

    <div v-if="pasteOpen" class="shrink-0 border-b p-2">
      <textarea
        v-model="pasteText"
        class="h-24 w-full rounded-md border bg-background p-2 font-mono text-xs"
        :placeholder="t('batch.paste_hint')"
        data-testid="batch-paste-area"
      />
      <div class="mt-1 flex gap-1">
        <Button size="sm" data-testid="batch-paste-apply" @click="applyPaste">
          {{ t('batch.paste_apply') }}
        </Button>
        <Button size="sm" variant="ghost" @click="pasteOpen = false">
          {{ t('common.cancel') }}
        </Button>
      </div>
    </div>

    <div class="flex min-h-0 flex-1 flex-col gap-2 overflow-auto p-2">
      <section>
        <h2 class="mb-1 text-xs font-medium text-muted-foreground">
          {{ t('batch.collect_title') }}
        </h2>
        <div class="flex flex-wrap gap-1" data-testid="batch-collect">
          <button
            v-for="ref in outputRefs"
            :key="ref"
            type="button"
            class="rounded-full border px-2 py-0.5 text-xs"
            :class="
              batch.collect.includes(ref)
                ? 'border-primary bg-primary/10 text-primary'
                : 'text-muted-foreground'
            "
            :aria-pressed="batch.collect.includes(ref)"
            :data-testid="`batch-collect-${ref}`"
            @click="toggleCollect(ref)"
          >
            {{ ref }}
          </button>
          <span v-if="outputRefs.length === 0" class="text-xs text-muted-foreground">
            {{ t('batch.no_outputs') }}
          </span>
        </div>
      </section>

      <section class="min-h-0">
        <h2 class="mb-1 text-xs font-medium text-muted-foreground">
          {{ t('batch.rows_title', { n: batch.rowCount }) }}
        </h2>
        <div class="overflow-auto rounded-md border">
          <table class="w-full border-collapse text-xs" data-testid="batch-table">
            <thead class="bg-muted/50">
              <tr>
                <th class="w-8 p-1"></th>
                <th class="w-24 p-1 text-left font-medium">{{ t('batch.status') }}</th>
                <th v-for="column in batch.columns" :key="column" class="p-1 text-left">
                  <div class="flex flex-col gap-0.5">
                    <span class="font-medium">{{ column }}</span>
                    <select
                      class="rounded border bg-background px-1 py-0.5 text-[10px]"
                      :value="batch.mapping[column] ?? ''"
                      :data-testid="`batch-map-${column}`"
                      @change="
                        batch.setMapping(column, ($event.target as HTMLSelectElement).value || null)
                      "
                    >
                      <option value="">{{ t('batch.unmapped') }}</option>
                      <option v-for="ref in refs" :key="ref" :value="ref">{{ ref }}</option>
                    </select>
                  </div>
                </th>
                <th class="w-8 p-1"></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(row, index) in batch.rows"
                :key="index"
                class="border-t"
                :data-testid="`batch-row-${index}`"
                :data-state="batch.stateOf(index).state"
              >
                <td class="p-1 text-center">
                  <input
                    type="checkbox"
                    :checked="batch.selected.has(index)"
                    :aria-label="t('batch.select_row', { row: index + 1 })"
                    :data-testid="`batch-select-${index}`"
                    @change="batch.toggleSelected(index)"
                  />
                </td>
                <td class="p-1">
                  <span
                    class="inline-block rounded-full px-1.5 py-0.5 text-[10px]"
                    :class="{
                      'bg-muted text-muted-foreground': batch.stateOf(index).state === 'pending',
                      'bg-amber-500/15 text-amber-600': ['running', 'queued'].includes(
                        batch.stateOf(index).state,
                      ),
                      'bg-emerald-500/15 text-emerald-600': batch.stateOf(index).state === 'done',
                      'bg-destructive/15 text-destructive': batch.stateOf(index).state === 'error',
                      'bg-slate-500/15 text-slate-500': batch.stateOf(index).state === 'cancelled',
                    }"
                    :title="batch.stateOf(index).error ?? undefined"
                    :data-testid="`batch-pill-${index}`"
                  >
                    {{ t(`batch.state.${batch.stateOf(index).state}`) }}
                  </span>
                </td>
                <td v-for="column in batch.columns" :key="column" class="p-0.5">
                  <input
                    class="w-full rounded border-transparent bg-transparent px-1 py-0.5 hover:border-input focus:border-input focus:outline-none"
                    :value="cellValue(index, column)"
                    :aria-label="`${column} ${index + 1}`"
                    :data-testid="`batch-cell-${index}-${column}`"
                    @change="onCell(index, column, $event)"
                  />
                </td>
                <td class="p-1">
                  <button
                    type="button"
                    class="text-muted-foreground hover:text-foreground"
                    :title="t('batch.open_in_canvas')"
                    :data-testid="`batch-open-${index}`"
                    @click="openRow(index)"
                  >
                    <ExternalLink class="size-3.5" />
                  </button>
                </td>
              </tr>
              <tr v-if="batch.rowCount === 0">
                <td colspan="99" class="p-3 text-center text-muted-foreground">
                  {{ t('batch.empty') }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="batch.results" class="min-h-0">
        <h2 class="mb-1 text-xs font-medium text-muted-foreground">
          {{ t('batch.results_title') }}
        </h2>
        <div class="overflow-auto rounded-md border">
          <table class="w-full border-collapse text-xs" data-testid="batch-results">
            <thead class="bg-muted/50">
              <tr>
                <th v-for="column in resultColumns" :key="column" class="p-1 text-left font-medium">
                  {{ column }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(row, index) in batch.results.rows"
                :key="index"
                class="border-t"
                :data-testid="`batch-result-${index}`"
              >
                <td v-for="column in resultColumns" :key="column" class="p-1">
                  {{ row[column] === null || row[column] === undefined ? '' : row[column] }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <p v-if="batch.error" class="text-xs text-destructive" data-testid="batch-error">
        {{ batch.error }}
      </p>
    </div>
  </div>
</template>
