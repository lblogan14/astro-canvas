/**
 * Keyboard shortcuts (design §8.1): Ctrl+Enter run · Ctrl+Z/Y undo/redo · Ctrl+C/V/D copy, paste,
 * duplicate · Delete · Ctrl+G / Ctrl+Shift+G group/ungroup · Ctrl+Shift+C / Ctrl+Shift+E collapse
 * to a subgraph / expand one · Ctrl+Shift+L auto-layout · Tab library search · `.` fit ·
 * `F` fit selection · Ctrl+A select all · Ctrl+S save · Escape.
 * Space-to-pan is handled by the canvas itself.
 */
import { onBeforeUnmount, onMounted, shallowRef } from 'vue'

import { type ClipboardPayload, parseClipboard } from '@/canvas/clipboard'
import { useCanvasAdapter } from '@/canvas/CanvasAdapter'
import { layoutGraph } from '@/canvas/layout'
import { isSubgraphType } from '@/canvas/subgraph'
import { groupIdOf, isGroupNodeId } from '@/canvas/vueflow/toFlow'
import { useSelectionStore } from '@/stores/selection'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'

/** In-memory clipboard (the system clipboard is used opportunistically). */
export const internalClipboard = shallowRef<ClipboardPayload | null>(null)

function inEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
}

export interface ShortcutActions {
  run(): void
  undo(): void
  redo(): void
  copy(): void
  paste(): Promise<void>
  duplicate(): void
  remove(): void
  group(): void
  ungroup(): void
  collapse(): void
  expand(): void
  autoLayout(): Promise<void>
  selectAll(): void
  fitView(): void
  fitSelection(): void
  save(): void
  openPalette(): void
  escape(): void
}

export function useShortcutActions(): ShortcutActions {
  const workflow = useWorkflowStore()
  const selection = useSelectionStore()
  const session = useSessionStore()
  const ui = useUiStore()
  const canvas = useCanvasAdapter()

  const selectedNodeIds = () => selection.nodeIds.filter((id) => !isGroupNodeId(id))
  const selectedGroupIds = () => selection.nodeIds.filter(isGroupNodeId).map(groupIdOf)

  return {
    run: () => void session.run(),
    undo: () => void workflow.undo(),
    redo: () => void workflow.redo(),
    copy() {
      const payload = workflow.copy(selectedNodeIds())
      if (!payload) return
      internalClipboard.value = payload
      try {
        void navigator.clipboard?.writeText(JSON.stringify(payload))
      } catch {
        // clipboard access denied: the in-memory copy still works
      }
    },
    async paste() {
      let payload = internalClipboard.value
      try {
        const text = await navigator.clipboard?.readText()
        const external = text ? parseClipboard(text) : null
        if (external) payload = external
      } catch {
        // permission denied or unavailable
      }
      if (!payload || !workflow.isOpen) return
      const ids = workflow.paste(payload, { offset: [40, 40] })
      if (ids.length) selection.set(ids)
    },
    duplicate() {
      const ids = workflow.duplicate(selectedNodeIds())
      if (ids.length) selection.set(ids)
    },
    remove() {
      const nodes = selectedNodeIds()
      const groups = selectedGroupIds()
      const edges = selection.edgeIds
      if (!nodes.length && !groups.length && !edges.length) return
      workflow.transaction('command.delete', () => {
        if (nodes.length) workflow.removeNodes(nodes)
        if (groups.length) workflow.ungroup(groups)
        if (edges.length) workflow.disconnect(edges)
      })
      selection.clear()
    },
    group() {
      const gid = workflow.groupNodes(selectedNodeIds())
      if (gid) selection.set([`group:${gid}`])
    },
    ungroup() {
      const groups = new Set(selectedGroupIds())
      for (const id of selectedNodeIds()) {
        const gid = workflow.groupOf(id)
        if (gid) groups.add(gid)
      }
      if (groups.size) workflow.ungroup([...groups])
    },
    collapse() {
      const ids = selectedNodeIds()
      if (ids.length === 0) return
      const instance = workflow.collapseToSubgraph(ids)
      if (instance) selection.set([instance])
    },
    expand() {
      const ids = selectedNodeIds().filter((id) => isSubgraphType(workflow.nodes[id]?.type ?? ''))
      if (ids.length === 0) return
      const created: string[] = []
      workflow.transaction('command.expand', () => {
        for (const id of ids) created.push(...workflow.expandSubgraph(id))
      })
      if (created.length) selection.set(created)
    },
    async autoLayout() {
      const ids = selectedNodeIds()
      const moves = await layoutGraph(workflow.nodes, workflow.edges, {
        nodeIds: ids.length > 1 ? ids : undefined,
      })
      if (moves.length) workflow.moveNodes(moves)
    },
    selectAll() {
      selection.set(Object.keys(workflow.nodes))
    },
    fitView: () => canvas.value?.fitView(),
    fitSelection() {
      const ids = selectedNodeIds()
      canvas.value?.fitView(ids.length ? { nodeIds: ids } : undefined)
    },
    save: () => void workflow.saveNow(),
    openPalette: () => ui.openPalette(),
    escape() {
      if (ui.paletteOpen) ui.closePalette()
      else selection.clear()
    },
  }
}

/** Install the global key handler for the canvas view. */
export function useShortcuts(actions: ShortcutActions): void {
  function onKeyDown(event: KeyboardEvent): void {
    const ui = useUiStore()
    const mod = event.ctrlKey || event.metaKey
    const key = event.key
    if (key === 'Escape') {
      actions.escape()
      return
    }
    if (inEditable(event.target)) return
    if (ui.paletteOpen) return
    let handled = true
    if (mod && key === 'Enter') actions.run()
    else if (mod && !event.shiftKey && key.toLowerCase() === 'z') actions.undo()
    else if (mod && (key.toLowerCase() === 'y' || (event.shiftKey && key.toLowerCase() === 'z')))
      actions.redo()
    else if (mod && event.shiftKey && key.toLowerCase() === 'c') actions.collapse()
    else if (mod && event.shiftKey && key.toLowerCase() === 'e') actions.expand()
    else if (mod && event.shiftKey && key.toLowerCase() === 'l') void actions.autoLayout()
    else if (mod && key.toLowerCase() === 'c') actions.copy()
    else if (mod && key.toLowerCase() === 'v') void actions.paste()
    else if (mod && key.toLowerCase() === 'd') actions.duplicate()
    else if (mod && key.toLowerCase() === 'g') {
      if (event.shiftKey) actions.ungroup()
      else actions.group()
    } else if (mod && key.toLowerCase() === 'a') actions.selectAll()
    else if (mod && key.toLowerCase() === 's') actions.save()
    else if (!mod && (key === 'Delete' || key === 'Backspace')) actions.remove()
    else if (!mod && key === 'Tab') actions.openPalette()
    else if (!mod && key === '.') actions.fitView()
    else if (!mod && key.toLowerCase() === 'f') actions.fitSelection()
    else handled = false
    if (handled) event.preventDefault()
  }

  onMounted(() => window.addEventListener('keydown', onKeyDown))
  onBeforeUnmount(() => window.removeEventListener('keydown', onKeyDown))
}
