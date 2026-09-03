import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { api } from '@/api/client'

export type Theme = 'system' | 'light' | 'dark'
export type BackendStatus = 'idle' | 'connecting' | 'online' | 'offline'

const THEME_ORDER: readonly Theme[] = ['system', 'light', 'dark']

function prefersDark(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

/** Shell-wide UI state: theme, sidebar, and backend connectivity. */
export const useUiStore = defineStore('ui', () => {
  const theme = ref<Theme>('system')
  const sidebarOpen = ref(true)
  const backendStatus = ref<BackendStatus>('idle')
  const backendVersion = ref<string | null>(null)
  const backendError = ref<string | null>(null)

  const isOnline = computed(() => backendStatus.value === 'online')
  const isDark = computed(
    () => theme.value === 'dark' || (theme.value === 'system' && prefersDark()),
  )

  function applyTheme(): void {
    if (typeof document === 'undefined') return
    document.documentElement.classList.toggle('dark', isDark.value)
  }

  function setTheme(next: Theme): void {
    theme.value = next
    applyTheme()
  }

  function cycleTheme(): void {
    const index = THEME_ORDER.indexOf(theme.value)
    setTheme(THEME_ORDER[(index + 1) % THEME_ORDER.length] ?? 'system')
  }

  function toggleSidebar(): void {
    sidebarOpen.value = !sidebarOpen.value
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

  return {
    theme,
    sidebarOpen,
    backendStatus,
    backendVersion,
    backendError,
    isOnline,
    isDark,
    setTheme,
    cycleTheme,
    toggleSidebar,
    connect,
  }
})
