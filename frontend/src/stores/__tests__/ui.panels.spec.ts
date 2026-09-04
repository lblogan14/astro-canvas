import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useUiStore } from '@/stores/ui'

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return { ...original, api: { getHealth: vi.fn<typeof original.api.getHealth>() } }
})

describe('ui store: panels, favourites, palette, toasts', () => {
  beforeEach(() => {
    window.localStorage.clear()
    setActivePinia(createPinia())
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows, switches and hides sidebar panels', () => {
    const ui = useUiStore()
    expect(ui.sidebarPanel).toBe('library')
    ui.showSidebar('workflows')
    expect(ui.sidebarOpen).toBe(true)
    expect(ui.sidebarPanel).toBe('workflows')
    ui.showSidebar('workflows')
    expect(ui.sidebarOpen).toBe(false)
    ui.showSidebar('library')
    expect(ui.sidebarOpen).toBe(true)
    expect(ui.sidebarPanel).toBe('library')
    ui.toggleInspector()
    expect(ui.inspectorOpen).toBe(false)
  })

  it('folds the canvas chrome away in a composed layout and restores it', () => {
    const ui = useUiStore()
    expect([ui.sidebarOpen, ui.inspectorOpen]).toEqual([true, true])

    ui.setMode('wizard')
    expect([ui.sidebarOpen, ui.inspectorOpen]).toEqual([false, false])
    // Panels opened by hand inside a mode stay open while switching between modes.
    ui.showSidebar('params')
    ui.setMode('dashboard')
    expect(ui.sidebarOpen).toBe(true)

    ui.setMode('canvas')
    expect([ui.sidebarOpen, ui.inspectorOpen]).toEqual([true, true])
    expect(ui.sidebarPanel).toBe('params')

    // The inspector's own state is what comes back, not a hard-coded default.
    ui.toggleInspector()
    ui.setMode('app')
    ui.setMode('canvas')
    expect(ui.inspectorOpen).toBe(false)
  })

  it('toggles the drawer, optionally switching tabs', () => {
    const ui = useUiStore()
    ui.toggleDrawer()
    expect(ui.drawerOpen).toBe(true)
    ui.toggleDrawer('errors')
    expect(ui.drawerOpen).toBe(true)
    expect(ui.drawerTab).toBe('errors')
    ui.toggleDrawer('errors')
    expect(ui.drawerOpen).toBe(false)
    ui.toggleDrawer('system')
    expect(ui.drawerOpen).toBe(true)
    expect(ui.drawerTab).toBe('system')
  })

  it('persists favourites and the theme in localStorage', () => {
    const ui = useUiStore()
    ui.toggleFavorite('core.math.expr')
    ui.toggleFavorite('core.math.constant')
    ui.toggleFavorite('core.math.expr')
    expect(ui.favorites).toEqual(['core.math.constant'])
    expect(ui.favoriteSet.has('core.math.constant')).toBe(true)
    ui.setTheme('dark')
    setActivePinia(createPinia())
    const again = useUiStore()
    expect(again.favorites).toEqual(['core.math.constant'])
    expect(again.theme).toBe('dark')
  })

  it('ignores corrupt storage', () => {
    window.localStorage.setItem('astro-canvas-favorites', '{"not":"a list"}')
    window.localStorage.setItem('astro-canvas-theme', '"purple"')
    const ui = useUiStore()
    expect(ui.favorites).toEqual([])
    expect(ui.theme).toBe('system')
  })

  it('opens the palette with or without a connection context', () => {
    const ui = useUiStore()
    ui.openPalette()
    expect(ui.paletteOpen).toBe(true)
    expect(ui.paletteContext).toBeNull()
    ui.openPalette({
      sourceNodeId: 'a',
      sourcePort: 'out',
      sourceType: 'astro.Float',
      at: { x: 1, y: 2 },
    })
    expect(ui.paletteContext?.sourceType).toBe('astro.Float')
    ui.closePalette()
    expect(ui.paletteOpen).toBe(false)
    expect(ui.paletteContext).toBeNull()
  })

  it('shows toasts that expire and can be dismissed', () => {
    const ui = useUiStore()
    ui.notify('hello')
    expect(ui.toast).toMatchObject({ message: 'hello', kind: 'info' })
    ui.notify('bad', 'error', 1000)
    expect(ui.toast).toMatchObject({ message: 'bad', kind: 'error' })
    vi.advanceTimersByTime(1000)
    expect(ui.toast).toBeNull()
    ui.notify('again')
    ui.dismissToast()
    expect(ui.toast).toBeNull()
  })
})
