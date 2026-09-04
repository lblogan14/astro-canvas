/**
 * Batch table I/O: CSV/ECSV parsing and writing, clipboard paste, and the rbcodes `specgui`
 * batch schema (`GUIs/specgui/batch/master_batch_table.py`) as an import preset.
 *
 * A batch row is a flat record of cell values; the column *mapping* says which node param each
 * column feeds. Values stay strings until `coerceCell` widens them, so a pasted table survives a
 * round trip even when a column holds JSON (continuum masks) or a boolean.
 */
import type { NodeDoc } from '@/api/types'

export type Cell = string | number | boolean | null
export type Row = Record<string, Cell>

export interface ParsedTable {
  columns: string[]
  rows: Row[]
}

// --- CSV / ECSV ---------------------------------------------------------------------------------

/** Split one delimited line, honouring `"` quoting and doubled quotes. */
export function splitLine(line: string, delimiter = ','): string[] {
  const out: string[] = []
  let field = ''
  let quoted = false
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i]
    if (quoted) {
      if (ch === '"') {
        if (line[i + 1] === '"') {
          field += '"'
          i += 1
        } else quoted = false
      } else field += ch
    } else if (ch === '"') quoted = true
    else if (ch === delimiter) {
      out.push(field)
      field = ''
    } else field += ch
  }
  out.push(field)
  return out
}

function guessDelimiter(line: string): string {
  const counts = [',', '\t', ';'].map((d) => [d, splitLine(line, d).length] as const)
  const best = counts.reduce((a, b) => (b[1] > a[1] ? b : a))
  return best[1] > 1 ? best[0] : ','
}

/** Turn a cell string into a number/boolean/null where that is unambiguous. */
export function coerceCell(raw: string): Cell {
  const value = raw.trim()
  if (value === '') return null
  if (value === 'true' || value === 'True') return true
  if (value === 'false' || value === 'False') return false
  if (/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(value)) return Number(value)
  return value
}

/**
 * Parse CSV, TSV or ECSV. ECSV's `#`-prefixed YAML header is skipped: its body is plain CSV with
 * a header row, which is all a batch table needs.
 */
export function parseDelimited(text: string): ParsedTable {
  const lines = text
    .split(/\r?\n/)
    .filter((line) => line.trim() !== '' && !line.trimStart().startsWith('#'))
  const header = lines[0]
  if (!header) return { columns: [], rows: [] }
  const delimiter = guessDelimiter(header)
  const columns = splitLine(header, delimiter).map((name) => name.trim())
  const rows: Row[] = []
  for (const line of lines.slice(1)) {
    const cells = splitLine(line, delimiter)
    const row: Row = {}
    columns.forEach((name, index) => {
      row[name] = coerceCell(cells[index] ?? '')
    })
    rows.push(row)
  }
  return { columns, rows }
}

function csvCell(value: Cell): string {
  if (value === null || value === undefined) return ''
  const text = String(value)
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

export function toCsv(columns: readonly string[], rows: readonly Row[]): string {
  const lines = [columns.map(csvCell).join(',')]
  for (const row of rows) lines.push(columns.map((name) => csvCell(row[name] ?? null)).join(','))
  return `${lines.join('\n')}\n`
}

function ecsvType(columns: readonly string[], rows: readonly Row[], name: string): string {
  const values = rows.map((row) => row[name]).filter((v) => v !== null && v !== undefined)
  if (values.length && values.every((v) => typeof v === 'boolean')) return 'bool'
  if (values.length && values.every((v) => typeof v === 'number')) {
    return values.every((v) => Number.isInteger(v)) ? 'int64' : 'float64'
  }
  return 'string'
}

/** ECSV 1.0: a YAML datatype header in `#` comments followed by the CSV body. */
export function toEcsv(columns: readonly string[], rows: readonly Row[]): string {
  const header = [
    '# %ECSV 1.0',
    '# ---',
    '# datatype:',
    ...columns.map((name) => `# - {name: ${name}, datatype: ${ecsvType(columns, rows, name)}}`),
    '# schema: astropy-2.0',
  ]
  return `${header.join('\n')}\n${toCsv(columns, rows)}`
}

// --- specgui batch preset -----------------------------------------------------------------------

/** A specgui column and the node type + param it maps onto in the absorption template. */
export interface PresetTarget {
  type: string
  param: string
}

/**
 * rbcodes `master_batch_table` columns. `slice_vmin/vmax` (the velocity window that is sliced
 * out) and `ew_vmin/vmax` (the integration limits) stay separate columns, as in specgui.
 */
export const SPECGUI_COLUMNS: Readonly<Record<string, PresetTarget>> = {
  filename: { type: 'core.io.load_spectrum', param: 'path' },
  redshift: { type: 'rbcodes.absorption.set_redshift', param: 'z' },
  transition: { type: 'rbcodes.absorption.set_transition', param: 'wrest' },
  linelist: { type: 'rbcodes.absorption.set_transition', param: 'linelist' },
  method: { type: 'rbcodes.absorption.set_transition', param: 'method' },
  slice_vmin: { type: 'rbcodes.absorption.slice', param: 'vmin' },
  slice_vmax: { type: 'rbcodes.absorption.slice', param: 'vmax' },
  ew_vmin: { type: 'rbcodes.absorption.compute_ew', param: 'vmin' },
  ew_vmax: { type: 'rbcodes.absorption.compute_ew', param: 'vmax' },
  calculate_snr: { type: 'rbcodes.absorption.compute_ew', param: 'snr' },
  binsize: { type: 'rbcodes.absorption.compute_ew', param: 'binsize' },
  continuum_method: { type: 'rbcodes.continuum.fit', param: 'method' },
  continuum_order: { type: 'rbcodes.continuum.fit', param: 'order' },
  continuum_masks: { type: 'rbcodes.continuum.fit', param: 'masks' },
  optimize_cont: { type: 'rbcodes.continuum.fit', param: 'optimize_order' },
  use_weights: { type: 'rbcodes.continuum.fit', param: 'use_weights' },
}

/** Columns specgui writes as results, not inputs: they are imported but never bound. */
export const SPECGUI_RESULT_COLUMNS: ReadonlySet<string> = new Set([
  'W',
  'W_e',
  'N',
  'N_e',
  'logN',
  'logN_e',
  'vel_centroid',
  'vel_disp',
  'SNR',
  'processing_status',
  'error_message',
  'calculation_timestamp',
  'last_modified',
  'continuum_fit_params',
  'transition_name',
])

const SPECGUI_REQUIRED = ['filename', 'redshift', 'transition']

export function looksLikeSpecgui(columns: readonly string[]): boolean {
  return SPECGUI_REQUIRED.every((name) => columns.includes(name))
}

/**
 * Read a specgui batch export: either the CSV template or the JSON
 * `{metadata, dataframe: [...]}` written by `MasterBatchTable.to_dict`.
 */
export function parseSpecguiBatch(text: string): ParsedTable | null {
  const trimmed = text.trimStart()
  if (trimmed.startsWith('{')) {
    let payload: unknown
    try {
      payload = JSON.parse(trimmed)
    } catch {
      return null
    }
    const frame = (payload as { dataframe?: unknown }).dataframe
    if (!Array.isArray(frame)) return null
    const rows = frame as Row[]
    const columns: string[] = []
    for (const row of rows)
      for (const name of Object.keys(row)) {
        if (!columns.includes(name)) columns.push(name)
      }
    return looksLikeSpecgui(columns) ? { columns, rows } : null
  }
  const table = parseDelimited(text)
  return looksLikeSpecgui(table.columns) ? table : null
}

/**
 * Match a parsed table's columns to node params of the open document: a specgui column maps
 * through `SPECGUI_COLUMNS` to the first node of that type, and any other column maps to a node
 * param whose `"<node>.<param>"` ref or bare param name it matches.
 */
export function suggestMapping(
  columns: readonly string[],
  nodes: Readonly<Record<string, NodeDoc>>,
): Record<string, string> {
  const byType = new Map<string, string>()
  for (const [nodeId, node] of Object.entries(nodes)) {
    if (!byType.has(node.type)) byType.set(node.type, nodeId)
  }
  const paramRefs = new Map<string, string>()
  for (const [nodeId, node] of Object.entries(nodes)) {
    for (const param of Object.keys(node.params ?? {})) {
      const ref = `${nodeId}.${param}`
      paramRefs.set(ref, ref)
      if (!paramRefs.has(param)) paramRefs.set(param, ref)
    }
  }
  const mapping: Record<string, string> = {}
  for (const column of columns) {
    if (SPECGUI_RESULT_COLUMNS.has(column)) continue
    const preset = SPECGUI_COLUMNS[column]
    const nodeId = preset ? byType.get(preset.type) : undefined
    if (preset && nodeId) {
      mapping[column] = `${nodeId}.${preset.param}`
      continue
    }
    const direct = paramRefs.get(column)
    if (direct) mapping[column] = direct
  }
  return mapping
}
