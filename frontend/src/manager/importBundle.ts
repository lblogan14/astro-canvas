/**
 * Importing a `.acw`: upload, report what needs fixing, open the workflow.
 *
 * The import endpoint stores the workflow either way, so the user can always look at what
 * arrived; this layer turns the result's three "still needs attention" channels — missing packs,
 * missing or changed input files, and the quarantine flag — into notifications and lands on the
 * new workflow.
 */
import type { BundleImportResult } from '@/api/types'
import { api } from '@/api/client'

export const BUNDLE_SUFFIX = '.acw'

export function isBundleFile(file: { name: string }): boolean {
  return file.name.toLowerCase().endsWith(BUNDLE_SUFFIX)
}

/** The first `.acw` in a drop, or `null` when the drop carries none. */
export function bundleFrom(files: FileList | File[] | null | undefined): File | null {
  if (!files) return null
  for (const file of Array.from(files)) if (isBundleFile(file)) return file
  return null
}

export interface ImportNotice {
  message: string
  kind: 'info' | 'error'
}

type Translate = (key: string, params?: Record<string, unknown> | number) => string

/** Everything the user should know about an import, most important first. */
export function importNotices(result: BundleImportResult, t: Translate): ImportNotice[] {
  const notices: ImportNotice[] = []
  const missingPacks = Object.keys(result.missing_packs ?? {})
  if (missingPacks.length) {
    notices.push({
      message: t('bundle.missing_packs', { names: missingPacks.join(', ') }),
      kind: 'error',
    })
  }
  const inputs = result.inputs ?? []
  const missing = inputs.filter((input) => input.status === 'missing')
  if (missing.length) {
    notices.push({ message: t('bundle.missing_inputs', missing.length), kind: 'error' })
  }
  const changed = inputs.filter((input) => input.status === 'hash_mismatch')
  if (changed.length) {
    notices.push({ message: t('bundle.hash_mismatch', changed.length), kind: 'error' })
  }
  const restored = inputs.filter((input) => input.status === 'restored')
  if (restored.length) {
    notices.push({ message: t('bundle.restored_inputs', restored.length), kind: 'info' })
  }
  notices.push({ message: t('bundle.imported', { name: result.name }), kind: 'info' })
  return notices
}

export async function importBundleFile(file: File | Blob, name = 'workflow.acw') {
  return api.importBundle(file, name)
}

type Notify = (message: string, kind?: 'info' | 'error') => void

let translate: Translate = (key) => String(key)
let notify: Notify = () => {}
let open: (workflowId: string) => void = () => {}

/**
 * The shell injects vue-i18n's `t`, the toast and the router push once at startup, so this
 * module stays usable from plain handlers (the canvas drop target) without component context.
 */
export function setBundleHandlers(handlers: {
  t: Translate
  notify: Notify
  open: (workflowId: string) => void
}): void {
  translate = handlers.t
  notify = handlers.notify
  open = handlers.open
}

/** Import a dropped or chosen `.acw`, report what needs fixing and open the workflow. */
export async function dropBundle(file: File): Promise<BundleImportResult | null> {
  try {
    const result = await importBundleFile(file, file.name)
    for (const notice of importNotices(result, translate)) notify(notice.message, notice.kind)
    open(result.workflow_id)
    return result
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    notify(translate('bundle.import_failed', { message }), 'error')
    return null
  }
}
