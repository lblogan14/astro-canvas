import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'

import { api } from '@/api/client'

export type Theme = 'system' | 'light' | 'dark'
export type BackendStatus = 'idle' | 'connecting' | 'online' | 'offline'
export type SidebarPanel = 'library' | 'workflows' | 'workspace'
export type DrawerTab = 'log' | 'errors' | 'system'

/** The node output shown in the full-size viewer sheet. */
export interface ViewerTarget {
  nodeId: string
  port: string
}

/** The node whose expandable editor (`NodeSpec.editor`) is open. */
export interface EditorTarget {
  nodeId: string
}

/** Where editors open: a centred modal (default) or a sheet docked on the right. */
export type EditorPlacement = 'modal' | 'sheet'

/** Why the command palette opened: a plain quick-add, or a connection dropped on empty canvas. */
export interface PaletteContext {
  sourceNodeId: string
  sourcePort: string
  sourceType: string | null
  /** Screen coordinates of the drop. */
  at: { x: number; y: number }
}

const THEME_ORDER: readonly Theme[] = ['system', 'light', 'dark']
const THEME_KEY = 'astro-canvas-theme'
const FAVORITES_KEY = 'astro-canvas-favorites'
const EDITOR_PLACEMENT_KEY = 'astro-canvas-editor-placement'

function prefersDark(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

function readStorage<T>(key: string, fallback: T, check: (value: unknown) => value is T): T {
  try {
    const raw = window.localStorage.getItem(key)
    if (raw === null) return fallback
    const parsed: unknown = JSON.parse(raw)
    return check(parsed) ? parsed : fallback
  } catch {
    return fallback
  }
}

function writeStorage(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // storage unavailable (private mode, quota): keep the in-memory value
  }
}

const isTheme = (value: unknown): value is Theme =>
  value === 'system' || value === 'light' || value === 'dark'
const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((v) => typeof v === 'string')
const isPlacement = (value: unknown): value is EditorPlacement =>
  value === 'modal' || value === 'sheet'

/** Shell-wide UI state: theme, panels, backend connectivity, favourites, transient toasts. */
export const useUiStore = defineStore('ui', () => {
  const theme = ref<Theme>(readStorage(THEME_KEY, 'system', isTheme))
  const sidebarOpen = ref(true)
  const sidebarPanel = ref<SidebarPanel>('library')
  const inspectorOpen = ref(true)
  const drawerOpen = ref(false)
  const drawerTab = ref<DrawerTab>('log')
  const paletteOpen = ref(false)
  const paletteContext = ref<PaletteContext | null>(null)
  const viewer = ref<ViewerTarget | null>(null)
  const editor = ref<EditorTarget | null>(null)
  const editorPlacement = ref<EditorPlacement>(
    readStorage(EDITOR_PLACEMENT_KEY, 'modal', isPlacement),
  )
  const backendStatus = ref<BackendStatus>('idle')
  const backendVersion = ref<string | null>(null)
  const backendError = ref<string | null>(null)
  const favorites = ref<string[]>(readStorage(FAVORITES_KEY, [], isStringArray))
  const toast = ref<{ id: number; message: string; kind: 'info' | 'error' } | null>(null)
  let toastSeq = 0
  let toastTimer: ReturnType<typeof setTimeout> | null = null

  const isOnline = computed(() => backendStatus.value === 'online')
  const isDark = computed(
    () => theme.value === 'dark' || (theme.value === 'system' && prefersDark()),
  )
  const favoriteSet = computed(() => new Set(favorites.value))

  function applyTheme(): void {
    if (typeof document === 'undefined') return
    document.documentElement.classList.toggle('dark', isDark.value)
  }

  function setTheme(next: Theme): void {
    theme.value = next
    writeStorage(THEME_KEY, next)
    applyTheme()
  }

  function cycleTheme(): void {
    const index = THEME_ORDER.indexOf(theme.value)
    setTheme(THEME_ORDER[(index + 1) % THEME_ORDER.length] ?? 'system')
  }

  function toggleSidebar(): void {
    sidebarOpen.value = !sidebarOpen.value
  }

  function showSidebar(panel: SidebarPanel): void {
    if (sidebarOpen.value && sidebarPanel.value === panel) {
      sidebarOpen.value = false
      return
    }
    sidebarPanel.value = panel
    sidebarOpen.value = true
  }

  function toggleInspector(): void {
    inspectorOpen.value = !inspectorOpen.value
  }

  function toggleDrawer(tab?: DrawerTab): void {
    if (tab && (!drawerOpen.value || drawerTab.value !== tab)) {
      drawerTab.value = tab
      drawerOpen.value = true
      return
    }
    drawerOpen.value = !drawerOpen.value
  }

  function openPalette(context: PaletteContext | null = null): void {
    paletteContext.value = context
    paletteOpen.value = true
  }

  function closePalette(): void {
    paletteOpen.value = false
    paletteContext.value = null
  }

  function openViewer(target: ViewerTarget): void {
    viewer.value = target
  }

  function closeViewer(): void {
    viewer.value = null
  }

  function openEditor(target: EditorTarget): void {
    editor.value = target
  }

  function closeEditor(): void {
    editor.value = null
  }

  function setEditorPlacement(next: EditorPlacement): void {
    editorPlacement.value = next
    writeStorage(EDITOR_PLACEMENT_KEY, next)
  }

  function toggleFavorite(typeId: string): void {
    favorites.value = favoriteSet.value.has(typeId)
      ? favorites.value.filter((id) => id !== typeId)
      : [...favorites.value, typeId]
    writeStorage(FAVORITES_KEY, favorites.value)
  }

  function notify(message: string, kind: 'info' | 'error' = 'info', durationMs = 3500): void {
    toastSeq += 1
    toast.value = { id: toastSeq, message, kind }
    if (toastTimer !== null) clearTimeout(toastTimer)
    toastTimer = setTimeout(() => {
      toast.value = null
      toastTimer = null
    }, durationMs)
  }

  function dismissToast(): void {
    toast.value = null
  }

  async function connect(): Promise<void> {
    backendStatus.value = 'connecting'
    backendError.value = null
    try {
      const health = await api.getHealth()
      backendVersion.value = health.version
      backendStatus.value = 'online'
    } catch (error) {
      backendVersion.value = null
      backendError.value = error instanceof Error ? error.message : String(error)
      backendStatus.value = 'offline'
    }
  }

  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    try {
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', applyTheme)
    } catch {
      // older browsers: theme follows the OS only after reload
    }
  }
  watch(theme, applyTheme)

  return {
    theme,
    sidebarOpen,
    sidebarPanel,
    inspectorOpen,
    drawerOpen,
    drawerTab,
    paletteOpen,
    paletteContext,
    viewer,
    editor,
    editorPlacement,
    backendStatus,
    backendVersion,
    backendError,
    favorites,
    favoriteSet,
    toast,
    isOnline,
    isDark,
    setTheme,
    cycleTheme,
    toggleSidebar,
    showSidebar,
    toggleInspector,
    toggleDrawer,
    openPalette,
    closePalette,
    openViewer,
    closeViewer,
    openEditor,
    closeEditor,
    setEditorPlacement,
    toggleFavorite,
    notify,
    dismissToast,
    connect,
  }
})
