import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { ApiError, api } from '@/api/client'
import { useUiStore } from '@/stores/ui'

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return {
    ...original,
    api: {
      getHealth: vi.fn<typeof original.api.getHealth>(),
      getSystem: vi.fn<typeof original.api.getSystem>(),
    },
  }
})

const getHealth = vi.mocked(api.getHealth)

describe('ui store', () => {
  beforeEach(() => {
    window.localStorage.clear()
    setActivePinia(createPinia())
    getHealth.mockReset()
    document.documentElement.classList.remove('dark')
  })

  it('starts idle with the sidebar open and the system theme', () => {
    const ui = useUiStore()
    expect(ui.backendStatus).toBe('idle')
    expect(ui.backendVersion).toBeNull()
    expect(ui.sidebarOpen).toBe(true)
    expect(ui.theme).toBe('system')
    expect(ui.isOnline).toBe(false)
  })

  it('toggles the sidebar', () => {
    const ui = useUiStore()
    ui.toggleSidebar()
    expect(ui.sidebarOpen).toBe(false)
    ui.toggleSidebar()
    expect(ui.sidebarOpen).toBe(true)
  })

  it('applies the dark class when the theme is dark and removes it for light', () => {
    const ui = useUiStore()
    ui.setTheme('dark')
    expect(ui.isDark).toBe(true)
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    ui.setTheme('light')
    expect(ui.isDark).toBe(false)
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('cycles system → light → dark → system', () => {
    const ui = useUiStore()
    ui.cycleTheme()
    expect(ui.theme).toBe('light')
    ui.cycleTheme()
    expect(ui.theme).toBe('dark')
    ui.cycleTheme()
    expect(ui.theme).toBe('system')
  })

  it('goes online with the backend version when /api/health answers', async () => {
    getHealth.mockResolvedValueOnce({ status: 'ok', version: '0.1.0a0' })
    const ui = useUiStore()
    const pending = ui.connect()
    expect(ui.backendStatus).toBe('connecting')
    await pending
    expect(ui.backendStatus).toBe('online')
    expect(ui.isOnline).toBe(true)
    expect(ui.backendVersion).toBe('0.1.0a0')
    expect(ui.backendError).toBeNull()
    expect(getHealth).toHaveBeenCalledTimes(1)
  })

  it('goes offline and records the error when the backend is unreachable', async () => {
    getHealth.mockRejectedValueOnce(new ApiError(503, '503 Service Unavailable'))
    const ui = useUiStore()
    await ui.connect()
    expect(ui.backendStatus).toBe('offline')
    expect(ui.isOnline).toBe(false)
    expect(ui.backendVersion).toBeNull()
    expect(ui.backendError).toBe('503 Service Unavailable')
  })

  it('stringifies non-Error rejections', async () => {
    getHealth.mockRejectedValueOnce('boom')
    const ui = useUiStore()
    await ui.connect()
    expect(ui.backendError).toBe('boom')
  })
})

describe('ui store system theme', () => {
  const originalMatchMedia = window.matchMedia

  beforeEach(() => {
    window.localStorage.clear()
    setActivePinia(createPinia())
    document.documentElement.classList.remove('dark')
  })

  afterEach(() => {
    window.matchMedia = originalMatchMedia
  })

  it('follows the OS preference when the theme is system', () => {
    window.matchMedia = vi.fn<typeof window.matchMedia>(() => ({ matches: true }) as MediaQueryList)
    const ui = useUiStore()
    ui.setTheme('system')
    expect(ui.isDark).toBe(true)
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('falls back to light when matchMedia is unavailable', () => {
    // jsdom does not implement matchMedia; simulate that explicitly.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- removing a DOM API for the test
    ;(window as any).matchMedia = undefined
    const ui = useUiStore()
    ui.setTheme('system')
    expect(ui.isDark).toBe(false)
  })
})
