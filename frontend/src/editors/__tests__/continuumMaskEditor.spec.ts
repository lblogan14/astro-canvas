import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'

import type { NodeSpec } from '@/api/types'
import { WsClient } from '@/api/ws'
import ContinuumMaskEditor from '@/editors/ContinuumMaskEditor.vue'
import { i18n } from '@/i18n'
import { useExecutionStore } from '@/stores/execution'
import { useSessionStore } from '@/stores/session'
import { mathChain } from '@/stores/__tests__/fixtures'
import { useWorkflowStore } from '@/stores/workflow'

vi.mock('@/editors/EditorPlot.vue', () => ({
  default: {
    name: 'EditorPlot',
    props: ['x', 'y', 'error', 'overlays', 'bands'],
    emits: ['select', 'click'],
    template:
      '<div data-widget="editor-plot-stub" :data-bands="JSON.stringify(bands)" :data-overlays="overlays.length" />',
  },
}))

class FakeSocket {
  static last: FakeSocket | null = null
  binaryType = 'blob'
  onopen: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  sent: string[] = []
  constructor() {
    FakeSocket.last = this
  }
  send(data: string): void {
    this.sent.push(data)
  }
  close(): void {
    // no-op
  }
}

const SPEC: NodeSpec = {
  id: 'rbcodes.continuum.fit',
  name: 'Fit Continuum',
  category: 'rbcodes/Continuum',
  version: '1.0.0',
  cost: 'cheap',
  inputs: [
    { name: 'spec', type: 'astro.Spectrum1D', description: '', required: true, lazy: false },
  ],
  params: [],
  outputs: [
    { name: 'continuum', type: 'astro.Continuum', description: '', required: true, lazy: false },
    { name: 'normalized', type: 'astro.Spectrum1D', description: '', required: true, lazy: false },
  ],
  description: '',
  param_docs: {},
  icon: null,
  preview: null,
  editor: 'continuum-mask',
  pack: 'rbcodes',
  module: '',
  deprecated: false,
  experimental: false,
  expand: false,
  fingerprint: false,
  is_async: false,
}

function sentOf(socket: FakeSocket, type: string): Record<string, unknown>[] {
  return socket.sent
    .map((s) => JSON.parse(s) as Record<string, unknown>)
    .filter((m) => m['type'] === type)
}

describe('ContinuumMaskEditor', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    FakeSocket.last = null
    const workflow = useWorkflowStore()
    workflow.load({
      ...mathChain(),
      id: 'wf',
      name: 'wf',
      nodes: {
        slice: { type: 'rbcodes.absorption.slice', params: {}, disabled: false, notes: '' },
        cont: {
          type: 'rbcodes.continuum.fit',
          params: { masks: [[-300, 250]], order: 3, optimize_order: true, method: 'polynomial' },
          disabled: false,
          notes: '',
        },
      },
      edges: { e1: { from: ['slice', 'out'], to: ['cont', 'spec'] } },
    })
    const session = useSessionStore()
    session.connect(
      () =>
        new WsClient({
          url: () => 'ws://test',
          factory: () => new FakeSocket() as unknown as WebSocket,
          pingIntervalMs: 0,
        }),
    )
    FakeSocket.last!.onopen?.()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  function mountEditor() {
    return mount(ContinuumMaskEditor, {
      props: { nodeId: 'cont', spec: SPEC },
      global: { plugins: [i18n] },
    })
  }

  it('sends a debounced preview.compute with the candidate params and shows the fit result', async () => {
    const socket = FakeSocket.last!
    const execution = useExecutionStore()
    const wrapper = mountEditor()
    await nextTick()
    expect(wrapper.findAll('[data-testid="mask-item"]')).toHaveLength(1)
    // The initial candidate goes out after the debounce, with the committed settings.
    expect(sentOf(socket, 'preview.compute')).toHaveLength(0)
    vi.advanceTimersByTime(100)
    await flushPromises()
    const first = sentOf(socket, 'preview.compute')
    expect(first).toHaveLength(1)
    expect(first[0]).toMatchObject({
      node_id: 'cont',
      tag: 'editor',
      params: { masks: [[-300, 250]], order: 3, optimize_order: true, method: 'polynomial' },
    })
    expect(wrapper.find('[data-testid="editor-fit-status"]').attributes('data-pending')).toBe(
      'true',
    )

    // Add a mask through the manual form: merged, listed, and a new candidate is sent.
    await wrapper.find('[data-testid="mask-lo"]').setValue('500')
    await wrapper.find('[data-testid="mask-hi"]').setValue('1000')
    await wrapper.find('[data-testid="mask-add"]').trigger('click')
    expect(wrapper.findAll('[data-testid="mask-item"]')).toHaveLength(2)
    vi.advanceTimersByTime(100)
    const second = sentOf(socket, 'preview.compute')
    expect(second).toHaveLength(2)
    expect(second[1]?.['params']).toMatchObject({
      masks: [
        [-300, 250],
        [500, 1000],
      ],
    })

    // The server answers with a tagged Continuum summary and preview.computed.
    execution.applyMessage({
      type: 'node.output.summary',
      workflow_id: 'wf',
      node_id: 'cont',
      port: 'continuum',
      type_id: 'astro.Continuum',
      tag: 'editor',
      ts: 1,
      summary: {
        type: 'astro.Continuum',
        n: 2,
        index: [0, 1],
        cont: [1, 1],
        masks: [[-300, 250]],
        method: 'polynomial',
        order: 1,
        bic: -40.9,
        params: {
          bic_results: [
            [0, -39.6],
            [1, -40.9],
          ],
          fit_error: 0.05,
        },
      },
    })
    execution.applyMessage({
      type: 'preview.computed',
      workflow_id: 'wf',
      node_id: 'cont',
      node_type: null,
      tag: 'editor',
      ok: true,
      ports: ['continuum', 'normalized'],
      elapsed_ms: 12.4,
      ts: 2,
    })
    await flushPromises()
    const status = wrapper.find('[data-testid="editor-fit-status"]')
    expect(status.attributes('data-pending')).toBe('false')
    expect(status.text()).toContain('12 ms')
    const rows = wrapper.findAll('[data-testid="bic-table"] tbody tr')
    expect(rows).toHaveLength(2)
    expect(rows[1]?.attributes('data-best')).toBe('true')

    // Picking a BIC row switches to a fixed order.
    await rows[0]!.trigger('click')
    expect(
      (wrapper.find('[data-testid="continuum-order"]').element as HTMLSelectElement).value,
    ).toBe('0')

    // Apply writes every setting in one undo entry and asks to close.
    await wrapper.find('[data-testid="editor-apply"]').trigger('click')
    const workflow = useWorkflowStore()
    expect(workflow.nodes['cont']?.params).toEqual({
      masks: [
        [-300, 250],
        [500, 1000],
      ],
      order: 0,
      optimize_order: false,
      method: 'polynomial',
    })
    expect(wrapper.emitted('close')).toHaveLength(1)
    const undoBefore = workflow.canUndo
    workflow.undo()
    expect(undoBefore).toBe(true)
    expect(workflow.nodes['cont']?.params).toMatchObject({ masks: [[-300, 250]], order: 3 })
  })

  it('removes a mask from the list and reports a failed preview', async () => {
    const execution = useExecutionStore()
    const wrapper = mountEditor()
    await nextTick()
    await wrapper.find('[data-testid="mask-remove"]').trigger('click')
    expect(wrapper.findAll('[data-testid="mask-item"]')).toHaveLength(0)
    expect(wrapper.text()).toContain(i18n.global.t('editor.continuum.no_masks'))
    vi.advanceTimersByTime(100)
    execution.applyMessage({
      type: 'preview.computed',
      workflow_id: 'wf',
      node_id: 'cont',
      node_type: null,
      tag: 'editor',
      ok: false,
      error: 'ValueError: not enough unmasked pixels',
      elapsed_ms: 1,
      ts: 3,
    })
    await flushPromises()
    expect(wrapper.find('[data-testid="editor-fit-status"]').text()).toContain(
      'not enough unmasked',
    )
    wrapper.unmount()
    expect(execution.compute('cont', 'editor')).toBeUndefined()
  })
})
