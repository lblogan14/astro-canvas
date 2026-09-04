import { describe, expect, it } from 'vitest'

import type { BundleImportResult, ImportedInput } from '@/api/types'
import { bundleFrom, importNotices, isBundleFile } from '../importBundle'

function input(status: ImportedInput['status'], ref = 'load.path'): ImportedInput {
  return {
    param_ref: ref,
    path: 'samples/sdss1.fits',
    status,
    expected_blake3: null,
    actual_blake3: null,
  }
}

function result(overrides: Partial<BundleImportResult> = {}): BundleImportResult {
  return {
    workflow_id: 'wf1',
    name: 'Absorption',
    lock: {
      app_version: '0.1.0',
      python: '3.12.0',
      platform: 'linux-x86_64',
      packs: {},
      requirements: [],
      created: '2026-09-04T00:00:00',
    },
    missing_packs: {},
    layout_errors: [],
    inputs: [],
    outputs_restored: 0,
    quarantined: false,
    snippets: [],
    warnings: [],
    ...overrides,
  }
}

/** vue-i18n's `t` in the shape the module is handed: a key plus params or a plural count. */
const t = (key: string, params?: Record<string, unknown> | number) =>
  typeof params === 'number' ? `${key}:${params}` : `${key}:${JSON.stringify(params ?? {})}`

describe('isBundleFile', () => {
  it.each(['workflow.acw', 'Absorption.ACW'])('accepts %s', (name) => {
    expect(isBundleFile({ name })).toBe(true)
  })
  it.each(['data.fits', 'workflow.json', 'acw'])('rejects %s', (name) => {
    expect(isBundleFile({ name })).toBe(false)
  })
})

describe('bundleFrom', () => {
  it('picks the first bundle out of a mixed drop', () => {
    const files = [{ name: 'a.fits' }, { name: 'b.acw' }, { name: 'c.acw' }] as unknown as File[]
    expect(bundleFrom(files)?.name).toBe('b.acw')
  })

  it('returns null when the drop has no bundle', () => {
    expect(bundleFrom([{ name: 'a.fits' }] as unknown as File[])).toBeNull()
    expect(bundleFrom(null)).toBeNull()
  })
})

describe('importNotices', () => {
  it('always ends with the "imported" message', () => {
    const notices = importNotices(result(), t)
    expect(notices.at(-1)).toEqual({
      message: 'bundle.imported:{"name":"Absorption"}',
      kind: 'info',
    })
  })

  it('reports missing packs first, as an error', () => {
    const notices = importNotices(result({ missing_packs: { 'astro-canvas-rbcodes': '>=0.1' } }), t)
    expect(notices[0]).toEqual({
      message: 'bundle.missing_packs:{"names":"astro-canvas-rbcodes"}',
      kind: 'error',
    })
  })

  it('counts missing, changed and restored inputs separately', () => {
    const notices = importNotices(
      result({
        inputs: [
          input('missing'),
          input('hash_mismatch', 'a.path'),
          input('restored', 'b.path'),
          input('ok', 'c.path'),
        ],
      }),
      t,
    )
    const messages = notices.map((n) => n.message)
    expect(messages).toContain('bundle.missing_inputs:1')
    expect(messages).toContain('bundle.hash_mismatch:1')
    expect(messages).toContain('bundle.restored_inputs:1')
  })

  it('says nothing about inputs that arrived intact', () => {
    const notices = importNotices(result({ inputs: [input('ok')] }), t)
    expect(notices).toHaveLength(1)
  })
})
