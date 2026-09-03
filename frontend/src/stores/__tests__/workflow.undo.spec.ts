import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { deepEqual } from '@/lib/deepEqual'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import {
  GROUP_HEADER,
  GROUP_PADDING,
  emptyDoc,
  nodeFromSpec,
  useWorkflowStore,
} from '@/stores/workflow'
import { SPECS, SPEC_INDEX, TYPES, mathChain } from './fixtures'

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return {
    ...original,
    api: {
      putWorkflow: vi.fn<typeof original.api.putWorkflow>(),
      createWorkflow: vi.fn<typeof original.api.createWorkflow>(),
      getWorkflow: vi.fn<typeof original.api.getWorkflow>(),
    },
  }
})

function setup() {
  setActivePinia(createPinia())
  const schema = useNodesSchemaStore()
  schema.specs = SPECS
  schema.types = TYPES
  schema.status = 'ready'
  const workflow = useWorkflowStore()
  workflow.autosaveEnabled = false
  workflow.load(mathChain())
  return workflow
}

const constant = SPEC_INDEX['core.math.constant']!
const expr = SPEC_INDEX['core.math.expr']!

describe('workflow store: document', () => {
  beforeEach(() => {
    vi.useRealTimers()
  })

  it('loads a document without history or dirt', () => {
    const wf = setup()
    expect(wf.isOpen).toBe(true)
    expect(wf.id).toBe('sample-math-chain')
    expect(wf.nodeCount).toBe(4)
    expect(wf.canUndo).toBe(false)
    expect(wf.isDirty).toBe(false)
    expect(deepEqual(wf.doc, mathChain())).toBe(true)
  })

  it('builds nodes from specs with defaults and keeps ids free of slashes', () => {
    const node = nodeFromSpec(expr, [1, 2])
    expect(node.params).toEqual({ expression: 'x', x: 0, y: 0, z: 0 })
    expect(node.linked).toEqual([])
    const wf = setup()
    const id = wf.addNode(constant, [10, 20])
    expect(id).not.toContain('/')
    expect(wf.nodes[id]?.pos).toEqual([10, 20])
    expect(wf.undoLabel).toBe('command.add_node')
    expect(wf.isDirty).toBe(true)
  })

  it('empty documents carry every top-level field the server expects', () => {
    const doc = emptyDoc('New')
    expect(doc.format).toBe('astro-canvas/workflow')
    expect(doc.version).toBe(1)
    expect(doc.nodes).toEqual({})
    expect(doc.name).toBe('New')
  })
})

describe('workflow store: undo/redo', () => {
  it('undoes and redoes add, param edit, connect and delete', () => {
    const wf = setup()
    const before = JSON.parse(JSON.stringify(wf.doc))
    const id = wf.addNode(constant, [0, 0])
    wf.setParam(id, 'value', 5)
    const rejected = wf.connect({ source: id, sourcePort: 'out', target: 'sum', targetPort: 'x' })
    expect(rejected.verdict).toMatchObject({ ok: false, reason: 'multiple_inputs' })
    expect(rejected.edgeId).toBeNull()
    // dropping onto an unlinked linkable param links it in the same command
    const ok = wf.connect({ source: id, sourcePort: 'out', target: 'sum', targetPort: 'z' })
    expect(ok.verdict.ok).toBe(true)
    expect(wf.nodes.sum?.linked).toEqual(['x', 'y', 'z'])
    expect(Object.keys(wf.edges)).toHaveLength(4)
    wf.removeNodes([id])
    expect(wf.nodes[id]).toBeUndefined()
    expect(Object.keys(wf.edges)).toHaveLength(3)

    // add, param, connect(+link), delete → 4 commands
    expect(wf.undoStack).toHaveLength(4)
    wf.undo() // delete
    expect(wf.nodes[id]?.params).toEqual({ value: 5 })
    expect(Object.keys(wf.edges)).toHaveLength(4)
    wf.undo() // connect
    expect(Object.keys(wf.edges)).toHaveLength(3)
    expect(wf.nodes.sum?.linked).toEqual(['x', 'y'])
    wf.undo() // param
    expect(wf.nodes[id]?.params).toEqual({ value: 0 })
    wf.undo() // add
    expect(deepEqual(wf.doc, before)).toBe(true)
    expect(wf.canUndo).toBe(false)
    expect(wf.undo()).toBe(false)

    expect(wf.canRedo).toBe(true)
    wf.redo()
    wf.redo()
    expect(wf.nodes[id]?.params).toEqual({ value: 5 })
    wf.redo()
    wf.redo()
    expect(wf.nodes[id]).toBeUndefined()
    expect(wf.redo()).toBe(false)
  })

  it('coalesces rapid edits of the same param and separate moves of the same nodes', () => {
    vi.useFakeTimers()
    vi.setSystemTime(1_000_000)
    const wf = setup()
    wf.setParam('c', 'value', 3)
    vi.advanceTimersByTime(100)
    wf.setParam('c', 'value', 4)
    vi.advanceTimersByTime(100)
    wf.setParam('c', 'value', 5)
    expect(wf.undoStack).toHaveLength(1)
    wf.moveNodes([{ id: 'c', pos: [100, 100] }])
    wf.moveNodes([{ id: 'c', pos: [120, 100] }])
    expect(wf.undoStack).toHaveLength(2)
    // outside the window → a new entry
    vi.advanceTimersByTime(5000)
    wf.setParam('c', 'value', 6)
    expect(wf.undoStack).toHaveLength(3)
    wf.undo()
    expect(wf.nodes.c?.params).toEqual({ value: 5 })
    wf.undo()
    expect(wf.nodes.c?.pos).toEqual([80, 80])
    wf.undo()
    expect(wf.nodes.c?.params).toEqual({ value: 2 })
    vi.useRealTimers()
  })

  it('a new command clears the redo stack and the stack is capped', () => {
    const wf = setup()
    wf.setParam('c', 'value', 1)
    wf.undo()
    expect(wf.canRedo).toBe(true)
    wf.coalesceWindowMs = 0
    wf.setTitle('c', 'Renamed')
    expect(wf.canRedo).toBe(false)
    for (let i = 0; i < 250; i += 1) wf.setTitle('c', `T${i}`)
    expect(wf.undoStack.length).toBeLessThanOrEqual(200)
  })

  it('groups and ungroups selections with derived geometry, folding into one command', () => {
    const wf = setup()
    const gid = wf.groupNodes(['c', 'sq'], 'Inputs')
    expect(gid).not.toBeNull()
    const group = wf.groups[gid as string]!
    expect(group.nodes).toEqual(['c', 'sq'])
    expect(group.title).toBe('Inputs')
    expect(group.pos).toEqual([80 - GROUP_PADDING, 80 - GROUP_PADDING - GROUP_HEADER])
    expect(group.size?.[0]).toBe(360 + 240 - 80 + 2 * GROUP_PADDING)
    // moving the group moves members
    wf.moveGroup(gid as string, [group.pos![0] + 10, group.pos![1] + 5])
    expect(wf.nodes.c?.pos).toEqual([90, 85])
    expect(wf.nodes.sq?.pos).toEqual([370, 85])
    // deleting a member shrinks the group; deleting all members drops it
    wf.removeNodes(['c'])
    expect(wf.groups[gid as string]?.nodes).toEqual(['sq'])
    wf.removeNodes(['sq'])
    expect(wf.groups[gid as string]).toBeUndefined()
    wf.undo()
    wf.undo()
    wf.ungroup([gid as string])
    expect(wf.groups[gid as string]).toBeUndefined()
    wf.undo()
    expect(wf.groups[gid as string]?.nodes).toEqual(['c', 'sq'])
    expect(wf.groupOf('c')).toBe(gid)
    expect(wf.groupOf('note')).toBeNull()
    wf.fitGroup(gid as string)
    expect(wf.groups[gid as string]?.pos).toEqual([
      90 - GROUP_PADDING,
      85 - GROUP_PADDING - GROUP_HEADER,
    ])
    expect(wf.groupNodes([])).toBeNull()
  })

  it('a transaction folds several commits into one undo entry', () => {
    const wf = setup()
    const ids = wf.transaction('command.paste', () => {
      const a = wf.addNode(constant, [0, 0])
      const b = wf.addNode(constant, [50, 0])
      wf.setParam(a, 'value', 9)
      return [a, b]
    })
    expect(wf.nodeCount).toBe(6)
    expect(wf.undoStack).toHaveLength(1)
    expect(wf.undoLabel).toBe('command.paste')
    wf.undo()
    expect(wf.nodes[ids[0]!]).toBeUndefined()
    expect(wf.nodeCount).toBe(4)
  })

  it('copy/paste preserves internal edges and relative offsets; duplicate shifts by 40', () => {
    const wf = setup()
    const payload = wf.copy(['c', 'sq'])
    expect(payload).not.toBeNull()
    expect(Object.keys(payload!.edges)).toEqual(['e1'])
    expect(payload!.origin).toEqual([80, 80])
    const pasted = wf.paste(payload!, { at: [1000, 500] })
    expect(pasted).toHaveLength(2)
    const positions = pasted.map((id) => wf.nodes[id]!.pos).sort((a, b) => a![0] - b![0])
    expect(positions).toEqual([
      [1000, 500],
      [1280, 500],
    ])
    const newEdges = Object.values(wf.edges).filter((e) => pasted.includes(e.from[0]))
    expect(newEdges).toHaveLength(1)
    expect(pasted).toContain(newEdges[0]!.to[0])
    expect(wf.undoLabel).toBe('command.paste')

    const dup = wf.duplicate(['note'])
    expect(dup).toHaveLength(1)
    expect(wf.nodes[dup[0]!]?.pos).toEqual([120, 340])
    expect(wf.paste({ ...payload!, nodes: {} })).toEqual([])
    expect(wf.copy(['nope'])).toBeNull()
    expect(wf.duplicate(['nope'])).toEqual([])
  })

  it('node property setters are undoable', () => {
    const wf = setup()
    wf.setDisabled('sq', true)
    wf.setCost('sq', 'expensive')
    wf.setNotes('sq', 'careful')
    wf.setUi('sq', { collapsed: true })
    wf.resizeNode('sq', [300, 200], [361, 81])
    wf.setTitle('sq', '   ')
    expect(wf.nodes.sq).toMatchObject({
      disabled: true,
      cost: 'expensive',
      notes: 'careful',
      ui: { collapsed: true },
      size: [300, 200],
      pos: [361, 81],
      title: null,
    })
    while (wf.undo()) {
      // unwind everything
    }
    expect(deepEqual(wf.doc, mathChain())).toBe(true)
  })

  it('unlinking removes the edge into that port; disconnect removes edges', () => {
    const wf = setup()
    wf.toggleLink('sum', 'y')
    expect(wf.nodes.sum?.linked).toEqual(['x'])
    expect(wf.edges.e3).toBeUndefined()
    wf.disconnect(['e1', 'missing'])
    expect(wf.edges.e1).toBeUndefined()
    wf.disconnect(['missing'])
    expect(wf.undoStack).toHaveLength(2)
    wf.toggleLink('nope', 'y')
    wf.setParam('nope', 'y', 1)
    wf.removeNodes([])
    wf.moveNodes([])
  })

  it('renames, describes and restores content', () => {
    const wf = setup()
    wf.rename('  Chain  ')
    expect(wf.name).toBe('Chain')
    wf.rename('Chain')
    wf.rename('   ')
    expect(wf.undoStack).toHaveLength(1)
    wf.setDescription('d1')
    wf.setDescription('d2')
    expect(wf.doc?.description).toBe('d2')
    const restored = mathChain()
    restored.name = 'Old'
    delete restored.nodes!.note
    wf.replaceContent(restored)
    expect(wf.name).toBe('Old')
    expect(wf.nodeCount).toBe(3)
    wf.undo()
    expect(wf.nodeCount).toBe(4)
    expect(wf.doc?.description).toBe('d2')
  })

  it('rejects invalid connections with a reason', () => {
    const wf = setup()
    expect(
      wf.validateConnection({ source: 'c', sourcePort: 'out', target: 'c', targetPort: 'x' }),
    ).toEqual({ ok: false, reason: 'self' })
    expect(
      wf.connect({ source: 'sum', sourcePort: 'out', target: 'sq', targetPort: 'x' }).verdict,
    ).toMatchObject({ ok: false, reason: 'multiple_inputs' })
    wf.disconnect(['e1'])
    expect(
      wf.connect({ source: 'sum', sourcePort: 'out', target: 'sq', targetPort: 'x' }).verdict,
    ).toMatchObject({ ok: false, reason: 'cycle' })
  })

  it('throws when committing without an open document and closes cleanly', () => {
    setActivePinia(createPinia())
    const wf = useWorkflowStore()
    expect(() => wf.commit('x', () => undefined)).toThrow('no workflow is open')
    expect(() => wf.transaction('x', () => undefined)).toThrow('no workflow is open')
    wf.load(mathChain())
    wf.close()
    expect(wf.isOpen).toBe(false)
    expect(wf.nodes).toEqual({})
  })
})
