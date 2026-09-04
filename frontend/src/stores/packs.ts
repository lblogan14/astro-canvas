/**
 * Pack manager state: installed packs, the registry index, snapshots, settings and trust.
 *
 * Every environment mutation is two steps here as well as on the server: `resolve` fills
 * `plan`, the dialog shows the diff, and only a confirmed, conflict-free plan reaches
 * `install`. Anything that changed the environment sets `restartRequired`, which the shell
 * surfaces as a banner.
 */
import { computed, ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'

import { ApiError, api } from '@/api/client'
import type {
  InstallPlan,
  InstallResult,
  ManagerSettings,
  ManagerStatus,
  PackDetail,
  RegistryEntry,
  RegistryIndex,
  SnapshotInfo,
  TrustDecision,
  TrustRecord,
} from '@/api/types'

export type ManagerTab = 'installed' | 'registry' | 'snapshots' | 'settings'

/** A pending operation, so the UI can disable exactly the row that is busy. */
export interface PackBusy {
  kind: 'resolve' | 'install' | 'update' | 'uninstall' | 'enable' | 'rollback' | 'snapshot'
  target: string
}

function message(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return error instanceof Error ? error.message : String(error)
}

export const usePacksStore = defineStore('packs', () => {
  const installed = shallowRef<PackDetail[]>([])
  const registry = shallowRef<RegistryIndex | null>(null)
  const snapshots = shallowRef<SnapshotInfo[]>([])
  const trust = shallowRef<TrustRecord[]>([])
  const status = ref<ManagerStatus | null>(null)
  const available = ref(true)
  /** False when the server runs without `/api/manager` (a locked-down deployment). */
  const busy = ref<PackBusy | null>(null)
  const error = ref<string | null>(null)
  const plan = ref<InstallPlan | null>(null)
  const lastResult = ref<InstallResult | null>(null)
  const restartRequired = ref(false)
  const tab = ref<ManagerTab>('installed')
  const query = ref('')

  const settings = computed<ManagerSettings | null>(() => status.value?.settings ?? null)
  const security = computed(() => settings.value?.security ?? 'standard')
  const uvReady = computed(() => Boolean(status.value?.uv_path))
  const loadFailures = computed(() => installed.value.filter((pack) => pack.error))
  const installedNames = computed(
    () => new Set(installed.value.flatMap((p) => [p.name, p.distribution ?? p.name])),
  )

  /** Registry entries not already installed here, filtered by the search box. */
  const registryResults = computed<RegistryEntry[]>(() => {
    const entries = registry.value?.entries ?? []
    const needle = query.value.trim().toLowerCase()
    if (!needle) return entries
    return entries.filter((entry) =>
      [entry.name, entry.display_name, entry.description, ...(entry.categories ?? [])]
        .join(' ')
        .toLowerCase()
        .includes(needle),
    )
  })

  function isInstalled(entry: RegistryEntry): boolean {
    return installedNames.value.has(entry.name)
  }

  async function guard<T>(kind: PackBusy['kind'], target: string, run: () => Promise<T>) {
    busy.value = { kind, target }
    error.value = null
    try {
      return await run()
    } catch (err) {
      error.value = message(err)
      if (err instanceof ApiError && err.status === 404) available.value = false
      return null
    } finally {
      busy.value = null
    }
  }

  async function refresh(): Promise<void> {
    error.value = null
    try {
      const [managerStatus, packs] = await Promise.all([
        api.getManagerStatus(),
        api.listInstalledPacks(),
      ])
      status.value = managerStatus
      installed.value = packs
      restartRequired.value = restartRequired.value || managerStatus.restart_required
      available.value = true
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        available.value = false
        return
      }
      error.value = message(err)
    }
  }

  async function loadRegistry(refreshIndex = false): Promise<void> {
    const index = await guard('resolve', 'registry', () => api.getRegistry(refreshIndex))
    if (index) registry.value = index
  }

  async function loadSnapshots(): Promise<void> {
    const rows = await guard('snapshot', 'list', () => api.listSnapshots())
    if (rows) snapshots.value = rows
  }

  async function loadTrust(): Promise<void> {
    const rows = await guard('resolve', 'trust', () => api.listTrust())
    if (rows) trust.value = rows
  }

  /** Dry-run a source; fills `plan` so the confirmation dialog can show the diff. */
  async function resolve(source: string): Promise<InstallPlan | null> {
    const result = await guard('resolve', source, () => api.resolvePack(source))
    plan.value = result
    return result
  }

  function clearPlan(): void {
    plan.value = null
  }

  async function install(source: string): Promise<InstallResult | null> {
    const result = await guard('install', source, () => api.installPack(source))
    return applyResult(result)
  }

  async function update(name: string): Promise<InstallResult | null> {
    return applyResult(await guard('update', name, () => api.updatePack(name)))
  }

  async function uninstall(name: string): Promise<InstallResult | null> {
    return applyResult(await guard('uninstall', name, () => api.uninstallPack(name)))
  }

  async function rollback(id: number): Promise<InstallResult | null> {
    return applyResult(await guard('rollback', String(id), () => api.rollbackSnapshot(id)))
  }

  async function snapshot(label: string): Promise<SnapshotInfo | null> {
    const row = await guard('snapshot', label, () => api.createSnapshot(label))
    if (row) await loadSnapshots()
    return row
  }

  async function setEnabled(name: string, enabled: boolean): Promise<void> {
    const updated = await guard('enable', name, () => api.setPackEnabled(name, enabled))
    if (!updated) return
    installed.value = installed.value.map((pack) => (pack.name === name ? updated : pack))
    await refresh()
  }

  async function applyResult(result: InstallResult | null): Promise<InstallResult | null> {
    if (!result) return null
    lastResult.value = result
    plan.value = null
    if (result.restart_required) restartRequired.value = true
    await refresh()
    await loadSnapshots()
    return result
  }

  async function updateSettings(patch: Partial<ManagerSettings>): Promise<void> {
    const updated = await guard('resolve', 'settings', () => api.setManagerSettings(patch))
    if (updated && status.value) status.value = { ...status.value, settings: updated }
  }

  async function decide(hash: string, decision: TrustDecision): Promise<void> {
    await guard('resolve', hash, () => api.setTrust(hash, decision))
    await loadTrust()
  }

  async function forget(hash: string): Promise<void> {
    await guard('resolve', hash, () => api.forgetTrust(hash))
    await loadTrust()
  }

  /** The Manager reacts to `packs.changed` from any source (an install elsewhere, a rollback). */
  function onPacksChanged(): void {
    void refresh()
  }

  function setTab(next: ManagerTab): void {
    tab.value = next
    if (next === 'registry' && !registry.value) void loadRegistry()
    if (next === 'snapshots' && snapshots.value.length === 0) void loadSnapshots()
  }

  return {
    installed,
    registry,
    registryResults,
    snapshots,
    trust,
    status,
    settings,
    security,
    available,
    uvReady,
    loadFailures,
    busy,
    error,
    plan,
    lastResult,
    restartRequired,
    tab,
    query,
    isInstalled,
    refresh,
    loadRegistry,
    loadSnapshots,
    loadTrust,
    resolve,
    clearPlan,
    install,
    update,
    uninstall,
    rollback,
    snapshot,
    setEnabled,
    updateSettings,
    decide,
    forget,
    onPacksChanged,
    setTab,
  }
})
