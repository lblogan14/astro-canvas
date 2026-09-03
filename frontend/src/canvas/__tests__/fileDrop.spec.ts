import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { api } from '@/api/client'
import type { NodeSpec } from '@/api/types'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'
import { SPECS, mathChain } from '@/stores/__tests__/fixtures'

import {
  FALLBACK_LOADER,
  addLoaderNode,
  addUploadedFiles,
  pickLoader,
  setFileDropTranslator,
} from '../fileDrop'

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return {
    ...original,
    api: {
      sniffWorkspaceFile: vi.fn<typeof original.api.sniffWorkspaceFile>(),
      uploadWorkspaceFile: vi.fn<typeof original.api.uploadWorkspaceFile>(),
      getWorkspaceTree: vi.fn<typeof original.api.getWorkspaceTree>(),
      putWorkflow: vi.fn<typeof original.api.putWorkflow>(),
    },
  }
})

const mocked = vi.mocked(api)

function loader(id: string, name: string): NodeSpec {
  const base = SPECS[0] as NodeSpec
  return {
    ...base,
    id,
    name,
    category: 'Data/Load',
    inputs: [],
    outputs: [
      { name: 'out', type: 'astro.Spectrum1D', description: '', required: true, lazy: false },
    ],
    params: [
      {
        name: 'path',
        label: 'File',
        description: '',
        json_schema: { type: 'string', default: '' },
        required: false,
        default: '',
        widget: 'file',
        unit: null,
        step: null,
        advanced: false,
        linkable: true,
        link_type: 'astro.Str',
      },
    ],
  }
}

describe('fileDrop', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    for (const fn of Object.values(mocked)) fn.mockReset()
    mocked.getWorkspaceTree.mockResolvedValue({ path: 'uploads', entries: [] })
    const schema = useNodesSchemaStore()
    schema.specs = [
      ...SPECS,
      loader('core.io.load_spectrum', 'Load Spectrum'),
      loader(FALLBACK_LOADER, 'Load Table'),
    ]
    setFileDropTranslator((key, params) => `${key}:${JSON.stringify(params ?? {})}`)
  })

  it('picks the loader from the server sniff and falls back to the table loader', async () => {
    mocked.sniffWorkspaceFile.mockResolvedValueOnce({
      path: 'a.fits',
      kind: 'spectrum',
      node: 'core.io.load_spectrum',
      detail: '',
    })
    const pick = await pickLoader('a.fits')
    expect(pick?.spec.id).toBe('core.io.load_spectrum')
    expect(pick?.kind).toBe('spectrum')
    expect(pick?.fallback).toBe(false)

    mocked.sniffWorkspaceFile.mockResolvedValueOnce({
      path: 'x.md',
      kind: 'unknown',
      node: null,
      detail: '',
    })
    const unknown = await pickLoader('x.md')
    expect(unknown?.spec.id).toBe(FALLBACK_LOADER)
    expect(unknown?.fallback).toBe(true)

    mocked.sniffWorkspaceFile.mockRejectedValueOnce(new Error('offline'))
    const failed = await pickLoader('y.fits')
    expect(failed?.spec.id).toBe(FALLBACK_LOADER)

    mocked.sniffWorkspaceFile.mockResolvedValueOnce({
      path: 'c.fits',
      kind: 'cube',
      node: 'core.io.load_cube',
      detail: '',
    })
    const missing = await pickLoader('c.fits') // load_cube is not installed here → table fallback
    expect(missing?.spec.id).toBe(FALLBACK_LOADER)
    expect(missing?.fallback).toBe(true)

    useNodesSchemaStore().specs = SPECS
    mocked.sniffWorkspaceFile.mockResolvedValueOnce({
      path: 'a',
      kind: 'unknown',
      node: null,
      detail: '',
    })
    expect(await pickLoader('a')).toBeNull()
  })

  it('adds a loader node with the path set and notifies', async () => {
    const workflow = useWorkflowStore()
    const ui = useUiStore()
    expect(await addLoaderNode('a.fits', [0, 0])).toBeNull() // no workflow open
    workflow.load(mathChain())
    const before = workflow.nodeCount
    mocked.sniffWorkspaceFile.mockResolvedValueOnce({
      path: 'samples/a.fits',
      kind: 'spectrum',
      node: 'core.io.load_spectrum',
      detail: '',
    })
    const id = await addLoaderNode('samples/a.fits', [10, 20])
    expect(id).not.toBeNull()
    const node = workflow.nodes[id as string]
    expect(node?.type).toBe('core.io.load_spectrum')
    expect(node?.params?.['path']).toBe('samples/a.fits')
    expect(node?.title).toBe('a.fits')
    expect(node?.pos).toEqual([10, 20])
    expect(workflow.nodeCount).toBe(before + 1)
    expect(ui.toast?.kind).toBe('info')
    expect(ui.toast?.message).toContain('workspace.added_node')

    mocked.sniffWorkspaceFile.mockResolvedValueOnce({
      path: 'n.md',
      kind: 'unknown',
      node: null,
      detail: '',
    })
    await addLoaderNode('n.md', [0, 0])
    expect(ui.toast?.kind).toBe('error')
    expect(ui.toast?.message).toContain('workspace.unknown_kind')
  })

  it('uploads OS files, then stacks one loader per stored file', async () => {
    const workflow = useWorkflowStore()
    workflow.load(mathChain())
    mocked.uploadWorkspaceFile.mockImplementation(async (file) => {
      if (file.name === 'bad.txt') throw new Error('409')
      return {
        upload_id: null,
        received: file.size,
        complete: true,
        file: { path: `uploads/${file.name}`, name: file.name, size: file.size, mtime: 0 },
      }
    })
    mocked.sniffWorkspaceFile.mockResolvedValue({
      path: 'x',
      kind: 'spectrum',
      node: 'core.io.load_spectrum',
      detail: '',
    })
    const ids = await addUploadedFiles(
      [new File(['a'], 'one.dat'), new File(['b'], 'bad.txt'), new File(['c'], 'two.dat')],
      [100, 100],
    )
    expect(ids).toHaveLength(2)
    expect(workflow.nodes[ids[0] as string]?.pos).toEqual([100, 100])
    expect(workflow.nodes[ids[1] as string]?.pos).toEqual([100, 320])
    expect(workflow.nodes[ids[1] as string]?.params?.['path']).toBe('uploads/two.dat')
  })
})
