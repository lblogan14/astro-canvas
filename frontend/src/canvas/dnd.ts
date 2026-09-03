/** Drag-and-drop MIME type for node types dragged from the library onto the canvas. */
export const NODE_DRAG_TYPE = 'application/astro-canvas-node'

export function setNodeDragData(event: DragEvent, typeId: string): void {
  if (!event.dataTransfer) return
  event.dataTransfer.setData(NODE_DRAG_TYPE, typeId)
  event.dataTransfer.effectAllowed = 'copy'
}
