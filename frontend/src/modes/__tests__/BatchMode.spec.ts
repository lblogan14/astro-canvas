import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'

import { createI18n } from 'vue-i18n'
import en from '@/i18n/locales/en.json'
import BatchMode from '@/modes/BatchMode.vue'
import {
  SPECGUI_COLUMNS,
  looksLikeSpecgui,
  parseDelimited,
  parseSpecguiBatch,
  splitLine,
  suggestMapping,
  toCsv,
  toEcsv,
} from '@/modes/batchTable'
import { useBatchStore } from '@/stores/batch'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useWorkflowStore } from '@/stores/workflow'
import { SPECS, TYPES, mathChain } from '@/stores/__tests__/fixtures'

type AnyFn = (...args: unknown[]) => unknown
const startBatch = vi.fn<AnyFn>()
const getBatch = vi.fn<AnyFn>()
const cancelBatch = vi.fn<AnyFn>()

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return {
    ...original,
    api: {
      putWorkflow: vi.fn<AnyFn>(),
      startBatch: (...args: unknown[]) => startBatch(...args),
      getBatch: (...args: unknown[]) => getBatch(...args),
      cancelBatch: (...args: unknown[]) => cancelBatch(...args),
    },
  }
})

const SPECGUI_CSV = [
  'filename,redshift,transition,transition_name,slice_vmin,slice_vmax,ew_vmin,ew_vmax,linelist,method',
  'samples/a.fits,1.3855,2796.35,MgII 2796,-1500,1500,-200,200,atom,closest',
  'samples/b.fits,0.348,1215.67,HI 1215,-1000,1000,-150,150,atom,closest',
].join('\n')

function setup() {
  setActivePinia(createPinia())
  const schema = useNodesSchemaStore()
  schema.specs = SPECS
  schema.types = TYPES
  schema.status = 'ready'
  const workflow = useWorkflowStore()
  workflow.autosaveEnabled = false
  workflow.load(mathChain())
  const batch = useBatchStore()
  return { workflow, batch }
}

function mountMode() {
  const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })
  return mount(BatchMode, { global: { plugins: [i18n] } })
}

describe('batch table parsing', () => {
  it('splits quoted fields and doubled quotes', () => {
    expect(splitLine('a,"b,c","say ""hi"""')).toEqual(['a', 'b,c', 'say "hi"'])
  })

  it('reads CSV, TSV and ECSV with typed cells', () => {
    const table = parseDelimited('x,y,ok\n1,2.5,true\n3,,false\n')
    expect(table.columns).toEqual(['x', 'y', 'ok'])
    expect(table.rows[0]).toEqual({ x: 1, y: 2.5, ok: true })
    expect(table.rows[1]).toEqual({ x: 3, y: null, ok: false })
    expect(parseDelimited('a\tb\n1\t2\n').columns).toEqual(['a', 'b'])
    const ecsv = parseDelimited('# %ECSV 1.0\n# ---\n# datatype:\nx,y\n1,2\n')
    expect(ecsv.rows).toEqual([{ x: 1, y: 2 }])
  })

  it('writes CSV and an ECSV header with inferred datatypes', () => {
    const rows = [{ name: 'a,b', W: 1.5, n: 2, ok: true }]
    expect(toCsv(['name', 'W'], rows)).toBe('name,W\n"a,b",1.5\n')
    const ecsv = toEcsv(['name', 'W', 'n', 'ok'], rows)
    expect(ecsv).toContain('# %ECSV 1.0')
    expect(ecsv).toContain('{name: W, datatype: float64}')
    expect(ecsv).toContain('{name: n, datatype: int64}')
    expect(ecsv).toContain('{name: ok, datatype: bool}')
  })
})

describe('specgui batch import', () => {
  it('recognises the CSV template', () => {
    const table = parseSpecguiBatch(SPECGUI_CSV)
    expect(table).not.toBeNull()
    expect(table!.rows).toHaveLength(2)
    expect(table!.rows[0]?.['slice_vmin']).toBe(-1500)
    expect(table!.rows[0]?.['ew_vmin']).toBe(-200)
    expect(looksLikeSpecgui(table!.columns)).toBe(true)
  })

  it('recognises the master_batch_table JSON export', () => {
    const payload = JSON.stringify({
      metadata: { version: '1.0' },
      dataframe: [
        { filename: 'a.fits', redshift: 1.0, transition: 2796.35, slice_vmin: -1200, W: 2.1 },
      ],
    })
    const table = parseSpecguiBatch(payload)
    expect(table?.rows[0]?.['W']).toBe(2.1)
    expect(table?.columns).toContain('slice_vmin')
  })

  it('rejects a table that is not a specgui export', () => {
    expect(parseSpecguiBatch('a,b\n1,2\n')).toBeNull()
    expect(parseSpecguiBatch('{')).toBeNull()
  })

  it('maps specgui columns onto the nodes of the open document', () => {
    const nodes = {
      load: { type: 'core.io.load_spectrum', params: { path: '' } },
      z: { type: 'rbcodes.absorption.set_redshift', params: { z: 0 } },
      tr: { type: 'rbcodes.absorption.set_transition', params: { wrest: 0 } },
      cut: { type: 'rbcodes.absorption.slice', params: { vmin: 0, vmax: 0 } },
      ew: { type: 'rbcodes.absorption.compute_ew', params: { vmin: 0, vmax: 0 } },
    }
    const mapping = suggestMapping(Object.keys(SPECGUI_COLUMNS), nodes as never)
    expect(mapping['filename']).toBe('load.path')
    expect(mapping['redshift']).toBe('z.z')
    // The two velocity windows stay apart, as in specgui.
    expect(mapping['slice_vmin']).toBe('cut.vmin')
    expect(mapping['ew_vmin']).toBe('ew.vmin')
  })

  it('never binds a specgui result column', () => {
    const mapping = suggestMapping(['W', 'logN', 'calculation_timestamp'], {} as never)
    expect(mapping).toEqual({})
  })
})

describe('batch store', () => {
  beforeEach(() => {
    startBatch.mockReset()
    getBatch.mockReset()
    cancelBatch.mockReset()
  })

  it('imports a specgui table and reports the preset', () => {
    const { batch } = setup()
    const result = batch.importText(SPECGUI_CSV)
    expect(result).toEqual({ rows: 2, preset: true })
    expect(batch.columns).toContain('ew_vmax')
  })

  it('edits rows and columns', () => {
    const { batch } = setup()
    batch.setTable({ columns: ['x'], rows: [{ x: 1 }] })
    batch.addRow({ x: 5 })
    expect(batch.rowCount).toBe(2)
    batch.setCell(1, 'x', 7)
    expect(batch.rows[1]).toEqual({ x: 7 })
    batch.addColumn('y', 'sum.z')
    expect(batch.mapping['y']).toBe('sum.z')
    expect(batch.rows[0]).toEqual({ x: 1, y: null })
    batch.removeColumn('y')
    expect(batch.mapping['y']).toBeUndefined()
    batch.removeRows([0])
    expect(batch.rowCount).toBe(1)
  })

  it('builds a spec from the mapping and posts the rows', async () => {
    const { batch } = setup()
    batch.setTable({ columns: ['value'], rows: [{ value: 2 }, { value: 3 }] }, false)
    batch.setMapping('value', 'c.value')
    batch.collect = ['sum.out']
    startBatch.mockResolvedValue({ batch_id: 'b1', results: { columns: [], rows: [] } })
    await batch.run()
    expect(startBatch).toHaveBeenCalledWith('sample-math-chain', {
      rows: [{ value: 2 }, { value: 3 }],
      spec: {
        bindings: [{ node: 'c', param: 'value', column: 'value' }],
        collect: [{ node: 'sum', port: 'out', prefix: null }],
        max_workers: null,
        continue_on_error: true,
      },
    })
    expect(batch.batchId).toBe('b1')
    expect(batch.isRunning).toBe(true)
  })

  it('maps row events of a partial run back to the table rows', async () => {
    const { batch } = setup()
    batch.setTable({ columns: ['value'], rows: [{ value: 1 }, { value: 2 }, { value: 3 }] }, false)
    batch.setMapping('value', 'c.value')
    batch.collect = ['sum.out']
    startBatch.mockResolvedValue({ batch_id: 'b2', results: { columns: [], rows: [] } })
    getBatch.mockResolvedValue({ results: { columns: ['value'], rows: [{ value: 9 }] } })
    await batch.run([2])

    batch.applyMessage({
      type: 'batch.row',
      ts: 0,
      workflow_id: 'w',
      batch_id: 'b2',
      row: 0,
      state: 'done',
      error: null,
      elapsed_ms: 12,
      outputs: { value: 9 },
    })
    expect(batch.stateOf(2).state).toBe('done')
    expect(batch.stateOf(0).state).toBe('pending')
    expect(batch.counts).toEqual({ pending: 2, done: 1 })

    batch.applyMessage({
      type: 'batch.finished',
      ts: 0,
      workflow_id: 'w',
      batch_id: 'b2',
      n_rows: 1,
      done: 1,
      failed: 0,
      cancelled: 0,
      status: 'done',
      elapsed_ms: 20,
    })
    expect(batch.status).toBe('done')
    await Promise.resolve()
    await Promise.resolve()
    expect(batch.results?.rows?.[0]).toEqual({ value: 9 })
  })

  it('applies a row to the canvas for inspection', () => {
    const { batch, workflow } = setup()
    batch.setTable({ columns: ['value', 'note'], rows: [{ value: 42, note: 'x' }] }, false)
    batch.setMapping('value', 'c.value')
    expect(batch.openInCanvas(0)).toBe(true)
    expect(workflow.nodes['c']?.params?.['value']).toBe(42)
    expect(batch.openInCanvas(9)).toBe(false)
  })

  it('round-trips the layout through the document', () => {
    const { batch, workflow } = setup()
    batch.setTable({ columns: ['value'], rows: [{ value: 1 }] }, false)
    batch.setMapping('value', 'c.value')
    batch.collect = ['sum.out']
    batch.saveLayout()
    expect(workflow.doc?.layouts?.['batch']).toMatchObject({
      columns: [{ promoted: 'c.value', column: 'value' }],
      collect: ['sum.out'],
    })

    batch.setTable({ columns: [], rows: [] }, false)
    expect(batch.loadLayout()).toBe(true)
    expect(batch.columns).toEqual(['value'])
    expect(batch.mapping['value']).toBe('c.value')
    expect(batch.collect).toEqual(['sum.out'])
  })
})

describe('BatchMode.vue', () => {
  it('renders rows with status pills and disables Run without a collect', async () => {
    const { batch } = setup()
    batch.setTable({ columns: ['value'], rows: [{ value: 1 }, { value: 2 }] }, false)
    batch.setMapping('value', 'c.value')
    const wrapper = mountMode()
    expect(wrapper.findAll('[data-testid^="batch-row-"]')).toHaveLength(2)
    expect(wrapper.get('[data-testid="batch-run"]').attributes('disabled')).toBeDefined()

    batch.collect = ['sum.out']
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[data-testid="batch-run"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('[data-testid="batch-pill-0"]').text()).toBe('Pending')

    batch.applyMessage({
      type: 'batch.row',
      ts: 0,
      workflow_id: 'w',
      batch_id: null as unknown as string,
      row: 1,
      state: 'error',
      error: 'boom',
      elapsed_ms: 1,
      outputs: {},
    })
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[data-testid="batch-row-1"]').attributes('data-state')).toBe('error')
    expect(wrapper.get('[data-testid="batch-pill-1"]').attributes('title')).toBe('boom')
  })

  it('edits a cell and binds a column through the header select', async () => {
    const { batch } = setup()
    batch.setTable({ columns: ['value'], rows: [{ value: 1 }] }, false)
    const wrapper = mountMode()
    const cell = wrapper.get('[data-testid="batch-cell-0-value"]')
    await cell.setValue('8')
    await cell.trigger('change')
    expect(batch.rows[0]).toEqual({ value: '8' })

    const select = wrapper.get('[data-testid="batch-map-value"]')
    await select.setValue('c.value')
    expect(batch.mapping['value']).toBe('c.value')
  })

  it('toggles a collected output', async () => {
    const { batch } = setup()
    batch.setTable({ columns: ['value'], rows: [{ value: 1 }] }, false)
    const wrapper = mountMode()
    await wrapper.get('[data-testid="batch-collect-sum.out"]').trigger('click')
    expect(batch.collect).toEqual(['sum.out'])
    await wrapper.get('[data-testid="batch-collect-sum.out"]').trigger('click')
    expect(batch.collect).toEqual([])
  })
})
