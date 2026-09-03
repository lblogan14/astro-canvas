import { ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'

import { api } from '@/api/client'
import type { WorkflowDoc, WorkflowSummary, WorkflowVersionInfo } from '@/api/types'
import { clone } from '@/lib/deepEqual'
import { newId } from '@/lib/ids'

/** The stored workflows list (sidebar) and per-workflow version history. */
export const useWorkflowsStore = defineStore('workflows', () => {
  const items = shallowRef<WorkflowSummary[]>([])
  const versions = shallowRef<WorkflowVersionInfo[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function refresh(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      items.value = await api.listWorkflows()
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loading.value = false
    }
  }

  async function remove(id: string): Promise<void> {
    await api.deleteWorkflow(id)
    items.value = items.value.filter((w) => w.id !== id)
  }

  /** Store a copy of `id` under a new id; returns the copy's id. */
  async function duplicate(id: string, name?: string): Promise<string> {
    const source = await api.getWorkflow(id)
    const copy = clone(source)
    copy.id = newId('wf')
    copy.name = name ?? `${source.name} (copy)`
    copy.meta = {}
    const saved = await api.createWorkflow(copy)
    await refresh()
    return saved.doc.id as string
  }

  async function loadVersions(id: string): Promise<void> {
    try {
      versions.value = await api.listVersions(id)
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
      versions.value = []
    }
  }

  async function fetchVersion(id: string, versionId: number): Promise<WorkflowDoc> {
    return api.getVersion(id, versionId)
  }

  return { items, versions, loading, error, refresh, remove, duplicate, loadVersions, fetchVersion }
})
