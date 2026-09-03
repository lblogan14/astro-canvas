/** Drag-and-drop MIME type for node types dragged from the library onto the canvas. */
export const NODE_DRAG_TYPE = 'application/astro-canvas-node'

/** Drag-and-drop MIME type for workspace files dragged from the Workspace panel. */
export const FILE_DRAG_TYPE = 'application/astro-canvas-file'

export function setNodeDragData(event: DragEvent, typeId: string): void {
  if (!event.dataTransfer) return
  event.dataTransfer.setData(NODE_DRAG_TYPE, typeId)
  event.dataTransfer.effectAllowed = 'copy'
}

export function setFileDragData(event: DragEvent, path: string): void {
  if (!event.dataTransfer) return
  event.dataTransfer.setData(FILE_DRAG_TYPE, path)
  event.dataTransfer.setData('text/plain', path)
  event.dataTransfer.effectAllowed = 'copy'
}

/** True when a drag carries something the canvas can turn into nodes (a library node, a workspace file or OS files). */
export function isCanvasDrop(transfer: DataTransfer | null): boolean {
  if (!transfer) return false
  const types = Array.from(transfer.types)
  return types.includes(NODE_DRAG_TYPE) || types.includes(FILE_DRAG_TYPE) || types.includes('Files')
}
