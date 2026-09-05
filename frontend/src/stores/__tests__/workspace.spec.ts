import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { api } from '@/api/client'
import type { WorkspaceEntry, WorkspaceInfo, WorkspaceTree } from '@/api/types'
import { joinPath, parentOf, useWorkspaceStore } from '@/stores/workspace'

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return {
    ...original,
    api: {
      getWorkspace: vi.fn<typeof original.api.getWorkspace>(),
      getWorkspaceTree: vi.fn<typeof original.api.getWorkspaceTree>(),
      sniffWorkspaceFile: vi.fn<typeof original.api.sniffWorkspaceFile>(),
      makeWorkspaceDir: vi.fn<typeof original.api.makeWorkspaceDir>(),
      deleteWorkspacePath: vi.fn<typeof original.api.deleteWorkspacePath>(),
      selectWorkspace: vi.fn<typeof original.api.selectWorkspace>(),
      uploadWorkspaceFile: vi.fn<typeof original.api.uploadWorkspaceFile>(),
    },
  }
})

const mocked = vi.mocked(api)

const info: WorkspaceInfo = {
  root: 'C:/ws',
  name: 'ws',
  recent: ['C:/ws'],
  samples_dir: 'samples',
  downloads_dir: 'downloads',
  uploads_dir: 'uploads',
  shared_dir: null,
  can_select: true,
  available: true,
}

function entry(path: string, isDir = false): WorkspaceEntry {
  return {
    path,
    name: path.split('/').pop() ?? path,
    is_dir: isDir,
    size: isDir ? 0 : 10,
    mtime: 1,
    mime: isDir ? null : 'application/fits',
    children: null,
  }
}

const trees: Record<string, WorkspaceTree> = {
  '': { path: '', entries: [entry('samples', true), entry('uploads', true), entry('a.fits')] },
  samples: { path: 'samples', entries: [entry('samples/rbcodes', true)] },
  'samples/rbcodes': { path: 'samples/rbcodes', entries: [entry('samples/rbcodes/sdss1.fits')] },
  uploads: { path: 'uploads', entries: [] },
}

describe('workspace store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    for (const fn of Object.values(mocked)) fn.mockReset()
    mocked.getWorkspace.mockResolvedValue(info)
    mocked.getWorkspaceTree.mockImplementation(async (path = '') => {
      const tree = trees[path]
      if (!tree) throw new Error(`no such folder: ${path}`)
      return tree
    })
  })

  it('has path helpers', () => {
    expect(parentOf('a/b/c.fits')).toBe('a/b')
    expect(parentOf('c.fits')).toBe('')
    expect(joinPath('', 'x')).toBe('x')
    expect(joinPath('a', 'x')).toBe('a/x')
  })

  it('loads the root and expands folders lazily', async () => {
    const store = useWorkspaceStore()
    await store.load()
    expect(store.root).toBe('C:/ws')
    expect(store.rootName).toBe('ws')
    expect(store.entriesOf('')?.map((e) => e.name)).toEqual(['samples', 'uploads', 'a.fits'])
    expect(store.isLoaded('samples')).toBe(false)
    await store.expand('samples')
    expect(store.expanded.has('samples')).toBe(true)
    expect(store.entriesOf('samples')?.[0]?.path).toBe('samples/rbcodes')
    await store.toggle('samples')
    expect(store.expanded.has('samples')).toBe(false)
    await store.toggle('samples')
    expect(store.expanded.has('samples')).toBe(true)
    expect(mocked.getWorkspaceTree).toHaveBeenCalledTimes(2) // root + samples (cached on re-expand)
    store.select('a.fits')
    expect(store.selectedPath).toBe('a.fits')
  })

  it('refreshes parents of changed paths after a debounce and drops vanished folders', async () => {
    vi.useFakeTimers()
    try {
      const store = useWorkspaceStore()
      await store.load()
      await store.expand('samples')
      await store.expand('samples/rbcodes')
      mocked.getWorkspaceTree.mockClear()
      trees['samples'] = { path: 'samples', entries: [] } // rbcodes folder deleted
      store.applyChange(['samples/rbcodes/sdss1.fits', 'samples/rbcodes'])
      expect(mocked.getWorkspaceTree).not.toHaveBeenCalled()
      await vi.advanceTimersByTimeAsync(300)
      const refreshed = mocked.getWorkspaceTree.mock.calls.map((c) => c[0])
      expect(refreshed).toEqual(expect.arrayContaining(['samples']))
      await vi.advanceTimersByTimeAsync(10)
      expect(store.isLoaded('samples/rbcodes')).toBe(false)
    } finally {
      trees['samples'] = { path: 'samples', entries: [entry('samples/rbcodes', true)] }
      vi.useRealTimers()
    }
  })

  it('caches sniff results until the file changes', async () => {
    const store = useWorkspaceStore()
    mocked.sniffWorkspaceFile.mockResolvedValue({
      path: 'a.fits',
      kind: 'spectrum',
      node: 'core.io.load_spectrum',
      detail: '',
    })
    expect((await store.sniff('a.fits')).kind).toBe('spectrum')
    expect((await store.sniff('a.fits')).node).toBe('core.io.load_spectrum')
    expect(mocked.sniffWorkspaceFile).toHaveBeenCalledTimes(1)
    vi.useFakeTimers()
    store.applyChange(['a.fits'])
    await vi.advanceTimersByTimeAsync(300)
    vi.useRealTimers()
    await store.sniff('a.fits')
    expect(mocked.sniffWorkspaceFile).toHaveBeenCalledTimes(2)
  })

  it('tracks uploads with progress, success and failure', async () => {
    const store = useWorkspaceStore()
    await store.load()
    mocked.uploadWorkspaceFile.mockImplementation(async (file, options) => {
      options?.onProgress?.(3, 6)
      if (file.name === 'bad.fits') throw new Error('409 exists')
      return {
        upload_id: null,
        received: file.size,
        complete: true,
        file: { path: `uploads/${file.name}`, name: file.name, size: file.size, mtime: 1 },
      }
    })
    const files = [new File(['abcdef'], 'good.fits'), new File(['x'], 'bad.fits')]
    const jobs = await store.upload(files, 'uploads')
    expect(jobs.map((j) => j.state)).toEqual(['done', 'error'])
    expect(jobs[0]?.path).toBe('uploads/good.fits')
    expect(jobs[1]?.error).toContain('409')
    expect(store.uploads).toHaveLength(2)
    expect(store.uploads[0]?.loaded).toBe(6)
    expect(store.activeUploads).toHaveLength(0)
    expect(store.expanded.has('uploads')).toBe(true)
    store.clearUploads()
    expect(store.uploads).toHaveLength(0)
    expect(mocked.uploadWorkspaceFile.mock.calls[0]?.[1]?.onConflict).toBe('rename')
  })

  it('creates folders, removes paths and switches workspace', async () => {
    const store = useWorkspaceStore()
    await store.load()
    mocked.makeWorkspaceDir.mockResolvedValue(entry('uploads/new', true))
    await store.createFolder('uploads/new')
    expect(mocked.makeWorkspaceDir).toHaveBeenCalledWith('uploads/new')
    expect(mocked.getWorkspaceTree).toHaveBeenLastCalledWith('uploads', 1)

    store.select('a.fits')
    mocked.deleteWorkspacePath.mockResolvedValue(undefined)
    await store.remove('a.fits')
    expect(mocked.deleteWorkspacePath).toHaveBeenCalledWith('a.fits', false)
    expect(store.selectedPath).toBeNull()

    mocked.selectWorkspace.mockResolvedValue({ ...info, root: 'D:/other', name: 'other' })
    await store.expand('samples')
    const next = await store.switchWorkspace('D:/other', true)
    expect(next.name).toBe('other')
    expect(store.rootName).toBe('other')
    expect(store.expanded.has('samples')).toBe(false)
    expect(mocked.selectWorkspace).toHaveBeenCalledWith('D:/other', true)
  })

  it('records errors instead of throwing on load', async () => {
    mocked.getWorkspace.mockRejectedValue(new Error('offline'))
    const store = useWorkspaceStore()
    await store.load()
    expect(store.error).toBe('offline')
    expect(store.root).toBeNull()
  })
})
