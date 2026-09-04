<script setup lang="ts">
/**
 * Sortable data grid (TanStack Table v9) fed by Arrow IPC bytes (`tableFromIPC`) or by the JSON
 * `head` of a table summary. Rows render in windows of `pageSize` to keep large tables cheap.
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  type ColumnDef,
  type SortingState,
  createSortedRowModel,
  rowSortingFeature,
  sortFn_basic,
  tableFeatures,
  useTable,
} from '@tanstack/vue-table'
import { tableFromIPC } from 'apache-arrow'

export interface TableHead {
  columns: string[]
  rows: Record<string, unknown[]>
  units?: Record<string, string>
  dtypes?: Record<string, string>
  nRows?: number
}

type Row = Record<string, unknown>

const props = withDefaults(
  defineProps<{
    /** Arrow IPC stream (full table). */
    arrow?: ArrayBuffer | Uint8Array | null
    /** JSON head (first rows) when no Arrow buffer is available. */
    head?: TableHead | null
    units?: Record<string, string>
    pageSize?: number
    compact?: boolean
    /** Row indices highlighted by a linked selection (dashboard mode). */
    selectedRows?: number[]
  }>(),
  {
    arrow: null,
    head: null,
    units: () => ({}),
    pageSize: 200,
    compact: false,
    selectedRows: () => [],
  },
)

const emit = defineEmits<{ 'select-row': [index: number] }>()

const { t } = useI18n()
const sorting = ref<SortingState>([])
const shown = ref(props.pageSize)

interface Parsed {
  columns: string[]
  rows: Row[]
  total: number
}

function parseArrow(buffer: ArrayBuffer | Uint8Array): Parsed {
  const table = tableFromIPC(buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer))
  const columns = table.schema.fields.map((f) => f.name)
  const rows: Row[] = []
  for (let i = 0; i < table.numRows; i += 1) {
    const row = table.get(i)
    const record: Row = {}
    if (row) {
      const json = row.toJSON() as Record<string, unknown>
      for (const name of columns) record[name] = json[name]
    }
    rows.push(record)
  }
  return { columns, rows, total: table.numRows }
}

function parseHead(head: TableHead): Parsed {
  const length = Math.max(0, ...head.columns.map((c) => head.rows[c]?.length ?? 0))
  const rows: Row[] = []
  for (let i = 0; i < length; i += 1) {
    const record: Row = {}
    for (const name of head.columns) record[name] = head.rows[name]?.[i]
    rows.push(record)
  }
  return { columns: head.columns, rows, total: head.nRows ?? length }
}

const parsed = computed<Parsed>(() => {
  try {
    if (props.arrow) return parseArrow(props.arrow)
  } catch {
    // fall through to the JSON head
  }
  if (props.head) return parseHead(props.head)
  return { columns: [], rows: [], total: 0 }
})

const features = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns: { basic: sortFn_basic },
})
type Features = typeof features

const columns = computed<ColumnDef<Features, Row>[]>(() =>
  parsed.value.columns.map((name) => ({
    id: name,
    accessorFn: (row: Row) => row[name],
    header: () => (props.units[name] ? `${name} (${props.units[name]})` : name),
    sortFn: 'basic',
  })),
)
const data = computed(() => parsed.value.rows)

const table = useTable<Features, Row>({
  features,
  columns,
  data,
  state: computed(() => ({ sorting: sorting.value })),
  onSortingChange: (updater: SortingState | ((old: SortingState) => SortingState)) => {
    sorting.value = typeof updater === 'function' ? updater(sorting.value) : updater
  },
})

const rows = computed(() => {
  void sorting.value
  void data.value
  return table.getRowModel().rows
})
const visibleRows = computed(() => rows.value.slice(0, shown.value))
const selected = computed(() => new Set(props.selectedRows))
const hasMore = computed(() => rows.value.length > shown.value)
const headerGroups = computed(() => {
  void columns.value
  return table.getHeaderGroups()
})

function headerText(name: string): string {
  return props.units[name] ? `${name} (${props.units[name]})` : name
}

function format(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return 'NaN'
    if (Number.isInteger(value)) return String(value)
    const abs = Math.abs(value)
    return abs !== 0 && (abs < 1e-4 || abs >= 1e7)
      ? value.toExponential(4)
      : value.toPrecision(7).replace(/\.?0+$/, '')
  }
  if (typeof value === 'bigint') return value.toString()
  if (value instanceof Date) return value.toISOString()
  return String(value)
}

function toggleSort(columnId: string, event: MouseEvent): void {
  const column = table.getColumn(columnId)
  column?.getToggleSortingHandler()?.(event)
}

function sortState(columnId: string): 'ascending' | 'descending' | 'none' {
  const sorted = table.getColumn(columnId)?.getIsSorted()
  return sorted === 'asc' ? 'ascending' : sorted === 'desc' ? 'descending' : 'none'
}

watch(
  () => [props.arrow, props.head],
  () => {
    shown.value = props.pageSize
    sorting.value = []
  },
)
</script>

<template>
  <div class="flex h-full min-h-0 flex-col text-[11px]" data-widget="data-table">
    <div class="min-h-0 flex-1 overflow-auto">
      <table class="w-full border-collapse font-mono">
        <thead class="sticky top-0 bg-muted text-left">
          <tr v-for="group in headerGroups" :key="group.id">
            <th
              v-for="header in group.headers"
              :key="header.id"
              class="cursor-pointer border-b px-2 py-1 font-medium whitespace-nowrap select-none"
              :aria-sort="sortState(header.column.id)"
              @click="toggleSort(header.column.id, $event)"
            >
              {{ headerText(header.column.id) }}
              <span v-if="sortState(header.column.id) === 'ascending'" aria-hidden="true"> ▲</span>
              <span v-else-if="sortState(header.column.id) === 'descending'" aria-hidden="true">
                ▼</span
              >
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, position) in visibleRows"
            :key="row.id"
            class="odd:bg-muted/30 hover:bg-accent/40"
            :class="selected.has(position) ? 'bg-primary/15!' : ''"
            :data-row="position"
            :data-linked="selected.has(position) ? 'true' : undefined"
            :aria-selected="selected.has(position) ? 'true' : undefined"
            @click="emit('select-row', position)"
          >
            <td
              v-for="cell in row.getAllCells()"
              :key="cell.id"
              class="border-b border-border/50 px-2 whitespace-nowrap"
              :class="compact ? 'py-px' : 'py-0.5'"
            >
              {{ format(cell.getValue()) }}
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="!parsed.rows.length" class="p-3 text-muted-foreground">{{ t('widgets.no_data') }}</p>
    </div>
    <div class="flex h-6 items-center gap-2 border-t px-2 text-muted-foreground">
      <span data-testid="table-count">
        {{
          t('widgets.rows_shown', {
            shown: Math.min(shown, parsed.rows.length),
            total: parsed.total,
          })
        }}
      </span>
      <button
        v-if="hasMore"
        type="button"
        class="rounded border px-1.5 hover:bg-muted"
        @click="shown += pageSize"
      >
        {{ t('widgets.load_more') }}
      </button>
    </div>
  </div>
</template>
