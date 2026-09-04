import { describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'

import { i18n } from '@/i18n'
import type { TemplateInfo } from '@/api/types'
import TemplatesGallery from '@/app/templates/TemplatesGallery.vue'
import { useUiStore } from '@/stores/ui'
import { useWorkflowsStore } from '@/stores/workflows'

type AnyFn = (...args: unknown[]) => unknown
const listTemplates = vi.fn<AnyFn>()
const instantiateTemplate = vi.fn<AnyFn>()

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return {
    ...original,
    getToken: () => 'test-token',
    api: {
      listTemplates: (...args: unknown[]) => listTemplates(...args),
      instantiateTemplate: (...args: unknown[]) => instantiateTemplate(...args),
    },
  }
})

function template(overrides: Partial<TemplateInfo> = {}): TemplateInfo {
  return {
    id: 'rbcodes.absorption-line-measurement',
    name: 'Absorption Line Measurement',
    description: 'MgII 2796 at z = 1.3855.',
    pack: 'rbcodes',
    node_count: 9,
    file: 'absorption-line-measurement.acw',
    readme: null,
    packs: { 'astro-canvas-rbcodes': '>=0.1,<0.2' },
    tags: ['absorption'],
    layouts: ['app', 'wizard', 'batch'],
    default_layout: 'wizard',
    figure: false,
    ...overrides,
  }
}

function makeRouter() {
  const blank = { template: '<div />' }
  return createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/', name: 'home', component: blank },
      { path: '/templates', name: 'templates', component: TemplatesGallery },
      { path: '/w/:id', name: 'workflow', component: blank },
      { path: '/w/:id/:mode', name: 'workflow-mode', component: blank },
    ],
  })
}

async function mountGallery(templates: TemplateInfo[]) {
  setActivePinia(createPinia())
  listTemplates.mockResolvedValue(templates)
  const router = makeRouter()
  await router.push('/templates')
  await router.isReady()
  const gallery = mount(TemplatesGallery, { global: { plugins: [i18n, router] } })
  await vi.waitUntil(() => useWorkflowsStore().templates.length === templates.length)
  await gallery.vm.$nextTick()
  return { gallery, router }
}

describe('templates gallery', () => {
  it('shows a card per template with its packs and default layout', async () => {
    const { gallery } = await mountGallery([
      template(),
      template({
        id: 'rbcodes.redshift-finder',
        name: 'Redshift Finder',
        default_layout: 'dashboard',
      }),
    ])
    const cards = gallery.findAll('[data-testid^="gallery-card-"]')
    expect(cards).toHaveLength(2)
    const first = cards[0]!
    expect(first.attributes('data-layout')).toBe('wizard')
    expect(first.text()).toContain('Absorption Line Measurement')
    expect(first.text()).toContain('astro-canvas-rbcodes')
    expect(first.text()).toContain('Wizard')
    // Without a figure the card paints its own initials block.
    expect(first.find('img').exists()).toBe(false)
  })

  it('links a shipped figure with the bearer token', async () => {
    const { gallery } = await mountGallery([template({ figure: true })])
    const img = gallery.get('[data-testid^="gallery-card-"] img')
    expect(img.attributes('src')).toBe(
      '/api/templates/rbcodes.absorption-line-measurement/figure?token=test-token',
    )
  })

  it('filters by name, description, pack and tags', async () => {
    const { gallery } = await mountGallery([
      template(),
      template({ id: 'rbcodes.ifu-cube-explorer', name: 'IFU Cube Explorer', tags: ['cube'] }),
    ])
    await gallery.get('[data-testid="gallery-search"]').setValue('cube')
    expect(gallery.findAll('[data-testid^="gallery-card-"]')).toHaveLength(1)
    await gallery.get('[data-testid="gallery-search"]').setValue('nothing here')
    expect(gallery.find('[data-testid="gallery-empty"]').exists()).toBe(true)
  })

  it('opens a template into its default layout', async () => {
    instantiateTemplate.mockResolvedValue({ doc: { id: 'wf-1' }, node_errors: {} })
    const { gallery, router } = await mountGallery([template()])
    await gallery
      .get('[data-testid="gallery-open-rbcodes.absorption-line-measurement"]')
      .trigger('click')
    await vi.waitUntil(() => router.currentRoute.value.name === 'workflow-mode')

    expect(instantiateTemplate).toHaveBeenCalledWith('rbcodes.absorption-line-measurement', null)
    expect(router.currentRoute.value.params).toEqual({ id: 'wf-1', mode: 'wizard' })
    expect(useUiStore().mode).toBe('wizard')
  })

  it('"Show graph" opens the same template on the canvas', async () => {
    instantiateTemplate.mockResolvedValue({ doc: { id: 'wf-2' }, node_errors: {} })
    const { gallery, router } = await mountGallery([template()])
    await gallery
      .get('[data-testid="gallery-graph-rbcodes.absorption-line-measurement"]')
      .trigger('click')
    await vi.waitUntil(() => router.currentRoute.value.name === 'workflow')

    expect(router.currentRoute.value.params).toEqual({ id: 'wf-2' })
    expect(useUiStore().mode).toBe('canvas')
  })

  it('reports a failed instantiation instead of navigating', async () => {
    instantiateTemplate.mockRejectedValue(new Error('pack missing'))
    const { gallery, router } = await mountGallery([template()])
    await gallery
      .get('[data-testid="gallery-open-rbcodes.absorption-line-measurement"]')
      .trigger('click')
    await vi.waitUntil(() => useUiStore().toast !== null)

    expect(useUiStore().toast?.message).toBe('pack missing')
    expect(router.currentRoute.value.name).toBe('templates')
  })
})
