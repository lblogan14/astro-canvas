/**
 * Workspace files: the active folder, a lazily loaded directory tree, uploads with progress and
 * refreshes driven by `workspace.changed` events. Paths are workspace-relative POSIX strings
 * (`''` is the root).
 */
import { computed, ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'

import { api, errorMessage, type UploadConflict } from '@/api/client'
import type { SniffResult, WorkspaceEntry, WorkspaceInfo } from '@/api/types'

export type UploadState = 'pending' | 'uploading' | 'done' | 'error'

export interface UploadJob {
  id: number
  name: string
  dir: string
  size: number
  loaded: number
  state: UploadState
  error: string | null
  /** Workspace path of the stored file once complete. */
  path: string | null
}

export function parentOf(path: string): string {
  const idx = path.lastIndexOf('/')
  return idx === -1 ? '' : path.slice(0, idx)
}

export function joinPath(dir: string, name: string): string {
  return dir ? `${dir}/${name}` : name
}

export const useWorkspaceStore = defineStore('workspace', () => {
  const info = ref<WorkspaceInfo | null>(null)
  /** Listed children per folder path (`''` = root); absent = not loaded yet. */
  const children = shallowRef<Record<string, WorkspaceEntry[]>>({})
  const expanded = ref<Set<string>>(new Set(['']))
  const loading = ref<Set<string>>(new Set())
  const selectedPath = ref<string | null>(null)
  const uploads = ref<UploadJob[]>([])
  const error = ref<string | null>(null)
  const sniffCache = shallowRef<Record<string, SniffResult>>({})
  let uploadSeq = 0
  let refreshTimer: ReturnType<typeof setTimeout> | null = null
  const pendingRefresh = new Set<string>()

  const root = computed(() => info.value?.root ?? null)
  const rootName = computed(() => info.value?.name ?? '')
  const recent = computed(() => info.value?.recent ?? [])
  /** False when the workspace folder has gone away (unplugged drive, unmounted share). */
  const available = computed(() => info.value?.available !== false)
  const activeUploads = computed(() =>
    uploads.value.filter((u) => u.state === 'pending' || u.state === 'uploading'),
  )

  function entriesOf(path: string): WorkspaceEntry[] | undefined {
    return children.value[path]
  }

  function isLoaded(path: string): boolean {
    return children.value[path] !== undefined
  }

  function setChildren(path: string, entries: WorkspaceEntry[]): void {
    children.value = { ...children.value, [path]: entries }
  }

  async function load(): Promise<void> {
    error.value = null
    try {
      info.value = await api.getWorkspace()
      children.value = {}
      sniffCache.value = {}
      await refresh('')
    } catch (err) {
      error.value = errorMessage(err)
    }
  }

  /** (Re)list one folder. */
  async function refresh(path: string): Promise<void> {
    const key = path
    loading.value = new Set([...loading.value, key])
    try {
      const tree = await api.getWorkspaceTree(path, 1)
      setChildren(key, tree.entries)
      // Drop cached listings of folders that vanished.
      const names = new Set(tree.entries.filter((e) => e.is_dir).map((e) => e.path))
      const next = { ...children.value }
      let changed = false
      for (const cached of Object.keys(next)) {
        if (cached !== key && parentOf(cached) === key && !names.has(cached)) {
          delete next[cached]
          changed = true
        }
      }
      if (changed) children.value = next
    } catch (err) {
      error.value = errorMessage(err)
    } finally {
      const rest = new Set(loading.value)
      rest.delete(key)
      loading.value = rest
    }
  }

  async function expand(path: string): Promise<void> {
    expanded.value = new Set([...expanded.value, path])
    if (!isLoaded(path)) await refresh(path)
  }

  function collapse(path: string): void {
    const next = new Set(expanded.value)
    next.delete(path)
    expanded.value = next
  }

  async function toggle(path: string): Promise<void> {
    if (expanded.value.has(path)) collapse(path)
    else await expand(path)
  }

  function select(path: string | null): void {
    selectedPath.value = path
  }

  /** Apply a `workspace.changed` event: refresh the parents of the changed paths (debounced). */
  function applyChange(paths: string[]): void {
    for (const p of paths) {
      const parent = parentOf(p)
      if (isLoaded(parent)) pendingRefresh.add(parent)
      if (isLoaded(p)) pendingRefresh.add(p)
      const rest = { ...sniffCache.value }
      delete rest[p]
      sniffCache.value = rest
    }
    if (refreshTimer !== null) clearTimeout(refreshTimer)
    refreshTimer = setTimeout(() => {
      refreshTimer = null
      const targets = [...pendingRefresh]
      pendingRefresh.clear()
      for (const target of targets) void refresh(target)
    }, 250)
  }

  async function sniff(path: string): Promise<SniffResult> {
    const cached = sniffCache.value[path]
    if (cached) return cached
    const result = await api.sniffWorkspaceFile(path)
    sniffCache.value = { ...sniffCache.value, [path]: result }
    return result
  }

  async function upload(
    files: File[] | FileList,
    dir = 'uploads',
    onConflict: UploadConflict = 'rename',
  ): Promise<UploadJob[]> {
    const jobs: UploadJob[] = []
    for (const file of Array.from(files)) {
      uploadSeq += 1
      const job: UploadJob = {
        id: uploadSeq,
        name: file.name,
        dir,
        size: file.size,
        loaded: 0,
        state: 'pending',
        error: null,
        path: null,
      }
      uploads.value = [...uploads.value, job]
      jobs.push(job)
      const update = (patch: Partial<UploadJob>): void => {
        uploads.value = uploads.value.map((u) => (u.id === job.id ? { ...u, ...patch } : u))
      }
      update({ state: 'uploading' })
      try {
        const result = await api.uploadWorkspaceFile(file, {
          dir,
          onConflict,
          onProgress: (loaded) => update({ loaded }),
        })
        update({ state: 'done', loaded: file.size, path: result.file?.path ?? null })
        job.path = result.file?.path ?? null
        job.state = 'done'
      } catch (err) {
        const message = errorMessage(err)
        update({ state: 'error', error: message })
        job.state = 'error'
        job.error = message
      }
    }
    await refresh(dir)
    await expand(dir)
    return jobs
  }

  function clearUploads(): void {
    uploads.value = uploads.value.filter((u) => u.state === 'uploading' || u.state === 'pending')
  }

  async function createFolder(path: string): Promise<void> {
    await api.makeWorkspaceDir(path)
    await refresh(parentOf(path))
  }

  async function remove(path: string, recursive = false): Promise<void> {
    await api.deleteWorkspacePath(path, recursive)
    if (selectedPath.value === path) selectedPath.value = null
    await refresh(parentOf(path))
  }

  async function switchWorkspace(path: string, create = false): Promise<WorkspaceInfo> {
    const next = await api.selectWorkspace(path, create)
    info.value = next
    children.value = {}
    sniffCache.value = {}
    expanded.value = new Set([''])
    selectedPath.value = null
    await refresh('')
    return next
  }

  return {
    info,
    root,
    rootName,
    recent,
    available,
    children,
    expanded,
    loading,
    selectedPath,
    uploads,
    activeUploads,
    error,
    entriesOf,
    isLoaded,
    load,
    refresh,
    expand,
    collapse,
    toggle,
    select,
    applyChange,
    sniff,
    upload,
    clearUploads,
    createFolder,
    remove,
    switchWorkspace,
  }
})
