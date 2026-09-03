import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { ApiError, api } from '@/api/client'
import type { WorkflowSummary } from '@/api/types'
import { useWorkflowsStore } from '@/stores/workflows'
import { mathChain } from './fixtures'

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return {
    ...original,
    api: {
      listWorkflows: vi.fn<typeof original.api.listWorkflows>(),
      deleteWorkflow: vi.fn<typeof original.api.deleteWorkflow>(),
      getWorkflow: vi.fn<typeof original.api.getWorkflow>(),
      createWorkflow: vi.fn<typeof original.api.createWorkflow>(),
      listVersions: vi.fn<typeof original.api.listVersions>(),
      getVersion: vi.fn<typeof original.api.getVersion>(),
      listTemplates: vi.fn<typeof original.api.listTemplates>(),
      instantiateTemplate: vi.fn<typeof original.api.instantiateTemplate>(),
    },
  }
})

const mocked = vi.mocked(api)

const summary = (id: string, name = id): WorkflowSummary => ({
  id,
  name,
  description: '',
  created: '2026-09-02T00:00:00',
  modified: '2026-09-02T00:00:00',
  node_count: 4,
  hash: 'h',
})

describe('workflows store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    for (const fn of Object.values(mocked)) fn.mockReset()
  })

  it('refreshes the list and records errors', async () => {
    mocked.listWorkflows.mockResolvedValueOnce([summary('a'), summary('b')])
    const store = useWorkflowsStore()
    const pending = store.refresh()
    expect(store.loading).toBe(true)
    await pending
    expect(store.items.map((w) => w.id)).toEqual(['a', 'b'])
    expect(store.loading).toBe(false)
    mocked.listWorkflows.mockRejectedValueOnce(new ApiError(500, 'nope'))
    await store.refresh()
    expect(store.error).toBe('nope')
    mocked.listWorkflows.mockRejectedValueOnce('odd')
    await store.refresh()
    expect(store.error).toBe('odd')
  })

  it('removes a workflow locally after the DELETE', async () => {
    mocked.listWorkflows.mockResolvedValue([summary('a'), summary('b')])
    mocked.deleteWorkflow.mockResolvedValue(undefined)
    const store = useWorkflowsStore()
    await store.refresh()
    await store.remove('a')
    expect(mocked.deleteWorkflow).toHaveBeenCalledWith('a')
    expect(store.items.map((w) => w.id)).toEqual(['b'])
  })

  it('duplicates under a fresh id with a "(copy)" name and refreshes', async () => {
    mocked.getWorkflow.mockResolvedValue(mathChain())
    mocked.createWorkflow.mockImplementation(async (doc) => ({ doc, node_errors: {} }))
    mocked.listWorkflows.mockResolvedValue([])
    const store = useWorkflowsStore()
    const id = await store.duplicate('sample-math-chain')
    expect(id).toMatch(/^wf_/)
    const sent = mocked.createWorkflow.mock.calls[0]![0]
    expect(sent.name).toBe('Math chain (copy)')
    expect(sent.meta).toEqual({})
    expect(sent.nodes?.c).toBeDefined()
    expect(mocked.listWorkflows).toHaveBeenCalled()
    await store.duplicate('sample-math-chain', 'Named')
    expect(mocked.createWorkflow.mock.calls[1]![0].name).toBe('Named')
  })

  it('loads and fetches versions', async () => {
    mocked.listVersions.mockResolvedValueOnce([{ id: 2, created: 'x', label: null }])
    mocked.getVersion.mockResolvedValue(mathChain())
    const store = useWorkflowsStore()
    await store.loadVersions('a')
    expect(store.versions.map((v) => v.id)).toEqual([2])
    const doc = await store.fetchVersion('a', 2)
    expect(doc.id).toBe('sample-math-chain')
    expect(mocked.getVersion).toHaveBeenCalledWith('a', 2)
    mocked.listVersions.mockRejectedValueOnce(new ApiError(404, 'missing'))
    await store.loadVersions('a')
    expect(store.versions).toEqual([])
    expect(store.error).toBe('missing')
  })

  it('lists templates and instantiates one into a new workflow', async () => {
    const store = useWorkflowsStore()
    mocked.listTemplates.mockResolvedValueOnce([
      {
        id: 'rbcodes.absorption-line-measurement',
        name: 'Absorption Line Measurement',
        description: 'MgII at z = 1.3855',
        pack: 'rbcodes',
        node_count: 9,
        file: 'absorption-line-measurement.acw',
        readme: '# Absorption',
      },
    ])
    await store.loadTemplates()
    expect(store.templates).toHaveLength(1)
    expect(store.templates[0]?.pack).toBe('rbcodes')
    const doc = { ...mathChain(), id: 'fresh-id', name: 'Absorption Line Measurement' }
    mocked.instantiateTemplate.mockResolvedValueOnce({ doc, node_errors: {} })
    mocked.listWorkflows.mockResolvedValueOnce([summary('fresh-id', doc.name)])
    const id = await store.instantiate('rbcodes.absorption-line-measurement')
    expect(id).toBe('fresh-id')
    expect(mocked.instantiateTemplate).toHaveBeenCalledWith(
      'rbcodes.absorption-line-measurement',
      null,
    )
    expect(store.items.map((w) => w.id)).toEqual(['fresh-id'])
    mocked.listTemplates.mockRejectedValueOnce(new ApiError(500, 'down'))
    await store.loadTemplates()
    expect(store.templates).toEqual([])
    expect(store.error).toBe('down')
  })
})
