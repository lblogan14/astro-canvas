import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'

import { WsClient } from '@/api/ws'
import { summaryData, upstreamOf, useUpstream } from '@/editors/useUpstream'
import { useExecutionStore } from '@/stores/execution'
import { useSessionStore } from '@/stores/session'
import { mathChain } from '@/stores/__tests__/fixtures'
import { useWorkflowStore } from '@/stores/workflow'

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

const EDGES = {
  e1: { from: ['slice', 'out'] as [string, string], to: ['cont', 'spec'] as [string, string] },
  e2: { from: ['tr', 'out'] as [string, string], to: ['cont', 'transition'] as [string, string] },
}

describe('upstreamOf / summaryData', () => {
  it('finds the source of an input port', () => {
    expect(upstreamOf(EDGES, 'cont', 'spec')).toEqual({ nodeId: 'slice', port: 'out' })
    expect(upstreamOf(EDGES, 'cont', 'transition')).toEqual({ nodeId: 'tr', port: 'out' })
    expect(upstreamOf(EDGES, 'cont', 'other')).toBeNull()
    expect(upstreamOf({}, 'cont', 'spec')).toBeNull()
  })

  it('unwraps {type, data} summaries and leaves flat ones alone', () => {
    const entry = { typeId: 'astro.Transition', summary: { type: 'x', data: { wrest: 1 } }, ts: 0 }
    expect(summaryData(entry)).toEqual({ wrest: 1 })
    const flat = { typeId: 'astro.Spectrum1D', summary: { wave: [1] }, ts: 0 }
    expect(summaryData(flat)).toEqual({ wave: [1] })
    expect(summaryData(undefined)).toBeNull()
  })
})

describe('useUpstream', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    FakeSocket.last = null
  })

  function openSocket(): FakeSocket {
    const session = useSessionStore()
    session.connect(
      () =>
        new WsClient({
          url: () => 'ws://test',
          factory: () => new FakeSocket() as unknown as WebSocket,
          pingIntervalMs: 0,
        }),
    )
    const socket = FakeSocket.last!
    socket.onopen?.()
    return socket
  }

  it('requests a tagged full-resolution preview of the upstream output and exposes the series', async () => {
    const workflow = useWorkflowStore()
    const execution = useExecutionStore()
    workflow.load({
      ...mathChain(),
      id: 'wf',
      name: 'wf',
      nodes: {
        slice: { type: 'rbcodes.absorption.slice', params: {}, disabled: false, notes: '' },
        cont: { type: 'rbcodes.continuum.fit', params: {}, disabled: false, notes: '' },
      },
      edges: EDGES,
    })
    const socket = openSocket()
    const seen = ref<number | null>(null)
    const Probe = defineComponent({
      setup() {
        const up = useUpstream(ref('cont'), 'spec')
        return () => {
          seen.value = up.series.value?.n ?? null
          return h('div', { 'data-ready': String(up.ready.value) }, up.source.value?.nodeId ?? '-')
        }
      },
    })
    const wrapper = mount(Probe)
    await nextTick()
    expect(wrapper.text()).toBe('slice')
    const requests = socket.sent.map((s) => JSON.parse(s) as Record<string, unknown>)
    const preview = requests.find((r) => r['type'] === 'preview.request')
    expect(preview).toMatchObject({
      node_id: 'slice',
      port: 'out',
      viewport: { n_out: 20000, tag: 'editor' },
    })
    expect(wrapper.attributes('data-ready')).toBe('false')
    // The tagged reply lands in `views` and becomes the series.
    execution.applyMessage({
      type: 'node.output.summary',
      workflow_id: 'wf',
      node_id: 'slice',
      port: 'out',
      type_id: 'astro.Spectrum1D',
      tag: 'editor',
      ts: 1,
      summary: {
        type: 'astro.Spectrum1D',
        n: 3,
        n_view: 3,
        range: [-10, 10],
        wave: [-10, 0, 10],
        flux: [1, 0.5, 1],
        wave_unit: 'km / s',
        flux_unit: '',
        frame: 'velocity',
        z: 1.3855,
        v0_wrest: 2796.352,
      },
    })
    await nextTick()
    expect(seen.value).toBe(3)
    expect(wrapper.attributes('data-ready')).toBe('true')
    // Unmounting drops the tagged view so the node thumbnail is untouched.
    wrapper.unmount()
    expect(execution.view('slice', 'out', 'editor')).toBeUndefined()
  })

  it('reports no source for an unconnected port without sending anything', async () => {
    const workflow = useWorkflowStore()
    workflow.load({
      ...mathChain(),
      id: 'wf',
      name: 'wf',
      nodes: { cont: { type: 'rbcodes.continuum.fit', params: {}, disabled: false, notes: '' } },
      edges: {},
    })
    const socket = openSocket()
    const Probe = defineComponent({
      setup() {
        const up = useUpstream(ref('cont'), 'spec')
        return () => h('div', up.source.value ? 'yes' : 'no')
      },
    })
    const wrapper = mount(Probe)
    await nextTick()
    expect(wrapper.text()).toBe('no')
    expect(socket.sent.filter((s) => s.includes('preview.request'))).toEqual([])
  })
})
