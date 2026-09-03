import type {
  CancelResult,
  HealthResponse,
  NodeSpec,
  PackRecord,
  PortTypeSpec,
  RunAccepted,
  RunDetail,
  SystemInfo,
  WorkflowDoc,
  WorkflowSaved,
  WorkflowSettings,
  WorkflowStatus,
  WorkflowSummary,
  WorkflowVersionInfo,
} from './types'

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

const TOKEN_KEY = 'astro-canvas-token'

/**
 * The bearer token the backend generated at startup. The launcher opens the app with
 * `?token=…`; it is moved into `sessionStorage` so reloads keep working (design §6.5).
 */
export function getToken(): string | null {
  try {
    const url = new URL(window.location.href)
    const fromQuery = url.searchParams.get('token')
    if (fromQuery) {
      window.sessionStorage.setItem(TOKEN_KEY, fromQuery)
      url.searchParams.delete('token')
      window.history.replaceState(window.history.state, '', url.toString())
      return fromQuery
    }
    return window.sessionStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** `ws://…/ws?token=…` for the same origin the SPA was served from. */
export function wsUrl(clientId?: string): string {
  const url = new URL('/ws', window.location.href)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  const token = getToken()
  if (token) url.searchParams.set('token', token)
  if (clientId) url.searchParams.set('client_id', clientId)
  return url.toString()
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { Accept: 'application/json', ...authHeaders(), ...init?.headers },
  })
  if (!response.ok) {
    let detail: unknown
    try {
      detail = (await response.json()) as unknown
    } catch {
      detail = undefined
    }
    const message =
      typeof detail === 'object' &&
      detail !== null &&
      typeof (detail as { detail?: unknown }).detail === 'string'
        ? (detail as { detail: string }).detail
        : `${response.status} ${response.statusText}`
    throw new ApiError(response.status, message, detail)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

function json(method: string, body: unknown): RequestInit {
  return {
    method,
    body: JSON.stringify(body),
    headers: { 'Content-Type': 'application/json' },
  }
}

const enc = encodeURIComponent

/** Thin typed wrapper over the REST API. Paths are relative so the Vite proxy and the wheel both work. */
export const api = {
  getHealth: () => request<HealthResponse>('/api/health'),
  getSystem: () => request<SystemInfo>('/api/system'),
  getNodes: (category?: string) =>
    request<NodeSpec[]>(
      category === undefined ? '/api/nodes' : `/api/nodes?category=${enc(category)}`,
    ),
  getNode: (id: string) => request<NodeSpec>(`/api/nodes/${enc(id)}`),
  getTypes: () => request<PortTypeSpec[]>('/api/types'),
  getPacks: () => request<PackRecord[]>('/api/packs'),

  listWorkflows: () => request<WorkflowSummary[]>('/api/workflows'),
  createWorkflow: (doc: WorkflowDoc) => request<WorkflowSaved>('/api/workflows', json('POST', doc)),
  getWorkflow: (id: string) => request<WorkflowDoc>(`/api/workflows/${enc(id)}`),
  putWorkflow: (doc: WorkflowDoc) =>
    request<WorkflowSaved>(`/api/workflows/${enc(doc.id ?? '')}`, json('PUT', doc)),
  deleteWorkflow: (id: string) => request<void>(`/api/workflows/${enc(id)}`, { method: 'DELETE' }),
  listVersions: (id: string) =>
    request<WorkflowVersionInfo[]>(`/api/workflows/${enc(id)}/versions`),
  getVersion: (id: string, versionId: number) =>
    request<WorkflowDoc>(`/api/workflows/${enc(id)}/versions/${versionId}`),
  getWorkflowStatus: (id: string) => request<WorkflowStatus>(`/api/workflows/${enc(id)}/status`),
  getWorkflowSettings: (id: string) =>
    request<WorkflowSettings>(`/api/workflows/${enc(id)}/settings`),
  setWorkflowSettings: (id: string, settings: WorkflowSettings) =>
    request<WorkflowSettings>(`/api/workflows/${enc(id)}/settings`, json('POST', settings)),

  startRun: (id: string, targets?: string[] | null) =>
    request<RunAccepted>(
      `/api/workflows/${enc(id)}/run`,
      json('POST', { targets: targets ?? null }),
    ),
  listRuns: (workflowId?: string) =>
    request<RunDetail[]>(
      workflowId === undefined ? '/api/runs' : `/api/runs?workflow_id=${enc(workflowId)}`,
    ),
  getRun: (runId: string) => request<RunDetail>(`/api/runs/${enc(runId)}`),
  cancelRun: (runId: string) =>
    request<CancelResult>(`/api/runs/${enc(runId)}/cancel`, { method: 'POST' }),
}

export type Api = typeof api
