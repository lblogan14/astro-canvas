/**
 * Layout plumbing shared by App, Wizard and Dashboard modes (design 7.1, 8.4).
 *
 * A layout is a list of **items**, each a ref to a promoted param (`"promoted:<node>.<param>"`)
 * or a pinned view (`"view:<id>"`). This module is the single parser for those refs, the reader
 * that turns an unknown `layouts.<name>` section into a typed one, and the source of the default
 * layout a document without a section gets — so a template that only promotes params still opens
 * into a usable form. Everything here is pure: modes bind it to the stores.
 */
import type { NodeDoc, NodeSpec, ParamSpec, PromotedDoc, ViewDoc } from '@/api/types'
import { type PreviewId, isPreviewId } from '@/previews'

export const PROMOTED_PREFIX = 'promoted:'
export const VIEW_PREFIX = 'view:'

/** Fallback section/step title for promoted params without a `group`. */
export const UNGROUPED = 'Parameters'
/** Section/step title the default layouts give the views. */
export const RESULTS = 'Results'

export type ItemKind = 'promoted' | 'view'

export interface ItemRef {
  kind: ItemKind
  /** `"<node>.<param>"` for a promoted param, the view id for a view. */
  ref: string
}

export function promotedItem(ref: string): string {
  return `${PROMOTED_PREFIX}${ref}`
}

export function viewItem(viewId: string): string {
  return `${VIEW_PREFIX}${viewId}`
}

export function itemText(item: ItemRef): string {
  return item.kind === 'promoted' ? promotedItem(item.ref) : viewItem(item.ref)
}

/** `"promoted:n2.z"` / `"view:v1"` (or the `{promoted}`/`{view}`/`{ref}` object form). */
export function parseItem(raw: unknown): ItemRef | null {
  let text = raw
  if (raw && typeof raw === 'object') {
    const entry = raw as Record<string, unknown>
    if (typeof entry['promoted'] === 'string' && entry['promoted'])
      return { kind: 'promoted', ref: entry['promoted'] }
    if (typeof entry['view'] === 'string' && entry['view'])
      return { kind: 'view', ref: entry['view'] }
    text = entry['ref']
  }
  if (typeof text !== 'string') return null
  if (text.startsWith(PROMOTED_PREFIX)) {
    const ref = text.slice(PROMOTED_PREFIX.length)
    return ref.includes('.') ? { kind: 'promoted', ref } : null
  }
  if (text.startsWith(VIEW_PREFIX)) {
    const ref = text.slice(VIEW_PREFIX.length)
    return ref ? { kind: 'view', ref } : null
  }
  return null
}

/** Split a promoted ref into its node id and param name (the node id may contain `/`). */
export function splitRef(ref: string): { node: string; param: string } {
  const dot = ref.lastIndexOf('.')
  return dot < 0 ? { node: ref, param: '' } : { node: ref.slice(0, dot), param: ref.slice(dot + 1) }
}

// --- sections ----------------------------------------------------------------------------------

export interface AppSection {
  title: string
  items: string[]
  description?: string | null
}

export interface AppLayout {
  sections: AppSection[]
}

export interface WizardStep {
  title: string
  items: string[]
  description?: string | null
  /** Nodes that must be `done` before Next; empty means "the nodes the items touch". */
  nodes?: string[]
  optional?: boolean
}

export interface WizardLayout {
  steps: WizardStep[]
}

export interface DashboardTile {
  ref: string
  x: number
  y: number
  w: number
  h: number
}

export interface DashboardLayout {
  cols: number
  row_height: number
  items: DashboardTile[]
}

export const DASHBOARD_COLS = 12
export const DASHBOARD_ROW_HEIGHT = 48

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function itemStrings(value: unknown): string[] {
  const out: string[] = []
  for (const raw of asArray(value)) {
    const item = parseItem(raw)
    if (item) out.push(itemText(item))
  }
  return out
}

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function int(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.round(value) : fallback
}

/** Read `layouts.app`; `null` when the document has no App section. */
export function readAppLayout(layouts: Record<string, unknown> | undefined): AppLayout | null {
  const section = asRecord(layouts?.['app'])
  if (!section) return null
  const sections: AppSection[] = []
  for (const raw of asArray(section['sections'])) {
    const entry = asRecord(raw)
    if (!entry) continue
    sections.push({
      title: text(entry['title']),
      items: itemStrings(entry['items']),
      description: typeof entry['description'] === 'string' ? entry['description'] : null,
    })
  }
  return { sections }
}

/** Read `layouts.wizard`; `null` when the document has no Wizard section. */
export function readWizardLayout(
  layouts: Record<string, unknown> | undefined,
): WizardLayout | null {
  const section = asRecord(layouts?.['wizard'])
  if (!section) return null
  const steps: WizardStep[] = []
  for (const raw of asArray(section['steps'])) {
    const entry = asRecord(raw)
    if (!entry) continue
    steps.push({
      title: text(entry['title']),
      items: itemStrings(entry['items']),
      description: typeof entry['description'] === 'string' ? entry['description'] : null,
      nodes: asArray(entry['nodes']).filter((n): n is string => typeof n === 'string'),
      optional: entry['optional'] === true,
    })
  }
  return { steps }
}

/** Read `layouts.dashboard`; `null` when the document has no Dashboard section. */
export function readDashboardLayout(
  layouts: Record<string, unknown> | undefined,
): DashboardLayout | null {
  const section = asRecord(layouts?.['dashboard'])
  if (!section) return null
  const items: DashboardTile[] = []
  for (const raw of asArray(section['items'])) {
    const entry = asRecord(raw)
    const item = parseItem(entry ?? raw)
    if (!item) continue
    items.push({
      ref: itemText(item),
      x: int(entry?.['x'], 0),
      y: int(entry?.['y'], 0),
      w: Math.max(1, int(entry?.['w'], 6)),
      h: Math.max(1, int(entry?.['h'], 5)),
    })
  }
  return {
    cols: Math.min(48, Math.max(1, int(section['cols'], DASHBOARD_COLS))),
    row_height: Math.min(400, Math.max(8, int(section['row_height'], DASHBOARD_ROW_HEIGHT))),
    items,
  }
}

// --- default layouts ---------------------------------------------------------------------------

/** Promoted params grouped by `group`, groups in `order` and first-appearance sequence. */
export function groupPromoted(
  promoted: readonly PromotedDoc[],
): { title: string; entries: PromotedDoc[] }[] {
  const groups: { title: string; entries: PromotedDoc[] }[] = []
  for (const entry of promoted) {
    const title = entry.group?.trim() || UNGROUPED
    const bucket = groups.find((g) => g.title === title)
    if (bucket) bucket.entries.push(entry)
    else groups.push({ title, entries: [entry] })
  }
  return groups
}

/** `"<node>.<param>"`: how layouts, batch columns and subgraph instances address a param. */
export function refOf(entry: { node: string; param: string }): string {
  return `${entry.node}.${entry.param}`
}

/**
 * The App layout a document without `layouts.app` gets: one section per promoted group, plus a
 * trailing section holding the views (App mode hoists those into its views column).
 */
export function defaultAppLayout(
  promoted: readonly PromotedDoc[],
  views: readonly ViewDoc[],
): AppLayout {
  const sections: AppSection[] = groupPromoted(promoted).map((group) => ({
    title: group.title,
    items: group.entries.map((entry) => promotedItem(refOf(entry))),
  }))
  if (views.length > 0)
    sections.push({ title: RESULTS, items: views.map((view) => viewItem(view.id)) })
  return { sections }
}

/**
 * The Wizard a document without `layouts.wizard` gets: one step per promoted group in order,
 * then a results step with the views (design 8.5's Load → … → Save tabs).
 */
export function defaultWizardLayout(
  promoted: readonly PromotedDoc[],
  views: readonly ViewDoc[],
): WizardLayout {
  const steps: WizardStep[] = groupPromoted(promoted).map((group) => ({
    title: group.title,
    items: group.entries.map((entry) => promotedItem(refOf(entry))),
    nodes: [...new Set(group.entries.map((entry) => entry.node))],
  }))
  if (views.length > 0) {
    steps.push({
      title: RESULTS,
      items: views.map((view) => viewItem(view.id)),
      nodes: [...new Set(views.map((view) => view.node))],
    })
  }
  return { steps }
}

/**
 * The Dashboard a document without `layouts.dashboard` gets: promoted params as narrow tiles
 * across the top, then the views two to a row.
 */
export function defaultDashboardLayout(
  promoted: readonly PromotedDoc[],
  views: readonly ViewDoc[],
): DashboardLayout {
  const items: DashboardTile[] = []
  const paramW = 3
  const paramH = 2
  promoted.forEach((entry, index) => {
    const perRow = Math.floor(DASHBOARD_COLS / paramW)
    items.push({
      ref: promotedItem(refOf(entry)),
      x: (index % perRow) * paramW,
      y: Math.floor(index / perRow) * paramH,
      w: paramW,
      h: paramH,
    })
  })
  const paramRows = promoted.length
    ? Math.ceil(promoted.length / Math.floor(DASHBOARD_COLS / paramW)) * paramH
    : 0
  const viewW = DASHBOARD_COLS / 2
  const viewH = 5
  views.forEach((view, index) => {
    items.push({
      ref: viewItem(view.id),
      x: (index % 2) * viewW,
      y: paramRows + Math.floor(index / 2) * viewH,
      w: viewW,
      h: viewH,
    })
  })
  return { cols: DASHBOARD_COLS, row_height: DASHBOARD_ROW_HEIGHT, items }
}

/** Remove one item (`"promoted:…"` / `"view:…"`) from every layout section that carries it. */
export function dropRefFromLayouts(
  layouts: Record<string, unknown>,
  item: string,
): Record<string, unknown> {
  const target = parseItem(item)
  if (!target) return layouts
  const keep = (raw: unknown): boolean => {
    const parsed = parseItem(raw)
    return !parsed || parsed.kind !== target.kind || parsed.ref !== target.ref
  }
  const next: Record<string, unknown> = { ...layouts }
  for (const [name, section] of Object.entries(next)) {
    const entry = asRecord(section)
    if (!entry) continue
    const copy: Record<string, unknown> = { ...entry }
    let changed = false
    for (const key of ['sections', 'steps']) {
      const groups = asArray(copy[key])
      if (groups.length === 0) continue
      copy[key] = groups.map((raw) => {
        const group = asRecord(raw)
        if (!group) return raw
        const items = asArray(group['items'])
        const kept = items.filter(keep)
        if (kept.length === items.length) return raw
        changed = true
        return { ...group, items: kept }
      })
    }
    // Dashboard tiles and batch columns are flat item lists.
    for (const key of ['items', 'columns']) {
      const tiles = asArray(copy[key])
      if (tiles.length === 0) continue
      const kept = tiles.filter(keep)
      if (kept.length !== tiles.length) {
        copy[key] = kept
        changed = true
      }
    }
    if (changed) next[name] = copy
  }
  return next
}

// --- resolution --------------------------------------------------------------------------------

export interface ResolveContext {
  promoted: readonly PromotedDoc[]
  views: readonly ViewDoc[]
  nodes: Readonly<Record<string, NodeDoc>>
  specs: Readonly<Record<string, NodeSpec>>
}

export interface ResolvedPromoted {
  kind: 'promoted'
  key: string
  ref: string
  node: string
  param: string
  entry: PromotedDoc
  spec: ParamSpec | undefined
  /** The promoted label, else the param's own label. */
  label: string
  help: string | null
  value: unknown
  linked: boolean
  disabled: boolean
}

export interface ResolvedView {
  kind: 'view'
  key: string
  ref: string
  view: ViewDoc
  node: string
  port: string
  label: string
}

export type ResolvedItem = ResolvedPromoted | ResolvedView

function helpOf(entry: PromotedDoc, spec: ParamSpec | undefined): string | null {
  const help = (entry as Record<string, unknown>)['help']
  if (typeof help === 'string' && help.trim()) return help
  return spec?.description || null
}

/** Resolve one layout item against the document; `null` when its target is gone. */
export function resolveItem(raw: unknown, ctx: ResolveContext): ResolvedItem | null {
  const item = parseItem(raw)
  if (!item) return null
  if (item.kind === 'promoted') {
    const entry = ctx.promoted.find((p) => refOf(p) === item.ref)
    if (!entry) return null
    const node = ctx.nodes[entry.node]
    if (!node) return null
    const spec = ctx.specs[node.type]?.params.find((p) => p.name === entry.param)
    return {
      kind: 'promoted',
      key: promotedItem(item.ref),
      ref: item.ref,
      node: entry.node,
      param: entry.param,
      entry,
      spec,
      label: entry.label?.trim() || spec?.label || entry.param,
      help: helpOf(entry, spec),
      value: (node.params ?? {})[entry.param],
      linked: (node.linked ?? []).includes(entry.param),
      disabled: node.disabled === true,
    }
  }
  const view = ctx.views.find((v) => v.id === item.ref)
  if (!view || !ctx.nodes[view.node]) return null
  const node = ctx.nodes[view.node]
  const spec = node ? ctx.specs[node.type] : undefined
  return {
    kind: 'view',
    key: viewItem(view.id),
    ref: view.id,
    view,
    node: view.node,
    port: view.port,
    label: text((view as Record<string, unknown>)['label']) || node?.title || spec?.name || view.id,
  }
}

/** Resolve a list of items, reporting the refs whose targets no longer exist. */
export function resolveItems(
  items: readonly unknown[],
  ctx: ResolveContext,
): { resolved: ResolvedItem[]; missing: string[] } {
  const resolved: ResolvedItem[] = []
  const missing: string[] = []
  for (const raw of items) {
    const item = resolveItem(raw, ctx)
    if (item) resolved.push(item)
    else {
      const parsed = parseItem(raw)
      missing.push(parsed ? itemText(parsed) : String(raw))
    }
  }
  return { resolved, missing }
}

/** Backend view `kind` hints (templates hand-write these) mapped onto preview ids. */
const KIND_ALIASES: Record<string, PreviewId> = {
  spectrum: 'spectrum-thumb',
  'spectrum-1d': 'spectrum-thumb',
  stack: 'spectrum-stack',
  table: 'table-head',
  'ew-summary': 'kv-tile',
  summary: 'kv-tile',
  image: 'image-thumb',
  cube: 'cube-thumb',
  moments: 'moment-thumbs',
}

/**
 * The preview renderer a view should use: what the running node actually produced wins, and the
 * document's `kind` is only a hint for views whose node has not run yet.
 */
export function viewRenderer(view: ViewDoc, live: PreviewId | null): PreviewId | null {
  if (live) return live
  const kind = view.kind ?? undefined
  if (!kind) return null
  if (isPreviewId(kind)) return kind
  return KIND_ALIASES[kind] ?? null
}
