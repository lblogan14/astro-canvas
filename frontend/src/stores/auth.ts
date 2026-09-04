/**
 * Who is using this server, when it has accounts at all (design §12).
 *
 * The SPA is the same bundle in every deployment tier, so it cannot know up front whether it
 * is talking to a desktop install (one token in the URL) or a lab server (`--auth users`).
 * `probe()` asks `/api/auth/info`: a 404 means the single-user server, and `mode` stays
 * `'single'` — nothing else in the app changes. Anything else means there is a login, and the
 * router keeps the canvas behind it until `user` is set.
 *
 * The session itself is an httpOnly cookie, so this store never sees or stores a credential.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { ApiError, api } from '@/api/client'
import type { AuthInfo, User } from '@/api/types'

/** `'single'` is a server without accounts; `'users'` is one with them. */
export type AuthMode = 'unknown' | 'single' | 'users'

function message(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return error instanceof Error ? error.message : String(error)
}

export const useAuthStore = defineStore('auth', () => {
  const mode = ref<AuthMode>('unknown')
  const info = ref<AuthInfo | null>(null)
  const user = ref<User | null>(null)
  const busy = ref(false)
  const error = ref<string | null>(null)

  /** True once the server has told us which kind it is. */
  const ready = computed(() => mode.value !== 'unknown')
  const requiresLogin = computed(() => mode.value === 'users' && user.value === null)
  /** The pack manager is admin-only on a shared server (design §12). */
  const canManagePacks = computed(() => mode.value !== 'users' || Boolean(user.value?.is_superuser))
  const canRegister = computed(() => info.value?.registration !== false)
  const providers = computed(() => info.value?.providers ?? [])
  const label = computed(() => user.value?.display_name || user.value?.email || '')

  /** Ask the server which tier it is, and restore an existing session if there is one. */
  async function probe(): Promise<AuthMode> {
    try {
      info.value = await api.getAuthInfo()
      mode.value = 'users'
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        mode.value = 'single'
        return mode.value
      }
      error.value = message(err)
      mode.value = 'single'
      return mode.value
    }
    await refresh()
    return mode.value
  }

  /** Re-read `/api/users/me`; a 401 just means nobody is logged in. */
  async function refresh(): Promise<User | null> {
    if (mode.value !== 'users') return null
    try {
      user.value = await api.getMe()
    } catch {
      user.value = null
    }
    return user.value
  }

  async function login(email: string, password: string): Promise<boolean> {
    busy.value = true
    error.value = null
    try {
      await api.login(email, password)
      await refresh()
      return user.value !== null
    } catch (err) {
      error.value = message(err)
      return false
    } finally {
      busy.value = false
    }
  }

  async function register(email: string, password: string, displayName = ''): Promise<boolean> {
    busy.value = true
    error.value = null
    try {
      await api.register(email, password, displayName)
    } catch (err) {
      error.value = message(err)
      busy.value = false
      return false
    }
    busy.value = false
    return login(email, password)
  }

  async function logout(): Promise<void> {
    try {
      await api.logout()
    } catch {
      // The cookie is gone either way; a failed logout must not trap the user in the app.
    }
    user.value = null
  }

  /** Hand the browser to an OAuth provider's consent page. */
  async function startOauth(provider: string): Promise<void> {
    error.value = null
    try {
      const { authorization_url: url } = await api.oauthStart(provider)
      window.location.assign(url)
    } catch (err) {
      error.value = message(err)
    }
  }

  return {
    mode,
    info,
    user,
    busy,
    error,
    ready,
    requiresLogin,
    canManagePacks,
    canRegister,
    providers,
    label,
    probe,
    refresh,
    login,
    register,
    logout,
    startOauth,
  }
})
