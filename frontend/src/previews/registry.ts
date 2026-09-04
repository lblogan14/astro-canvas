/**
 * Preview renderer registry (design §5.2, §8.2): picks the inline renderer for a node output from
 * the node's `preview` id, the port type's `summary_renderer`, or the summary's shape.
 */
import type { Component } from 'vue'

import type { NodeSpec, PortTypeSpec } from '@/api/types'
import { isTileSummary } from '@/lib/tile'

import CandidatesTable from './renderers/CandidatesTable.vue'
import CubeThumb from './renderers/CubeThumb.vue'
import FigurePreview from './renderers/FigurePreview.vue'
import FileChip from './renderers/FileChip.vue'
import ImageThumb from './renderers/ImageThumb.vue'
import KvTile from './renderers/KvTile.vue'
import MomentThumbs from './renderers/MomentThumbs.vue'
import MultispecThumb from './renderers/MultispecThumb.vue'
import SpectrumThumb from './renderers/SpectrumThumb.vue'
import TableHead from './renderers/TableHead.vue'
import ValueChip from './renderers/ValueChip.vue'
import ZFindCurve from './renderers/ZFindCurve.vue'

export type PreviewId =
  | 'spectrum-thumb'
  | 'spectrum-stack'
  | 'image-thumb'
  | 'cube-thumb'
  | 'table-head'
  | 'kv-tile'
  | 'figure'
  | 'file-chip'
  | 'value-chip'
  | 'zfind-curve'
  | 'candidates-table'
  | 'multispec-thumb'
  | 'moment-thumbs'

/** Props every renderer receives. */
export interface PreviewProps {
  nodeId: string
  port: string
  typeId: string
  summary: Record<string, unknown>
  /** Available width in CSS pixels (drives the point/tile budget). */
  width: number
}

const COMPONENTS: Record<PreviewId, Component> = {
  'spectrum-thumb': SpectrumThumb,
  'spectrum-stack': SpectrumThumb,
  'image-thumb': ImageThumb,
  'cube-thumb': CubeThumb,
  'table-head': TableHead,
  'kv-tile': KvTile,
  figure: FigurePreview,
  'file-chip': FileChip,
  'value-chip': ValueChip,
  'zfind-curve': ZFindCurve,
  'candidates-table': CandidatesTable,
  'multispec-thumb': MultispecThumb,
  'moment-thumbs': MomentThumbs,
}

/** Backend `summary_renderer` ids → frontend preview ids. */
const RENDERER_ALIASES: Record<string, PreviewId> = {
  'spectrum-thumb': 'spectrum-thumb',
  'spectrum-stack': 'spectrum-stack',
  'image-thumb': 'image-thumb',
  'cube-thumb': 'cube-thumb',
  'table-grid': 'table-head',
  'table-head': 'table-head',
  'kv-tile': 'kv-tile',
  chip: 'kv-tile',
  'linelist-chip': 'kv-tile',
  'continuum-thumb': 'kv-tile',
  'region-overlay': 'kv-tile',
  figure: 'figure',
  'file-chip': 'file-chip',
  'value-chip': 'value-chip',
  'type-name': 'value-chip',
  'zfind-curve': 'zfind-curve',
  'candidates-table': 'candidates-table',
  'multispec-thumb': 'multispec-thumb',
  'moment-thumbs': 'moment-thumbs',
}

/**
 * Renderers that have a full-size view in the viewer sheet. The four rbcodes renderers below
 * have no bespoke viewer branch: the sheet re-renders the inline component at full width, which
 * is enough because each one already scales with `width` (and Dashboard tiles rely on the same
 * property).
 */
export const EXPANDABLE: ReadonlySet<PreviewId> = new Set<PreviewId>([
  'spectrum-thumb',
  'spectrum-stack',
  'image-thumb',
  'cube-thumb',
  'table-head',
  'figure',
  'kv-tile',
  'zfind-curve',
  'candidates-table',
  'multispec-thumb',
  'moment-thumbs',
])

/** Expandable renderers the viewer shows by scaling the inline renderer up. */
export const SCALED: ReadonlySet<PreviewId> = new Set<PreviewId>([
  'zfind-curve',
  'candidates-table',
  'multispec-thumb',
  'moment-thumbs',
])

function isMapEntry(value: unknown): boolean {
  if (typeof value !== 'object' || value === null) return false
  const entry = value as Record<string, unknown>
  return typeof entry['key'] === 'string' && isTileSummary(entry['tile'])
}

export function isPreviewId(value: unknown): value is PreviewId {
  return typeof value === 'string' && value in COMPONENTS
}

/** Guess a renderer from the payload when no metadata says otherwise. */
export function rendererFromSummary(summary: Record<string, unknown>): PreviewId {
  if (Array.isArray(summary['wave']) && Array.isArray(summary['flux'])) return 'spectrum-thumb'
  if (Array.isArray(summary['panels']) && Array.isArray(summary['absorbers']))
    return 'multispec-thumb'
  if (Array.isArray(summary['maps']) && summary['maps'].some((m) => isMapEntry(m)))
    return 'moment-thumbs'
  if (Array.isArray(summary['z']) && Array.isArray(summary['curves'])) return 'zfind-curve'
  if (Array.isArray(summary['rows']) && 'accepted' in summary) return 'candidates-table'
  if (isTileSummary(summary['tile'])) {
    return Array.isArray(summary['shape']) && summary['shape'].length === 3
      ? 'cube-thumb'
      : 'image-thumb'
  }
  if (Array.isArray(summary['columns']) && typeof summary['head'] === 'object') return 'table-head'
  if (summary['kind'] === 'plotly' || summary['kind'] === 'png') return 'figure'
  const data = summary['data']
  if (typeof data === 'object' && data !== null) {
    const record = data as Record<string, unknown>
    if (typeof record['path'] === 'string' && 'size' in record) return 'file-chip'
    const keys = Object.keys(record)
    if (keys.length === 1 && keys[0] === 'value' && typeof record['value'] !== 'object')
      return 'value-chip'
    return 'kv-tile'
  }
  return 'value-chip'
}

/** Pick the renderer for `port` of a node. */
export function rendererFor(
  spec: NodeSpec | undefined,
  typeSpec: PortTypeSpec | undefined,
  summary: Record<string, unknown> | undefined,
): PreviewId {
  if (spec?.preview && isPreviewId(spec.preview)) return spec.preview
  const alias = typeSpec?.summary_renderer ? RENDERER_ALIASES[typeSpec.summary_renderer] : undefined
  if (alias) return alias
  return summary ? rendererFromSummary(summary) : 'value-chip'
}

export function previewComponent(id: PreviewId): Component {
  return COMPONENTS[id]
}

/** Point/tile budget for a preview of the given width (re-requested on resize). */
export function previewBudget(id: PreviewId, width: number): number | null {
  const w = Math.max(1, Math.round(width))
  switch (id) {
    case 'spectrum-thumb':
    case 'spectrum-stack':
    case 'zfind-curve':
    case 'multispec-thumb':
      return Math.min(4000, Math.max(200, w * 2))
    case 'image-thumb':
    case 'cube-thumb':
      return Math.min(512, Math.max(64, w))
    // Three maps share the node's width, so each tile only needs a third of it.
    case 'moment-thumbs':
      return Math.min(256, Math.max(48, Math.round(w / 3)))
    default:
      return null
  }
}
