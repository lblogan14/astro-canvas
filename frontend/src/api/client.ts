import type {
  CancelResult,
  HealthResponse,
  NodeSpec,
  PackRecord,
  PortTypeSpec,
  RunAccepted,
  RunDetail,
  SniffResult,
  SystemInfo,
  UploadResult,
  WorkflowDoc,
  WorkflowSaved,
  WorkflowSettings,
  WorkflowStatus,
  WorkflowSummary,
  WorkflowVersionInfo,
  WorkspaceEntry,
  WorkspaceFileInfo,
  WorkspaceInfo,
  WorkspaceTree,
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

  // Phase 04: workspace files.
  getWorkspace: () => request<WorkspaceInfo>('/api/workspace'),
  selectWorkspace: (path: string, create = false) =>
    request<WorkspaceInfo>('/api/workspace/select', json('POST', { path, create })),
  getWorkspaceTree: (path = '', depth = 1, hidden = false) =>
    request<WorkspaceTree>(
      `/api/workspace/tree?path=${enc(path)}&depth=${depth}&hidden=${hidden ? 'true' : 'false'}`,
    ),
  getWorkspaceFileInfo: (path: string, hash = true) =>
    request<WorkspaceFileInfo>(
      `/api/workspace/info?path=${enc(path)}&hash=${hash ? 'true' : 'false'}`,
    ),
  sniffWorkspaceFile: (path: string) =>
    request<SniffResult>(`/api/workspace/sniff?path=${enc(path)}`),
  makeWorkspaceDir: (path: string) =>
    request<WorkspaceEntry>('/api/workspace/mkdir', json('POST', { path })),
  deleteWorkspacePath: (path: string, recursive = false) =>
    request<void>(
      `/api/workspace/file?path=${enc(path)}&recursive=${recursive ? 'true' : 'false'}`,
      { method: 'DELETE' },
    ),
  /** Download URL of a workspace file (the bearer token travels as a query parameter). */
  workspaceFileUrl: (path: string) => {
    const token = getToken()
    return `/api/workspace/file?path=${enc(path)}${token ? `&token=${enc(token)}` : ''}`
  },
  /** Full output of a node as an Arrow IPC stream (tables) or other formats. */
  outputUrl: (workflowId: string, nodeId: string, port: string, fmt: 'arrow' | 'json' | 'npz') =>
    `/api/outputs/${enc(nodeId)}/${enc(port)}?workflow_id=${enc(workflowId)}&fmt=${fmt}`,
  fetchOutputArrow: async (workflowId: string, nodeId: string, port: string) => {
    const response = await fetch(api.outputUrl(workflowId, nodeId, port, 'arrow'), {
      headers: authHeaders(),
    })
    if (!response.ok)
      throw new ApiError(response.status, `${response.status} ${response.statusText}`)
    return response.arrayBuffer()
  },
  uploadWorkspaceFile,
}

export type Api = typeof api

export type UploadConflict = 'error' | 'rename' | 'overwrite'

export interface UploadOptions {
  dir?: string
  filename?: string
  onConflict?: UploadConflict
  /** Progress in bytes (`loaded`, `total`). */
  onProgress?: (loaded: number, total: number) => void
  /** Files above this size are sent as ordered chunks (default 100 MB). */
  chunkThreshold?: number
  chunkSize?: number
  signal?: AbortSignal
}

const DEFAULT_CHUNK_THRESHOLD = 100 * 1024 * 1024
const DEFAULT_CHUNK_SIZE = 32 * 1024 * 1024

function randomUploadId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

/** One multipart POST with upload progress (XHR: `fetch` cannot report upload progress). */
function postForm(
  form: FormData,
  onProgress: ((loaded: number, total: number) => void) | undefined,
  signal: AbortSignal | undefined,
): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/workspace/upload')
    for (const [name, value] of Object.entries(authHeaders())) xhr.setRequestHeader(name, value)
    xhr.setRequestHeader('Accept', 'application/json')
    xhr.responseType = 'json'
    if (onProgress) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(event.loaded, event.total)
      }
    }
    xhr.onerror = () => reject(new ApiError(0, 'network error during upload'))
    xhr.onabort = () => reject(new ApiError(0, 'upload cancelled'))
    xhr.onload = () => {
      const body: unknown = xhr.response
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as UploadResult)
        return
      }
      const detail =
        typeof body === 'object' &&
        body !== null &&
        typeof (body as { detail?: unknown }).detail === 'string'
          ? (body as { detail: string }).detail
          : `${xhr.status} ${xhr.statusText}`
      reject(new ApiError(xhr.status, detail, body))
    }
    if (signal) {
      if (signal.aborted) xhr.abort()
      else signal.addEventListener('abort', () => xhr.abort(), { once: true })
    }
    xhr.send(form)
  })
}

/** Upload a file into the workspace, chunking large files (see `POST /api/workspace/upload`). */
export async function uploadWorkspaceFile(
  file: File,
  options: UploadOptions = {},
): Promise<UploadResult> {
  const threshold = options.chunkThreshold ?? DEFAULT_CHUNK_THRESHOLD
  const chunkSize = options.chunkSize ?? DEFAULT_CHUNK_SIZE
  const name = options.filename ?? file.name
  const common = (form: FormData): FormData => {
    form.set('dir', options.dir ?? 'uploads')
    form.set('filename', name)
    form.set('on_conflict', options.onConflict ?? 'error')
    return form
  }
  if (file.size <= threshold) {
    const form = common(new FormData())
    form.set('file', file, name)
    return postForm(form, options.onProgress, options.signal)
  }
  const uploadId = randomUploadId()
  const count = Math.ceil(file.size / chunkSize)
  let result: UploadResult | null = null
  for (let index = 0; index < count; index += 1) {
    const start = index * chunkSize
    const blob = file.slice(start, Math.min(file.size, start + chunkSize))
    const form = common(new FormData())
    form.set('file', blob, name)
    form.set('upload_id', uploadId)
    form.set('chunk_index', String(index))
    form.set('chunk_count', String(count))
    result = await postForm(
      form,
      options.onProgress
        ? (loaded, total) => options.onProgress?.(start + loaded, file.size + (total - blob.size))
        : undefined,
      options.signal,
    )
  }
  if (!result) throw new ApiError(0, 'empty upload')
  return result
}
