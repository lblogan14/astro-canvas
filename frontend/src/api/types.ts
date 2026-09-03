/**
 * Wire types mirroring the backend Pydantic models in `astro_canvas.server.health`.
 * Hand-written for phase 00; a generated client replaces this file once the API grows.
 */

export interface HealthResponse {
  status: 'ok'
  version: string
}

export interface PackInfo {
  name: string
  version: string
  enabled: boolean
}

export interface SystemInfo {
  version: string
  python: string
  platform: string
  workspace: string
  workspace_exists: boolean
  disk_free_bytes: number
  disk_total_bytes: number
  packs: PackInfo[]
}
