import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { ApiError, api } from '@/api/client'
import type {
  InstallPlan,
  InstallResult,
  ManagerStatus,
  PackDetail,
  RegistryEntry,
  RegistryIndex,
  SnapshotInfo,
} from '@/api/types'
import { usePacksStore } from '@/stores/packs'

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return {
    ...original,
    api: {
      getManagerStatus: vi.fn<typeof original.api.getManagerStatus>(),
      listInstalledPacks: vi.fn<typeof original.api.listInstalledPacks>(),
      resolvePack: vi.fn<typeof original.api.resolvePack>(),
      installPack: vi.fn<typeof original.api.installPack>(),
      updatePack: vi.fn<typeof original.api.updatePack>(),
      uninstallPack: vi.fn<typeof original.api.uninstallPack>(),
      setPackEnabled: vi.fn<typeof original.api.setPackEnabled>(),
      listSnapshots: vi.fn<typeof original.api.listSnapshots>(),
      createSnapshot: vi.fn<typeof original.api.createSnapshot>(),
      rollbackSnapshot: vi.fn<typeof original.api.rollbackSnapshot>(),
      getRegistry: vi.fn<typeof original.api.getRegistry>(),
      setManagerSettings: vi.fn<typeof original.api.setManagerSettings>(),
      listTrust: vi.fn<typeof original.api.listTrust>(),
      setTrust: vi.fn<typeof original.api.setTrust>(),
      forgetTrust: vi.fn<typeof original.api.forgetTrust>(),
    },
  }
})

const mocked = vi.mocked(api)

function pack(name: string, overrides: Partial<PackDetail> = {}): PackDetail {
  return {
    name,
    version: '0.1.0',
    distribution: `astro-canvas-${name}`,
    entry_point: `${name}:register`,
    enabled: true,
    loaded: true,
    node_count: 3,
    type_count: 1,
    template_count: 0,
    security: 'standard',
    source: null,
    installed: null,
    error: null,
    traceback: null,
    ...overrides,
  }
}

function status(overrides: Partial<ManagerStatus> = {}): ManagerStatus {
  return {
    uv_path: '/usr/bin/uv',
    uv_version: 'uv 0.11.25',
    uv_error: null,
    python: '/env/bin/python',
    settings: { security: 'standard', uv_path: null, registry_url: '' },
    security_levels: ['strict', 'standard', 'permissive'],
    security_help: {},
    restart_required: false,
    ...overrides,
  }
}

function plan(overrides: Partial<InstallPlan> = {}): InstallPlan {
  return {
    source: 'astro-canvas-demo',
    action: 'install',
    changes: [],
    conflicts: [],
    ok: true,
    message: '',
    output: '',
    ...overrides,
  }
}

function result(overrides: Partial<InstallResult> = {}): InstallResult {
  return {
    ok: true,
    action: 'install',
    source: 'astro-canvas-demo',
    plan: null,
    snapshot_id: 1,
    packs: ['demo'],
    restart_required: false,
    import_test: null,
    message: 'installed demo',
    output: '',
    ...overrides,
  }
}

function entry(name: string, overrides: Partial<RegistryEntry> = {}): RegistryEntry {
  return {
    name,
    display_name: name,
    publisher: 'someone',
    description: 'A pack',
    source: name,
    latest: '1.0.0',
    requires: {},
    categories: [],
    templates: [],
    security: 'standard',
    homepage: '',
    stars: null,
    ...overrides,
  }
}

const index = (entries: RegistryEntry[]): RegistryIndex => ({
  url: 'https://example/index.json',
  entries,
  fetched: 0,
  stale: false,
  error: null,
})

const snapshot = (id: number): SnapshotInfo => ({
  id,
  created: '2026-09-04T00:00:00',
  label: 'before install',
  packages: 12,
})

describe('packs store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mocked.getManagerStatus.mockResolvedValue(status())
    mocked.listInstalledPacks.mockResolvedValue([pack('core'), pack('rbcodes')])
    mocked.listSnapshots.mockResolvedValue([snapshot(1)])
  })

  it('loads status and installed packs', async () => {
    const packs = usePacksStore()
    await packs.refresh()
    expect(packs.available).toBe(true)
    expect(packs.installed.map((p) => p.name)).toEqual(['core', 'rbcodes'])
    expect(packs.security).toBe('standard')
    expect(packs.uvReady).toBe(true)
  })

  it('marks itself unavailable when the server has no manager', async () => {
    mocked.getManagerStatus.mockRejectedValue(new ApiError(404, 'disabled'))
    const packs = usePacksStore()
    await packs.refresh()
    expect(packs.available).toBe(false)
  })

  it('surfaces a load failure per pack', async () => {
    mocked.listInstalledPacks.mockResolvedValue([
      pack('broken', { error: 'ImportError: nope', loaded: false, traceback: 'Traceback…' }),
    ])
    const packs = usePacksStore()
    await packs.refresh()
    expect(packs.loadFailures.map((p) => p.name)).toEqual(['broken'])
  })

  it('resolves before installing and keeps the plan for the dialog', async () => {
    mocked.resolvePack.mockResolvedValue(plan({ changes: [] }))
    const packs = usePacksStore()
    const resolved = await packs.resolve('astro-canvas-demo')
    expect(resolved?.ok).toBe(true)
    expect(packs.plan).not.toBeNull()
    expect(mocked.installPack).not.toHaveBeenCalled()
  })

  it('keeps a blocked plan so the dialog can explain it', async () => {
    mocked.resolvePack.mockResolvedValue(
      plan({ ok: false, message: 'unsatisfiable', conflicts: ['numpy'] }),
    )
    const packs = usePacksStore()
    await packs.resolve('astro-canvas-bad')
    expect(packs.plan?.ok).toBe(false)
    expect(packs.plan?.conflicts).toEqual(['numpy'])
  })

  it('clears the plan and refreshes after a successful install', async () => {
    mocked.installPack.mockResolvedValue(result())
    const packs = usePacksStore()
    packs.plan = plan()
    const installed = await packs.install('astro-canvas-demo')
    expect(installed?.ok).toBe(true)
    expect(packs.plan).toBeNull()
    expect(mocked.listInstalledPacks).toHaveBeenCalled()
    expect(packs.restartRequired).toBe(false)
  })

  it('raises the restart flag when the server says so', async () => {
    mocked.installPack.mockResolvedValue(result({ restart_required: true }))
    const packs = usePacksStore()
    await packs.install('astro-canvas-demo')
    expect(packs.restartRequired).toBe(true)
  })

  it('reports an install failure without throwing', async () => {
    mocked.installPack.mockRejectedValue(new ApiError(400, 'the resolution has conflicts'))
    const packs = usePacksStore()
    expect(await packs.install('astro-canvas-bad')).toBeNull()
    expect(packs.error).toBe('the resolution has conflicts')
    expect(packs.busy).toBeNull()
  })

  it('rolls back through a snapshot and asks for a restart', async () => {
    mocked.rollbackSnapshot.mockResolvedValue(
      result({ action: 'rollback', restart_required: true, message: 'restored 12 packages' }),
    )
    const packs = usePacksStore()
    const rolled = await packs.rollback(1)
    expect(rolled?.message).toContain('restored')
    expect(packs.restartRequired).toBe(true)
  })

  it('replaces the row it toggled', async () => {
    mocked.setPackEnabled.mockResolvedValue(pack('core', { enabled: false, loaded: false }))
    const packs = usePacksStore()
    await packs.refresh()
    await packs.setEnabled('core', false)
    expect(mocked.setPackEnabled).toHaveBeenCalledWith('core', false)
  })

  it('filters the registry client-side and knows what is installed', async () => {
    mocked.getRegistry.mockResolvedValue(
      index([entry('astro-canvas-core'), entry('astro-canvas-demo', { description: 'spectra' })]),
    )
    const packs = usePacksStore()
    await packs.refresh()
    await packs.loadRegistry()
    expect(packs.registryResults).toHaveLength(2)
    packs.query = 'spectra'
    expect(packs.registryResults.map((e) => e.name)).toEqual(['astro-canvas-demo'])
    expect(packs.isInstalled(entry('astro-canvas-core'))).toBe(true)
    expect(packs.isInstalled(entry('astro-canvas-demo'))).toBe(false)
  })

  it('loads the registry the first time that tab is opened', async () => {
    mocked.getRegistry.mockResolvedValue(index([]))
    const packs = usePacksStore()
    packs.setTab('registry')
    await Promise.resolve()
    expect(mocked.getRegistry).toHaveBeenCalledTimes(1)
  })

  it('updates a pack and refreshes', async () => {
    mocked.updatePack.mockResolvedValue(
      result({ action: 'update', restart_required: true, message: 'restart to finish' }),
    )
    const packs = usePacksStore()
    const updated = await packs.update('core')
    expect(updated?.message).toBe('restart to finish')
    expect(packs.restartRequired).toBe(true)
  })

  it('uninstalls a pack', async () => {
    mocked.uninstallPack.mockResolvedValue(result({ action: 'uninstall', packs: ['demo'] }))
    const packs = usePacksStore()
    expect((await packs.uninstall('demo'))?.packs).toEqual(['demo'])
    expect(mocked.uninstallPack).toHaveBeenCalledWith('demo')
  })

  it('takes a snapshot and reloads the list', async () => {
    mocked.createSnapshot.mockResolvedValue(snapshot(2))
    mocked.listSnapshots.mockResolvedValue([snapshot(2), snapshot(1)])
    const packs = usePacksStore()
    expect((await packs.snapshot('before the experiment'))?.id).toBe(2)
    expect(packs.snapshots.map((s) => s.id)).toEqual([2, 1])
  })

  it('loads snapshots the first time that tab is opened', async () => {
    const packs = usePacksStore()
    packs.setTab('snapshots')
    await Promise.resolve()
    expect(mocked.listSnapshots).toHaveBeenCalledTimes(1)
  })

  it('keeps the new settings in the status it already holds', async () => {
    mocked.setManagerSettings.mockResolvedValue({
      security: 'permissive',
      uv_path: '/opt/uv',
      registry_url: '',
    })
    const packs = usePacksStore()
    await packs.refresh()
    await packs.updateSettings({ security: 'permissive' })
    expect(packs.security).toBe('permissive')
    expect(packs.settings?.uv_path).toBe('/opt/uv')
  })

  it('reports a settings failure rather than throwing', async () => {
    mocked.setManagerSettings.mockRejectedValue(new Error('read-only workspace'))
    const packs = usePacksStore()
    await packs.updateSettings({ security: 'strict' })
    expect(packs.error).toBe('read-only workspace')
  })

  it('forgets a decision and reloads the list', async () => {
    mocked.forgetTrust.mockResolvedValue(undefined)
    mocked.listTrust.mockResolvedValue([])
    const packs = usePacksStore()
    await packs.forget('abc')
    expect(mocked.forgetTrust).toHaveBeenCalledWith('abc')
    expect(packs.trust).toEqual([])
  })

  it('refreshes when a packs.changed event arrives', async () => {
    const packs = usePacksStore()
    packs.onPacksChanged()
    await Promise.resolve()
    expect(mocked.listInstalledPacks).toHaveBeenCalled()
  })

  it('keeps a stale registry copy visible', async () => {
    mocked.getRegistry.mockResolvedValue({
      ...index([entry('astro-canvas-core')]),
      stale: true,
      error: 'offline',
    })
    const packs = usePacksStore()
    await packs.loadRegistry(true)
    expect(packs.registry?.stale).toBe(true)
    expect(packs.registryResults).toHaveLength(1)
  })

  it('reports a refresh failure that is not a missing manager', async () => {
    mocked.getManagerStatus.mockRejectedValue(new ApiError(500, 'boom'))
    const packs = usePacksStore()
    await packs.refresh()
    expect(packs.available).toBe(true)
    expect(packs.error).toBe('boom')
  })

  it('clears a plan the user cancelled', async () => {
    const packs = usePacksStore()
    packs.plan = plan()
    packs.clearPlan()
    expect(packs.plan).toBeNull()
  })

  it('ignores an empty resolve', async () => {
    mocked.resolvePack.mockRejectedValue(new ApiError(400, 'an install source is required'))
    const packs = usePacksStore()
    expect(await packs.resolve('')).toBeNull()
    expect(packs.error).toContain('required')
  })

  it('records a trust decision and reloads the list', async () => {
    mocked.setTrust.mockResolvedValue({ hash: 'abc', decision: 'trusted', decided: 'now' })
    mocked.listTrust.mockResolvedValue([{ hash: 'abc', decision: 'trusted', decided: 'now' }])
    const packs = usePacksStore()
    await packs.decide('abc', 'trusted')
    expect(packs.trust.map((r) => r.hash)).toEqual(['abc'])
  })
})
