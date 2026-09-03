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

// Phase 02: workflows, runs and engine events (see docs/formats/workflow.md).
export type WorkflowDoc = Schemas['WorkflowDoc']
export type NodeDoc = Schemas['NodeDoc']
export type EdgeDoc = Schemas['EdgeDoc']
export type SubgraphDoc = Schemas['SubgraphDoc']
export type WorkflowSummary = Schemas['WorkflowSummary']
export type WorkflowSaved = Schemas['WorkflowSaved']
export type WorkflowStatus = Schemas['WorkflowStatus']
export type WorkflowVersionInfo = Schemas['WorkflowVersionInfo']
export type RunRequest = Schemas['RunRequest']
export type RunAccepted = Schemas['RunAccepted']
export type RunDetail = Schemas['RunDetail']
export type NodeRunInfo = Schemas['NodeRunInfo']
export type CancelResult = Schemas['CancelResult']
export type NodeStatus = Schemas['NodeStatus']
export type NodeIssue = Schemas['NodeIssue']
export type NodeState = NodeStatus['state']
