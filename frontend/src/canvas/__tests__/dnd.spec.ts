import { describe, expect, it } from 'vitest'

import {
  FILE_DRAG_TYPE,
  NODE_DRAG_TYPE,
  isCanvasDrop,
  setFileDragData,
  setNodeDragData,
} from '../dnd'

function transfer(types: string[] = []): DataTransfer {
  const data = new Map<string, string>()
  return {
    types,
    effectAllowed: 'none',
    setData(type: string, value: string) {
      data.set(type, value)
      types.push(type)
    },
    getData(type: string) {
      return data.get(type) ?? ''
    },
  } as unknown as DataTransfer
}

describe('canvas drag-and-drop payloads', () => {
  it('writes node and file payloads', () => {
    const t = transfer()
    setNodeDragData({ dataTransfer: t } as unknown as DragEvent, 'core.math.constant')
    expect(t.getData(NODE_DRAG_TYPE)).toBe('core.math.constant')
    expect(t.effectAllowed).toBe('copy')
    const f = transfer()
    setFileDragData({ dataTransfer: f } as unknown as DragEvent, 'samples/a.fits')
    expect(f.getData(FILE_DRAG_TYPE)).toBe('samples/a.fits')
    expect(f.getData('text/plain')).toBe('samples/a.fits')
    // No dataTransfer: nothing happens.
    setNodeDragData({ dataTransfer: null } as unknown as DragEvent, 'x')
    setFileDragData({ dataTransfer: null } as unknown as DragEvent, 'x')
  })

  it('recognises droppable transfers', () => {
    expect(isCanvasDrop(null)).toBe(false)
    expect(isCanvasDrop(transfer(['text/plain']))).toBe(false)
    expect(isCanvasDrop(transfer([NODE_DRAG_TYPE]))).toBe(true)
    expect(isCanvasDrop(transfer([FILE_DRAG_TYPE]))).toBe(true)
    expect(isCanvasDrop(transfer(['Files']))).toBe(true)
  })
})
