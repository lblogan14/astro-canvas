/**
 * Editor registry (design §8.3): expandable editors bound to one node, opened from
 * `NodeSpec.editor`, writing back to the node's params through the workflow store only.
 */
import type { Component } from 'vue'

import type { NodeSpec } from '@/api/types'

import ContinuumMaskEditor from './ContinuumMaskEditor.vue'
import LinePickerEditor from './LinePickerEditor.vue'
import MultispecViewerEditor from './MultispecViewerEditor.vue'
import RangeSelectEditor from './RangeSelectEditor.vue'
import ZAcceptEditor from './ZAcceptEditor.vue'

export type EditorId =
  'range-select' | 'line-picker' | 'continuum-mask' | 'z-accept' | 'multispec-viewer'

/** Tag used for every `preview.request` / `preview.compute` an editor issues. */
export const EDITOR_TAG = 'editor'

/** Props every editor receives. */
export interface EditorProps {
  nodeId: string
  spec: NodeSpec
}

const COMPONENTS: Record<EditorId, Component> = {
  'range-select': RangeSelectEditor,
  'line-picker': LinePickerEditor,
  'continuum-mask': ContinuumMaskEditor,
  'z-accept': ZAcceptEditor,
  'multispec-viewer': MultispecViewerEditor,
}

export function isEditorId(value: unknown): value is EditorId {
  return typeof value === 'string' && value in COMPONENTS
}

/** The editor id a node type declares, when the frontend has a component for it. */
export function editorFor(spec: NodeSpec | undefined): EditorId | null {
  const id = spec?.editor
  return isEditorId(id) ? id : null
}

export function editorComponent(id: EditorId): Component {
  return COMPONENTS[id]
}
