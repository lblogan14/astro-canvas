import { type VueWrapper, flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import type { InstallPlan, PackageChange } from '@/api/types'
import { i18n } from '@/i18n'

import PlanDialog from '../PlanDialog.vue'

function change(overrides: Partial<PackageChange> & { name: string }): PackageChange {
  return { action: 'add', from_version: null, to_version: null, ...overrides }
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

/** reka-ui renders the dialog in a portal, so assertions go against the document body. */
let mounted: VueWrapper | null = null

async function render(props: { plan: InstallPlan | null; busy?: boolean }) {
  const wrapper = mount(PlanDialog, {
    props,
    global: { plugins: [i18n] },
    attachTo: document.body,
  })
  mounted = wrapper
  // reka-ui teleports the content in a microtask, so nothing is in the body until it settles.
  await flushPromises()
  return { wrapper, body: document.body }
}

afterEach(() => {
  // The portal outlives the component's own subtree; unmount so the next test sees a clean body.
  mounted?.unmount()
  mounted = null
  document.body.innerHTML = ''
})

function testId(id: string): HTMLElement | null {
  return document.body.querySelector(`[data-testid="${id}"]`)
}

describe('PlanDialog', () => {
  it('stays closed without a plan', async () => {
    await render({ plan: null })
    expect(testId('plan-dialog')).toBeNull()
  })

  it('lists the diff grouped by what it does', async () => {
    await render({
      plan: plan({
        changes: [
          change({ name: 'zzz-added', to_version: '1.0.0' }),
          change({ name: 'numpy', action: 'upgrade', from_version: '2.5.2', to_version: '2.6.0' }),
          change({ name: 'stale', action: 'remove', from_version: '1.0.0' }),
        ],
      }),
    })
    const rows = [...document.body.querySelectorAll('[data-testid^="plan-change-"]')]
    // Additions first, then upgrades, then anything that goes backwards.
    expect(rows.map((row) => row.getAttribute('data-action'))).toEqual(['add', 'upgrade', 'remove'])
    expect(testId('plan-summary')?.textContent).toContain('1 added')
    expect(testId('plan-summary')?.textContent).toContain('1 upgraded')
    expect(testId('plan-change-numpy')?.textContent).toContain('2.6.0')
  })

  it('warns when the plan downgrades or removes something', async () => {
    await render({
      plan: plan({
        changes: [
          change({
            name: 'numpy',
            action: 'downgrade',
            from_version: '2.6.0',
            to_version: '2.5.2',
          }),
        ],
      }),
    })
    expect(testId('plan-risky')).not.toBeNull()
  })

  it('does not warn for a plain addition', async () => {
    await render({ plan: plan({ changes: [change({ name: 'demo', to_version: '1.0.0' })] }) })
    expect(testId('plan-risky')).toBeNull()
  })

  it('offers no confirm button for a blocked plan and shows the reason', async () => {
    await render({
      plan: plan({
        ok: false,
        message: 'your requirements are unsatisfiable',
        conflicts: ['astropy>=6 and numpy==1.19.5'],
        output: 'x No solution found when resolving dependencies',
      }),
    })
    expect(testId('plan-dialog')?.getAttribute('data-blocked')).toBe('true')
    expect(testId('plan-confirm')).toBeNull()
    expect(testId('plan-conflicts')?.textContent).toContain('astropy>=6')
    expect(testId('plan-conflicts')?.textContent).toContain('unsatisfiable')
  })

  it('says so when nothing would change, and offers no confirm', async () => {
    await render({ plan: plan({ message: 'already satisfied: nothing would change' }) })
    expect(testId('plan-empty')?.textContent).toContain('already satisfied')
    expect(testId('plan-confirm')).toBeNull()
  })

  it('emits confirm and cancel', async () => {
    const { wrapper } = await render({
      plan: plan({ changes: [change({ name: 'demo', to_version: '1.0.0' })] }),
    })
    ;(testId('plan-confirm') as HTMLElement).click()
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('confirm')).toHaveLength(1)
    ;(testId('plan-cancel') as HTMLElement).click()
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })

  it('disables confirm while the install runs', async () => {
    await render({
      plan: plan({ changes: [change({ name: 'demo', to_version: '1.0.0' })] }),
      busy: true,
    })
    expect((testId('plan-confirm') as HTMLButtonElement).disabled).toBe(true)
  })

  it('keeps the raw uv output available for the curious', async () => {
    await render({ plan: plan({ output: 'Resolved 3 packages in 480ms' }) })
    expect(document.body.textContent).toContain('Resolved 3 packages in 480ms')
  })
})
