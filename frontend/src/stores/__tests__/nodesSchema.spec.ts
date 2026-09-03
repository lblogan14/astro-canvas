import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { ApiError, api } from '@/api/client'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { SPECS, TYPES } from './fixtures'

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return {
    ...original,
    api: {
      getNodes: vi.fn<typeof original.api.getNodes>(),
      getTypes: vi.fn<typeof original.api.getTypes>(),
      getPacks: vi.fn<typeof original.api.getPacks>(),
    },
  }
})

const getNodes = vi.mocked(api.getNodes)
const getTypes = vi.mocked(api.getTypes)
const getPacks = vi.mocked(api.getPacks)

describe('nodesSchema store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    getNodes.mockReset()
    getTypes.mockReset()
    getPacks.mockReset()
  })

  it('loads nodes, types and packs and indexes them', async () => {
    getNodes.mockResolvedValue(SPECS)
    getTypes.mockResolvedValue(TYPES)
    getPacks.mockResolvedValue([])
    const schema = useNodesSchemaStore()
    expect(schema.status).toBe('idle')
    const pending = schema.load()
    expect(schema.status).toBe('loading')
    await pending
    expect(schema.isReady).toBe(true)
    expect(schema.spec('core.math.expr')?.name).toBe('expr')
    expect(schema.spec('nope')).toBeUndefined()
    expect(schema.portType('astro.Spectrum1D')?.compatible_with).toEqual([
      'astro.SpectrumCollection',
    ])
    expect(schema.compatible('astro.Float', 'astro.Json')).toBe(true)
    expect(schema.compatible('astro.Spectrum1D', 'astro.Float')).toBe(false)
  })

  it('builds a sorted category tree from slash-separated paths', async () => {
    getNodes.mockResolvedValue(SPECS)
    getTypes.mockResolvedValue(TYPES)
    getPacks.mockResolvedValue([])
    const schema = useNodesSchemaStore()
    await schema.load()
    const labels = schema.categories.map((c) => c.label)
    expect(labels).toEqual(['Lists', 'Math', 'Spectra', 'Utilities'])
    const spectra = schema.categories.find((c) => c.label === 'Spectra')!
    expect(spectra.nodes).toEqual([])
    expect(spectra.children.map((c) => c.path)).toEqual(['Spectra/Test', 'Spectra/Transform'])
    const math = schema.categories.find((c) => c.label === 'Math')!
    expect(math.nodes.map((n) => n.id)).toEqual(['core.math.constant', 'core.math.expr'])
  })

  it('lists node types accepting a given output type (inputs or linkable params)', async () => {
    getNodes.mockResolvedValue(SPECS)
    getTypes.mockResolvedValue(TYPES)
    getPacks.mockResolvedValue([])
    const schema = useNodesSchemaStore()
    await schema.load()
    expect(schema.acceptingInput('astro.Spectrum1D').map((s) => s.id)).toEqual([
      'core.spec.crop',
      'core.list.collect',
    ])
    const floats = schema.acceptingInput('astro.Float').map((s) => s.id)
    expect(floats).toContain('core.math.expr')
    expect(floats).toContain('core.list.collect') // via the astro.Any / astro.Json inputs
    expect(floats).toContain('core.spec.crop') // via its linkable Float params
    expect(schema.acceptingInput('astro.Bool').map((s) => s.id)).toEqual(['core.list.collect'])
  })

  it('records load errors', async () => {
    getNodes.mockRejectedValue(new ApiError(500, 'down'))
    getTypes.mockResolvedValue([])
    getPacks.mockResolvedValue([])
    const schema = useNodesSchemaStore()
    await schema.load()
    expect(schema.status).toBe('error')
    expect(schema.error).toBe('down')
    getNodes.mockRejectedValue('weird')
    await schema.load()
    expect(schema.error).toBe('weird')
  })
})
