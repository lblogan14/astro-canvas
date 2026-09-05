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
// Phase 05: pack-shipped workflow templates.
export type TemplateInfo = Schemas['TemplateInfo']

// Phase 02: workflows, runs and engine events (see docs/formats/workflow.md).
export type WorkflowDoc = Schemas['WorkflowDoc']
export type NodeDoc = Schemas['NodeDoc']
export type EdgeDoc = Schemas['EdgeDoc']
export type GroupDoc = Schemas['GroupDoc']
export type SubgraphDoc = Schemas['SubgraphDoc']
export type WorkflowSummary = Schemas['WorkflowSummary']
export type WorkflowSaved = Schemas['WorkflowSaved']
export type WorkflowStatus = Schemas['WorkflowStatus']
export type WorkflowSettings = Schemas['WorkflowSettings']
export type WorkflowVersionInfo = Schemas['WorkflowVersionInfo']
export type RunRequest = Schemas['RunRequest']
export type RunAccepted = Schemas['RunAccepted']
export type RunDetail = Schemas['RunDetail']
export type NodeRunInfo = Schemas['NodeRunInfo']
export type CancelResult = Schemas['CancelResult']
export type NodeStatus = Schemas['NodeStatus']
export type NodeIssue = Schemas['NodeIssue']
export type NodeState = NodeStatus['state']

/** `node_errors` as returned by the compiler: per node id, a list of issues. */
export type NodeErrors = Record<string, NodeIssue[]>

// Phase 04: workspace files.
export type WorkspaceInfo = Schemas['WorkspaceInfo']
export type WorkspaceEntry = Schemas['EntryModel']
export type WorkspaceTree = Schemas['TreeResponse']
export type WorkspaceFileInfo = Schemas['FileInfoModel']
export type UploadResult = Schemas['UploadResult']
export type SniffResult = Schemas['SniffResult']
export type SniffKind = SniffResult['kind']

// Phase 09: batch runs and subgraph promotion.
export type PromotedDoc = Schemas['PromotedDoc']
export type SubgraphPort = Schemas['SubgraphPort']
export type BatchRequest = Schemas['BatchRequest']
export type BatchInfo = Schemas['BatchInfo']
export type BatchSpec = Schemas['BatchSpec']
export type BatchBinding = Schemas['BatchBinding']
export type BatchCollect = Schemas['BatchCollect']
export type BatchResults = Schemas['BatchResults']
export type BatchRowInfo = Schemas['BatchRowInfo']
export type BatchRowState = BatchRowInfo['state']

// Phase 10: app modes (promoted params, pinned views, layouts) and workspace exports.
export type ViewDoc = Schemas['ViewDoc']
export type LayoutIssue = Schemas['LayoutIssue']
export type ExportRequest = Schemas['ExportRequest']
export type ExportResult = Schemas['ExportResult']
export type ExportedFile = Schemas['ExportedFile']

// Phase 11: pack manager, registry, bundles and the code-node trust gate.
export type ManagerStatus = Schemas['ManagerStatus']
export type ManagerSettings = Schemas['ManagerSettings']
export type ManagerSettingsUpdate = Schemas['ManagerSettingsUpdate']
export type SecurityLevel = ManagerSettings['security']
export type PackDetail = Schemas['PackDetail']
export type InstallPlan = Schemas['InstallPlan']
export type PackageChange = Schemas['PackageChange']
export type ChangeAction = PackageChange['action']
export type InstallResult = Schemas['InstallResult']
export type ImportTest = Schemas['ImportTest']
export type SnapshotInfo = Schemas['SnapshotInfo']
export type RegistryIndex = Schemas['RegistryIndex']
export type RegistryEntry = Schemas['RegistryEntry']
export type RegistryTemplate = Schemas['RegistryTemplate']
export type BundleManifest = Schemas['BundleManifest']
export type BundleImportResult = Schemas['BundleImportResult']
export type BundleLock = Schemas['BundleLock']
export type ImportedInput = Schemas['ImportedInput']
export type InputRef = Schemas['InputRef']
export type CodeSnippet = Schemas['CodeSnippet']
export type TrustRecord = Schemas['TrustRecord']
export type TrustReview = Schemas['TrustReview']
export type TrustDecision = TrustRecord['decision']

// Phase 12: user accounts on a lab server (`--auth users`).
export type AuthInfo = Schemas['AuthInfo']
export type User = Schemas['UserRead']
export type UserCreate = Schemas['UserCreate']
