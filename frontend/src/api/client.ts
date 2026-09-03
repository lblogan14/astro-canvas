import type { HealthResponse, SystemInfo } from './types'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { Accept: 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`)
  }
  return (await response.json()) as T
}

/** Thin typed wrapper over the REST API. Paths are relative so the Vite proxy and the wheel both work. */
export const api = {
  getHealth: () => request<HealthResponse>('/api/health'),
  getSystem: () => request<SystemInfo>('/api/system'),
}
