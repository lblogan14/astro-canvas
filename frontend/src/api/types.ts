/**
 * Wire types for the REST API, derived from the generated OpenAPI schema (`schema.d.ts`).
 * Regenerate with `task api:gen` after changing backend Pydantic models.
 */
import type { components } from './schema'

type Schemas = components['schemas']

export type HealthResponse = Schemas['HealthResponse']
export type PackInfo = Schemas['PackInfo']
export type SystemInfo = Schemas['SystemInfo']
export type NodeSpec = Schemas['NodeSpec']
export type PortSpec = Schemas['PortSpec']
export type ParamSpec = Schemas['ParamSpec']
export type PortTypeSpec = Schemas['PortTypeSpec']
export type PackRecord = Schemas['PackRecord']
export type PackLoadError = Schemas['PackLoadError']
export type Cost = NodeSpec['cost']
