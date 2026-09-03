/**
 * Turn workspace files into loader nodes: sniff the file kind on the server, pick the matching
 * `core.io.load_*` node and add it with `path` set. Used by the canvas drop handler, the
 * Workspace panel and OS file drops (which upload first).
 */
import type { NodeSpec } from '@/api/types'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useUiStore } from '@/stores/ui'
import { type Pos, useWorkflowStore } from '@/stores/workflow'
import { useWorkspaceStore } from '@/stores/workspace'

export const FALLBACK_LOADER = 'core.io.load_table'

export interface LoaderPick {
  spec: NodeSpec
  kind: string
  fallback: boolean
}

/** Choose the loader node for a workspace file (server sniff, table as the fallback). */
export async function pickLoader(path: string): Promise<LoaderPick | null> {
  const schema = useNodesSchemaStore()
  const workspace = useWorkspaceStore()
  let kind = 'unknown'
  let nodeId: string | null = null
  try {
    const sniff = await workspace.sniff(path)
    kind = sniff.kind
    nodeId = sniff.node ?? null
  } catch {
    nodeId = null
  }
  const spec = (nodeId ? schema.byId[nodeId] : undefined) ?? schema.byId[FALLBACK_LOADER]
  if (!spec) return null
  return { spec, kind, fallback: nodeId === null || !schema.byId[nodeId] }
}

/** Add a loader node for `path` at `pos`; returns the new node id (or `null` when nothing fits). */
export async function addLoaderNode(path: string, pos: Pos): Promise<string | null> {
  const workflow = useWorkflowStore()
  const ui = useUiStore()
  if (!workflow.isOpen) return null
  const pick = await pickLoader(path)
  if (!pick) return null
  const name = path.split('/').pop() ?? path
  const id = workflow.addNode(pick.spec, pos, { params: { path }, title: name })
  ui.notify(
    pick.fallback
      ? translate('workspace.unknown_kind', { name })
      : translate('workspace.added_node', { node: pick.spec.name, name }),
    pick.fallback ? 'error' : 'info',
  )
  return id
}

/** Upload OS files into `dir`, then add one loader node per file, stacked below `pos`. */
export async function addUploadedFiles(
  files: FileList | File[],
  pos: Pos,
  dir = 'uploads',
): Promise<string[]> {
  const workspace = useWorkspaceStore()
  const jobs = await workspace.upload(files, dir, 'rename')
  const ids: string[] = []
  let offset = 0
  for (const job of jobs) {
    if (job.state !== 'done' || !job.path) continue
    const id = await addLoaderNode(job.path, [pos[0], pos[1] + offset])
    if (id) ids.push(id)
    offset += 220
  }
  return ids
}

type Translate = (key: string, params?: Record<string, unknown>) => string
let translate: Translate = (key) => key

/** The shell injects vue-i18n's `t` once at startup (keeps this module free of component context). */
export function setFileDropTranslator(fn: Translate): void {
  translate = fn
}
