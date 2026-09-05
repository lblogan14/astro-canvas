/**
 * The shell's four state banners (phase 13, scope item 4). Each one is a state the user cannot
 * discover any other way, so each one is asserted on its own: what it says, what it offers, and
 * when it goes away again.
 */
import { describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'

import type { PackRecord, WorkspaceInfo } from '@/api/types'
import ShellNotices from '@/app/ShellNotices.vue'
import { i18n } from '@/i18n'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'
import { useWorkspaceStore } from '@/stores/workspace'
import { mathChain } from '@/stores/__tests__/fixtures'

const connect = vi.fn<() => void>()
const getHealth = vi.fn<() => Promise<{ status: string; version: string }>>(async () => ({
  status: 'ok',
  version: '0.1.0',
}))

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return { ...original, api: { getHealth: () => getHealth() } }
})

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: { template: '<div />' } },
    { path: '/manager', name: 'manager', component: { template: '<div />' } },
  ],
})

function workspaceInfo(overrides: Partial<WorkspaceInfo> = {}): WorkspaceInfo {
  return {
    root: 'C:/ws',
    name: 'ws',
    recent: [],
    samples_dir: 'samples',
    downloads_dir: 'downloads',
    uploads_dir: 'uploads',
    shared_dir: null,
    can_select: true,
    available: true,
    ...overrides,
  }
}

function failure(error: string): PackRecord['error'] {
  return { error, traceback: '', pack: 'broken', entry_point: 'broken:register' }
}

function pack(overrides: Partial<PackRecord> = {}): PackRecord {
  return {
    name: 'rbcodes',
    version: '0.1.0',
    distribution: 'astro-canvas-rbcodes',
    entry_point: 'astro_canvas_rbcodes:register',
    enabled: true,
    node_count: 0,
    type_count: 0,
    security: 'standard',
    error: null,
    ...overrides,
  }
}

async function render() {
  setActivePinia(createPinia())
  const wrapper = mount(ShellNotices, { global: { plugins: [i18n, router] } })
  await router.isReady()
  return wrapper
}

describe('ShellNotices', () => {
  it('says nothing when everything is fine', async () => {
    const wrapper = await render()
    useWorkspaceStore().info = workspaceInfo()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="shell-notices"]').exists()).toBe(false)
  })

  it('reports a dropped connection with the attempt count, and offers a retry', async () => {
    const wrapper = await render()
    const session = useSessionStore()
    session.wsStatus = 'reconnecting'
    session.wsAttempt = 3
    session.connect = connect
    await wrapper.vm.$nextTick()

    const notice = wrapper.find('[data-testid="notice-offline"]')
    expect(notice.exists()).toBe(true)
    expect(notice.attributes('data-reconnecting')).toBe('true')
    expect(notice.text()).toContain('attempt 3')

    await wrapper.find('[data-testid="notice-retry"]').trigger('click')
    await flushPromises()
    expect(getHealth).toHaveBeenCalled()
    expect(connect).toHaveBeenCalled()

    session.wsStatus = 'open'
    useUiStore().backendStatus = 'online'
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="notice-offline"]').exists()).toBe(false)
  })

  it('reports an offline backend even while the socket is idle', async () => {
    const wrapper = await render()
    useUiStore().backendStatus = 'offline'
    await wrapper.vm.$nextTick()
    const notice = wrapper.find('[data-testid="notice-offline"]')
    expect(notice.attributes('data-reconnecting')).toBe('false')
    expect(notice.text()).toContain('No contact with the server')
  })

  it('names the workspace that went away and opens the panel to switch', async () => {
    const wrapper = await render()
    const workspace = useWorkspaceStore()
    workspace.info = workspaceInfo({ available: false, root: 'D:/field-trip' })
    await wrapper.vm.$nextTick()

    const notice = wrapper.find('[data-testid="notice-workspace"]')
    expect(notice.text()).toContain('D:/field-trip')
    // Not dismissible: a workspace you cannot read is not something to hide.
    expect(notice.find('[aria-label="Dismiss"]').exists()).toBe(false)

    await wrapper.find('[data-testid="notice-workspace-switch"]').trigger('click')
    const ui = useUiStore()
    expect(ui.sidebarOpen).toBe(true)
    expect(ui.sidebarPanel).toBe('workspace')
  })

  it('counts the packs that failed to load and links to the Manager', async () => {
    const wrapper = await render()
    const schema = useNodesSchemaStore()
    schema.packs = [pack(), pack({ name: 'broken', error: failure('ImportError: no scipy') })]
    await wrapper.vm.$nextTick()

    const notice = wrapper.find('[data-testid="notice-packs"]')
    expect(notice.attributes('data-count')).toBe('1')
    expect(notice.text()).toContain('broken')
    expect(notice.text()).toContain('One node pack failed to load')
    expect(wrapper.find('[data-testid="notice-packs-manager"]').exists()).toBe(true)

    await wrapper.find('[data-testid="notice-packs-dismiss"]').trigger('click')
    expect(wrapper.find('[data-testid="notice-packs"]').exists()).toBe(false)

    // A different failure is worth saying again.
    schema.packs = [pack({ name: 'other', error: failure('boom') })]
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="notice-packs"]').exists()).toBe(true)
  })

  it('pluralises the pack notice', async () => {
    const wrapper = await render()
    useNodesSchemaStore().packs = [
      pack({ name: 'a', error: failure('x') }),
      pack({ name: 'b', error: failure('y') }),
    ]
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="notice-packs"]').text()).toContain(
      '2 node packs failed to load',
    )
  })

  it('explains a recovered document and offers to keep it', async () => {
    const wrapper = await render()
    const workflow = useWorkflowStore()
    const doc = mathChain()
    doc.meta = {
      ...doc.meta,
      recovered: { version: 12, created: '2026-09-04T10:00:00', reason: 'ValidationError: 3' },
    }
    workflow.load(doc)
    const saveNow = vi.fn<() => Promise<void>>(async () => undefined)
    workflow.saveNow = saveNow
    await wrapper.vm.$nextTick()

    const notice = wrapper.find('[data-testid="notice-recovered"]')
    expect(notice.attributes('data-version')).toBe('12')
    expect(notice.text()).toContain('version 12')

    await wrapper.find('[data-testid="notice-recovered-save"]').trigger('click')
    expect(saveNow).toHaveBeenCalled()

    await wrapper.find('[data-testid="notice-recovered-dismiss"]').trigger('click')
    expect(wrapper.find('[data-testid="notice-recovered"]').exists()).toBe(false)
  })

  it('says nothing about recovery for an ordinary document', async () => {
    const wrapper = await render()
    useWorkflowStore().load(mathChain())
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="notice-recovered"]').exists()).toBe(false)
  })
})
