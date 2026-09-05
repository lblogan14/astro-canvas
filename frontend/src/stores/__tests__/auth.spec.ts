import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { ApiError, api } from '@/api/client'
import type { AuthInfo, User } from '@/api/types'
import { useAuthStore } from '@/stores/auth'

vi.mock('@/api/client', async () => {
  const original = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return {
    ...original,
    api: {
      getAuthInfo: vi.fn<typeof original.api.getAuthInfo>(),
      getMe: vi.fn<typeof original.api.getMe>(),
      login: vi.fn<typeof original.api.login>(),
      logout: vi.fn<typeof original.api.logout>(),
      register: vi.fn<typeof original.api.register>(),
      oauthStart: vi.fn<typeof original.api.oauthStart>(),
    },
  }
})

const mocked = vi.mocked(api)

const INFO: AuthInfo = { mode: 'users', registration: true, providers: ['github'] }

function user(overrides: Partial<User> = {}): User {
  return {
    id: 'u1',
    email: 'student@lab.example',
    is_active: true,
    is_superuser: false,
    is_verified: true,
    display_name: '',
    ...overrides,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('probe', () => {
  it('settles on the single-user server when /api/auth/info is not there', async () => {
    mocked.getAuthInfo.mockRejectedValue(new ApiError(404, 'Not Found'))
    const auth = useAuthStore()

    expect(await auth.probe()).toBe('single')
    expect(auth.ready).toBe(true)
    expect(auth.requiresLogin).toBe(false)
    // A desktop install has no admin flag, so the manager stays reachable.
    expect(auth.canManagePacks).toBe(true)
    expect(mocked.getMe).not.toHaveBeenCalled()
  })

  it('reports a login is needed when nobody has one yet', async () => {
    mocked.getAuthInfo.mockResolvedValue(INFO)
    mocked.getMe.mockRejectedValue(new ApiError(401, 'Unauthorized'))
    const auth = useAuthStore()

    expect(await auth.probe()).toBe('users')
    expect(auth.requiresLogin).toBe(true)
    expect(auth.canManagePacks).toBe(false)
    expect(auth.providers).toEqual(['github'])
  })

  it('restores an existing cookie session', async () => {
    mocked.getAuthInfo.mockResolvedValue(INFO)
    mocked.getMe.mockResolvedValue(user({ display_name: 'A Student' }))
    const auth = useAuthStore()

    await auth.probe()
    expect(auth.requiresLogin).toBe(false)
    expect(auth.label).toBe('A Student')
  })

  it('treats an unauthorised probe as the single-user server, not as an error', async () => {
    // A token server rejects every /api call the SPA makes before the token is in the URL.
    mocked.getAuthInfo.mockRejectedValue(new ApiError(401, 'missing or invalid token'))
    const auth = useAuthStore()

    expect(await auth.probe()).toBe('single')
    expect(auth.error).toBeNull()
    expect(auth.requiresLogin).toBe(false)
  })

  it('falls back to the single-user server when the probe fails outright', async () => {
    mocked.getAuthInfo.mockRejectedValue(new TypeError('offline'))
    const auth = useAuthStore()

    expect(await auth.probe()).toBe('single')
    expect(auth.error).toBe('offline')
  })
})

describe('login', () => {
  beforeEach(async () => {
    mocked.getAuthInfo.mockResolvedValue(INFO)
    mocked.getMe.mockRejectedValue(new ApiError(401, 'Unauthorized'))
  })

  it('reads the session back after the cookie is set', async () => {
    const auth = useAuthStore()
    await auth.probe()
    mocked.getMe.mockResolvedValue(user())

    expect(await auth.login('student@lab.example', 'a good phrase')).toBe(true)
    expect(mocked.login).toHaveBeenCalledWith('student@lab.example', 'a good phrase')
    expect(auth.requiresLogin).toBe(false)
    expect(auth.busy).toBe(false)
  })

  it('keeps the server message when the password is wrong', async () => {
    const auth = useAuthStore()
    await auth.probe()
    mocked.login.mockRejectedValue(new ApiError(400, 'LOGIN_BAD_CREDENTIALS'))

    expect(await auth.login('student@lab.example', 'wrong')).toBe(false)
    expect(auth.error).toBe('LOGIN_BAD_CREDENTIALS')
    expect(auth.user).toBeNull()
  })

  it('signs up and then signs in', async () => {
    const auth = useAuthStore()
    await auth.probe()
    mocked.register.mockResolvedValue(user())
    mocked.getMe.mockResolvedValue(user())

    expect(await auth.register('student@lab.example', 'a good phrase', 'A Student')).toBe(true)
    expect(mocked.register).toHaveBeenCalledWith(
      'student@lab.example',
      'a good phrase',
      'A Student',
    )
    expect(mocked.login).toHaveBeenCalled()
  })

  it('stops at the sign-up error rather than trying to log in', async () => {
    const auth = useAuthStore()
    await auth.probe()
    mocked.register.mockRejectedValue(new ApiError(400, 'the password must be at least 8'))

    expect(await auth.register('student@lab.example', 'short')).toBe(false)
    expect(auth.error).toBe('the password must be at least 8')
    expect(mocked.login).not.toHaveBeenCalled()
  })
})

describe('admin flag', () => {
  it('unlocks the pack manager only for a superuser', async () => {
    mocked.getAuthInfo.mockResolvedValue(INFO)
    mocked.getMe.mockResolvedValue(user({ is_superuser: true, email: 'pi@lab.example' }))
    const auth = useAuthStore()

    await auth.probe()
    expect(auth.canManagePacks).toBe(true)
    expect(auth.label).toBe('pi@lab.example')
  })
})

describe('logout', () => {
  it('clears the user even when the request fails', async () => {
    mocked.getAuthInfo.mockResolvedValue(INFO)
    mocked.getMe.mockResolvedValue(user())
    const auth = useAuthStore()
    await auth.probe()
    mocked.logout.mockRejectedValue(new ApiError(500, 'boom'))

    await auth.logout()
    expect(auth.user).toBeNull()
    expect(auth.requiresLogin).toBe(true)
  })
})

describe('oauth', () => {
  it('hands the browser to the provider', async () => {
    mocked.getAuthInfo.mockResolvedValue(INFO)
    mocked.getMe.mockRejectedValue(new ApiError(401, 'Unauthorized'))
    mocked.oauthStart.mockResolvedValue({ authorization_url: 'https://github.test/authorize' })
    const assign = vi.fn<(url: string) => void>()
    vi.spyOn(window, 'location', 'get').mockReturnValue({
      ...window.location,
      assign,
    } as unknown as Location)

    const auth = useAuthStore()
    await auth.probe()
    await auth.startOauth('github')
    expect(assign).toHaveBeenCalledWith('https://github.test/authorize')
  })

  it('surfaces a provider that is not configured', async () => {
    mocked.getAuthInfo.mockResolvedValue(INFO)
    mocked.getMe.mockRejectedValue(new ApiError(401, 'Unauthorized'))
    mocked.oauthStart.mockRejectedValue(new ApiError(404, 'Not Found'))

    const auth = useAuthStore()
    await auth.probe()
    await auth.startOauth('gitlab')
    expect(auth.error).toBe('Not Found')
  })
})
