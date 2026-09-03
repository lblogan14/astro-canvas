import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'

import type { NodeSpec } from '@/api/types'
import { WsClient } from '@/api/ws'
import ApertureEditor from '@/editors/ApertureEditor.vue'
import {
  type Aperture,
  apertureFromDrag,
  aperturesFrom,
  center,
  clampToField,
  contains,
  defaultLabel,
  describe as describeAperture,
  fromDs9,
  moveTo,
  outerRadius,
  pick,
  resizeTo,
  toDs9,
  toParam,
} from '@/editors/aperture'
import { i18n } from '@/i18n'
import { useExecutionStore } from '@/stores/execution'
import { useSessionStore } from '@/stores/session'
import { mathChain } from '@/stores/__tests__/fixtures'
import { useWorkflowStore } from '@/stores/workflow'

// uPlot draws into a real canvas; jsdom has no 2-d context, so the chart is stubbed and the test
// asserts on the series it was handed instead.
vi.mock('@/widgets', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/widgets')>()
  return {
    ...actual,
    UPlotLine: {
      name: 'UPlotLine',
      props: ['series', 'height', 'axes'],
      template:
        '<div data-testid="aperture-plot" :data-points="series ? series.wave.length : 0" />',
    },
  }
})

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

const CIRCLE: Aperture = {
  shape: 'circle',
  pixel: [10, 12, 4],
  sky: null,
  label: 'disc',
  role: 'source',
}
const ANNULUS: Aperture = {
  shape: 'annulus',
  pixel: [10, 12, 8, 11],
  sky: null,
  label: 'sky',
  role: 'background',
}
const BOX: Aperture = {
  shape: 'box',
  pixel: [20, 20, 6, 4, 0],
  sky: null,
  label: null,
  role: 'source',
}
const TRIANGLE: Aperture = {
  shape: 'polygon',
  pixel: [2, 2, 12, 2, 7, 12],
  sky: null,
  label: null,
  role: 'source',
}

// --- helpers --------------------------------------------------------------------------------------

describe('aperture helpers', () => {
  it('reads apertures from a param list and from a Region2D summary', () => {
    const param = [
      { shape: 'circle', pixel: [1, 2, 3], role: 'background', label: 'sky' },
      { shape: 'nope', pixel: [1, 2, 3] },
      { shape: 'box', pixel: [] },
      'junk',
    ]
    const rows = aperturesFrom(param)
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ shape: 'circle', role: 'background', label: 'sky' })

    const summary = {
      type: 'astro.Region2D',
      count: 1,
      regions: [{ shape: 'box', pixel: [1, 2, 3, 4, 0] }],
    }
    expect(aperturesFrom(summary)[0]?.shape).toBe('box')
    expect(aperturesFrom(undefined)).toEqual([])
    expect(aperturesFrom({ regions: 'no' })).toEqual([])
  })

  it('round-trips through the param payload', () => {
    const payload = toParam([CIRCLE, ANNULUS])
    expect(payload[0]).toEqual({
      shape: 'circle',
      pixel: [10, 12, 4],
      sky: null,
      label: 'disc',
      role: 'source',
    })
    expect(aperturesFrom(payload)).toEqual([CIRCLE, ANNULUS])
  })

  it('builds each shape from a drag', () => {
    const from = { x: 10, y: 10 }
    const to = { x: 13, y: 14 }
    expect(apertureFromDrag('circle', from, to).pixel).toEqual([10, 10, 5])
    expect(apertureFromDrag('annulus', from, to).pixel).toEqual([10, 10, 3, 5])
    expect(apertureFromDrag('box', from, to).pixel).toEqual([11.5, 12, 3, 4, 0])
    expect(apertureFromDrag('polygon', from, to).pixel).toEqual([10, 10, 13, 10, 13, 14, 10, 14])
    // A click without a drag still produces a usable (tiny) aperture rather than a zero one.
    expect(apertureFromDrag('circle', from, from).pixel[2]).toBeGreaterThan(0)
    expect(apertureFromDrag('circle', from, to, 'background').role).toBe('background')
  })

  it('tests containment the way the rasterizer does', () => {
    expect(contains(CIRCLE, { x: 10, y: 12 })).toBe(true)
    expect(contains(CIRCLE, { x: 14, y: 12 })).toBe(true) // on the edge: inside
    expect(contains(CIRCLE, { x: 15, y: 12 })).toBe(false)
    // The annulus hole is not part of the aperture.
    expect(contains(ANNULUS, { x: 10, y: 12 })).toBe(false)
    expect(contains(ANNULUS, { x: 19, y: 12 })).toBe(true)
    expect(contains(BOX, { x: 22, y: 21 })).toBe(true)
    expect(contains(BOX, { x: 24, y: 20 })).toBe(false)
    expect(contains(TRIANGLE, { x: 7, y: 4 })).toBe(true)
    expect(contains(TRIANGLE, { x: 2, y: 11 })).toBe(false)
  })

  it('picks the top-most aperture under a point', () => {
    const list = [CIRCLE, BOX]
    expect(pick(list, { x: 20, y: 20 })).toBe(1)
    expect(pick(list, { x: 10, y: 12 })).toBe(0)
    expect(pick(list, { x: 40, y: 40 })).toBe(-1)
    // Later apertures win where two overlap.
    expect(pick([CIRCLE, { ...CIRCLE, label: 'second' }], { x: 10, y: 12 })).toBe(1)
  })

  it('moves and resizes every shape about its centre', () => {
    expect(center(TRIANGLE)).toEqual({ x: 7, y: 16 / 3 })
    expect(moveTo(CIRCLE, { x: 0, y: 0 }).pixel).toEqual([0, 0, 4])
    expect(moveTo(TRIANGLE, { x: 7, y: 0 }).pixel[1]).toBeCloseTo(2 - 16 / 3)
    expect(resizeTo(CIRCLE, { x: 16, y: 12 }).pixel).toEqual([10, 12, 6])
    // The annulus keeps its inner/outer ratio.
    const grown = resizeTo(ANNULUS, { x: 32, y: 12 })
    expect(grown.pixel[3]).toBeCloseTo(22)
    expect(grown.pixel[2] / grown.pixel[3]!).toBeCloseTo(8 / 11)
    expect(resizeTo(BOX, { x: 25, y: 23 }).pixel).toEqual([20, 20, 10, 6, 0])
    expect(outerRadius(resizeTo(TRIANGLE, { x: 7, y: 20 }))).toBeCloseTo(20 - 16 / 3)
    // Resizing never collapses a shape to nothing.
    expect(resizeTo(CIRCLE, { x: 10, y: 12 }).pixel[2]).toBeGreaterThan(0)
  })

  it('keeps apertures inside the field', () => {
    expect(clampToField(CIRCLE, 40, 40)).toBe(CIRCLE)
    const pulled = clampToField({ ...CIRCLE, pixel: [90, -5, 4] }, 40, 36)
    expect(pulled.pixel[0]).toBe(35)
    expect(pulled.pixel[1]).toBe(0)
  })

  it('labels and describes apertures', () => {
    expect(defaultLabel(CIRCLE, 0)).toBe('disc')
    expect(defaultLabel({ ...CIRCLE, label: null }, 1)).toBe('circle 2')
    expect(describeAperture(CIRCLE, null)).toBe('r 4.0 px')
    expect(describeAperture(CIRCLE, 0.36)).toBe('r 1.44″')
    expect(describeAperture(ANNULUS, null)).toBe('8.0 px – 11.0 px')
    expect(describeAperture(BOX, null)).toBe('6.0 px × 4.0 px')
    expect(describeAperture(TRIANGLE, null)).toBe('3 vertices')
  })
})

describe('ds9 text', () => {
  it('writes 1-based image coordinates with labels and background tags', () => {
    const text = toDs9([CIRCLE, ANNULUS])
    expect(text).toContain('# Region file format: DS9 version 4.1')
    expect(text).toContain('image')
    expect(text).toContain('circle(11.0000,13.0000,4.0000) # text={disc}')
    expect(text).toContain('tag={background}')
  })

  it('round-trips every shape', () => {
    const { apertures, skipped } = fromDs9(toDs9([CIRCLE, ANNULUS, BOX, TRIANGLE]))
    expect(skipped).toBe(0)
    expect(apertures).toEqual([CIRCLE, ANNULUS, BOX, TRIANGLE])
  })

  it('skips sky regions, exclusions and shapes it does not draw', () => {
    const text = [
      'fk5',
      'circle(150.1,2.2,1.8")',
      'image',
      '-circle(5,5,2)',
      'ellipse(5,5,3,2,0)',
      '# a comment',
      'circle(10,10,3) # text={keep}',
    ].join('\n')
    const { apertures, skipped } = fromDs9(text)
    expect(skipped).toBe(1)
    expect(apertures).toHaveLength(1)
    expect(apertures[0]).toMatchObject({ label: 'keep', pixel: [9, 9, 3] })
  })

  it('ignores unparseable lines', () => {
    expect(fromDs9('image\ncircle(a,b,c)\nnot a shape').apertures).toEqual([])
  })
})

// --- component ------------------------------------------------------------------------------------

const SPEC: NodeSpec = {
  id: 'rbcodes.ifu.aperture_extract',
  name: 'Aperture Extract',
  category: 'rbcodes/IFU',
  version: '1.0.0',
  cost: 'auto',
  description: '',
  icon: null,
  editor: 'aperture-editor',
  preview: null,
  inputs: [],
  outputs: [],
  params: [],
  expand: false,
  fingerprint: false,
  pack: 'rbcodes',
  module: 'astro_canvas_rbcodes.nodes.ifu',
} as unknown as NodeSpec

const NY = 20
const NX = 16

function tile(width = NX, height = NY) {
  const values = new Float32Array(width * height)
  for (let i = 0; i < values.length; i += 1) values[i] = i % 7
  const bytes = new Uint8Array(values.buffer)
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return {
    width,
    height,
    step: 1,
    dtype: 'f4',
    b64: btoa(binary),
    zscale: [0, 6],
    minmax: [0, 6],
    percentile: [0, 6],
  }
}

const CUBE_SUMMARY = {
  type: 'astro.Cube3D',
  shape: [40, NY, NX],
  instrument: 'KCWI',
  object: 'Synthetic disc',
  wave_range: [4900, 5059],
  band: [null, null],
  has_var: true,
  wcs: {
    naxis: 2,
    ctype: ['RA---TAN', 'DEC--TAN'],
    crval: [150.1, 2.2],
    crpix: [8, 10],
    cdelt: [-0.0001, 0.0001],
    cunit: ['deg', 'deg'],
  },
  tile: tile(),
  spectrum: { wave: [4900, 5059], flux: [1, 2] },
}

function spectrumSummary() {
  const wave = Array.from({ length: 32 }, (_, i) => 4900 + i * 5)
  return {
    type: 'astro.Spectrum1D',
    n: 32,
    range: [wave[0], wave[wave.length - 1]],
    wave,
    flux: wave.map((w) => Math.sin(w / 30) + 2),
    wave_unit: 'Angstrom',
    flux_unit: '',
    frame: 'observed',
    z: null,
    v0_wrest: null,
  }
}

function summary(
  nodeId: string,
  typeId: string,
  payload: Record<string, unknown>,
  tag: string | null = 'editor',
  port = 'out',
) {
  return {
    type: 'node.output.summary',
    workflow_id: 'wf',
    node_id: nodeId,
    port,
    type_id: typeId,
    tag,
    ts: 1,
    summary: payload,
  } as never
}

function sentOf(socket: FakeSocket, type: string): Record<string, unknown>[] {
  return socket.sent
    .map((raw) => JSON.parse(raw) as Record<string, unknown>)
    .filter((message) => message['type'] === type)
}

describe('ApertureEditor', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  async function setup(params: Record<string, unknown> = {}) {
    const workflow = useWorkflowStore()
    workflow.load({
      ...mathChain(),
      id: 'wf-ifu',
      name: 'wf-ifu',
      nodes: {
        load: { type: 'core.io.load_cube', params: {}, disabled: false, notes: '' },
        extract: {
          type: 'rbcodes.ifu.aperture_extract',
          params: { regions: [], method: 'sum', background: 'none', ...params },
          disabled: false,
          notes: '',
        },
      },
      edges: { e1: { from: ['load', 'out'], to: ['extract', 'cube'] } },
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
    const socket = FakeSocket.last!
    socket.onopen?.()
    const execution = useExecutionStore()
    execution.applyMessage(summary('load', 'astro.Cube3D', CUBE_SUMMARY))
    const wrapper = mount(ApertureEditor, {
      props: { nodeId: 'extract', spec: SPEC },
      global: { plugins: [i18n] },
      attachTo: document.body,
    })
    await flushPromises()
    return { wrapper, workflow, socket, execution }
  }

  it('requests the cube preview and shows its field', async () => {
    const { wrapper, socket } = await setup()
    const requests = sentOf(socket, 'preview.request')
    expect(requests[0]).toMatchObject({ node_id: 'load', port: 'out', viewport: { n_out: 512 } })
    expect(wrapper.find('[data-testid="aperture-overlay"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="aperture-readout"]').text()).toContain(`${NY} × ${NX}`)
    expect(wrapper.find('[data-testid="aperture-list"]').text()).toContain('Drag on the image')
  })

  it('places the overlay on the painted tile, not on the whole widget', async () => {
    // ImageView letterboxes the tile inside its box; an overlay covering the widget would draw
    // every aperture in the wrong place (and stretched).
    const { wrapper } = await setup({ regions: toParam([CIRCLE]) })
    const overlay = wrapper.find('[data-testid="aperture-overlay"]')
    const style = overlay.attributes('style') ?? ''
    expect(style).not.toContain('display: none')
    const width = Number(/width:\s*([\d.]+)px/.exec(style)?.[1])
    const height = Number(/height:\s*([\d.]+)px/.exec(style)?.[1])
    expect(width / height).toBeCloseTo(NX / NY, 5)
    expect(overlay.attributes('viewBox')).toBe(`0 0 ${NX} ${NY}`)
  })

  it('seeds the apertures from the node parameters', async () => {
    const { wrapper } = await setup({ regions: toParam([CIRCLE, ANNULUS]) })
    expect(wrapper.attributes('data-apertures')).toBe('2')
    const rows = wrapper.findAll('[data-testid="aperture-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[1]?.attributes('data-role')).toBe('background')
    expect(wrapper.find('[data-testid="aperture-counts"]').text()).toContain('1 source')
    expect(wrapper.findAll('[data-testid="aperture-shape"]')).toHaveLength(2)
  })

  it('draws a new aperture from a drag on the overlay', async () => {
    const { wrapper } = await setup()
    const overlay = wrapper.find('[data-testid="aperture-overlay"]')
    // jsdom reports a zero-size box; stub it so the pixel mapping is well defined.
    stubBox(overlay.element as SVGSVGElement)
    await overlay.trigger('mousedown', { clientX: 80, clientY: 100 })
    await overlay.trigger('mousemove', { clientX: 120, clientY: 100 })
    await overlay.trigger('mouseup')
    expect(wrapper.attributes('data-apertures')).toBe('1')
    expect(wrapper.find('[data-testid="aperture-status"]').text()).toContain('Circle')
  })

  it('draws background apertures when the toggle is on', async () => {
    const { wrapper } = await setup()
    await wrapper.find('[data-testid="aperture-background-toggle"]').setValue(true)
    await wrapper.find('[data-testid="aperture-tool-annulus"]').trigger('click')
    const overlay = wrapper.find('[data-testid="aperture-overlay"]')
    stubBox(overlay.element as SVGSVGElement)
    await overlay.trigger('mousedown', { clientX: 80, clientY: 100 })
    await overlay.trigger('mousemove', { clientX: 140, clientY: 100 })
    await overlay.trigger('mouseup')
    const row = wrapper.find('[data-testid="aperture-row"]')
    expect(row.attributes('data-role')).toBe('background')
  })

  it('asks the server to extract with the candidate apertures', async () => {
    const { wrapper, socket } = await setup({ regions: toParam([CIRCLE]) })
    await flushPromises()
    const computes = sentOf(socket, 'preview.compute')
    expect(computes.length).toBeGreaterThan(0)
    const request = computes[computes.length - 1]!
    expect(request['node_id']).toBe('extract')
    expect((request['params'] as Record<string, unknown>)['regions']).toEqual(toParam([CIRCLE]))
    expect(request['tag']).toBe('editor-extract')
    expect(wrapper.find('[data-testid="aperture-spectrum"]').text()).toContain('Extracting')
  })

  it('draws the extracted spectrum when it arrives', async () => {
    const { wrapper, execution } = await setup({ regions: toParam([CIRCLE]) })
    execution.applyMessage(
      summary(
        'extract',
        'astro.SpectrumCollection',
        {
          type: 'astro.SpectrumCollection',
          count: 1,
          labels: ['disc'],
          items: [spectrumSummary()],
        },
        'editor-extract',
        'spectra',
      ),
    )
    await flushPromises()
    const plot = wrapper.find('[data-testid="aperture-plot"]')
    expect(plot.exists()).toBe(true)
    expect(plot.attributes('data-points')).toBe('32')
  })

  it('re-collapses the cube when the band changes', async () => {
    const { wrapper, socket } = await setup()
    const before = sentOf(socket, 'preview.request').length
    const slider = wrapper.find('[data-testid="aperture-band-lo"]')
    await slider.setValue('4950')
    await slider.trigger('change')
    const requests = sentOf(socket, 'preview.request')
    expect(requests.length).toBeGreaterThan(before)
    expect(requests[requests.length - 1]).toMatchObject({ viewport: { lo: 4950, hi: 5059 } })
    await wrapper.find('[data-testid="aperture-band-reset"]').trigger('click')
    const reset = sentOf(socket, 'preview.request')
    expect(reset[reset.length - 1]?.['viewport']).not.toHaveProperty('lo')
  })

  it('edits labels, roles and removes apertures', async () => {
    const { wrapper } = await setup({ regions: toParam([CIRCLE, BOX, TRIANGLE]) })
    const labels = wrapper.findAll('[data-testid="aperture-label"]')
    await labels[1]?.setValue('clump')
    await labels[1]?.trigger('change')
    await wrapper.findAll('[data-testid="aperture-row-background"]')[1]?.setValue(true)
    await wrapper.findAll('[data-testid="aperture-remove"]')[2]?.trigger('click')
    expect(wrapper.attributes('data-apertures')).toBe('2')
    await wrapper.find('[data-testid="aperture-apply"]').trigger('click')
    const workflow = useWorkflowStore()
    const written = workflow.nodes['extract']?.params['regions'] as Record<string, unknown>[]
    expect(written).toHaveLength(2)
    expect(written[1]).toMatchObject({ label: 'clump', role: 'background' })
  })

  it('cannot apply without a source aperture', async () => {
    const { wrapper, workflow } = await setup({ regions: toParam([CIRCLE]) })
    await wrapper.find('[data-testid="aperture-row-background"]').setValue(true)
    expect(wrapper.find('[data-testid="aperture-apply"]').attributes('disabled')).toBeDefined()
    expect(workflow.nodes['extract']?.params['regions'] as unknown[]).toHaveLength(1)
  })

  it('imports a ds9 file and exports one', async () => {
    const { wrapper } = await setup()
    const clicked = vi.fn()
    const created = document.createElement('a')
    created.click = clicked
    const create = vi.spyOn(document, 'createElement')
    create.mockImplementation((tag: string) =>
      tag === 'a' ? created : Object.getPrototypeOf(document).createElement.call(document, tag),
    )
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()

    const input = wrapper.find('[data-testid="aperture-file"]')
    const file = new File([toDs9([CIRCLE, ANNULUS])], 'a.reg', { type: 'text/plain' })
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(wrapper.attributes('data-apertures')).toBe('2')
    expect(wrapper.find('[data-testid="aperture-status"]').text()).toContain('Imported 2')

    await wrapper.find('[data-testid="aperture-export"]').trigger('click')
    expect(clicked).toHaveBeenCalled()
    create.mockRestore()
  })

  it('clears every aperture', async () => {
    const { wrapper } = await setup({ regions: toParam([CIRCLE, BOX]) })
    await wrapper.find('[data-testid="aperture-clear"]').trigger('click')
    expect(wrapper.attributes('data-apertures')).toBe('0')
    expect(wrapper.find('[data-testid="aperture-apply"]').attributes('disabled')).toBeDefined()
  })
})

/** jsdom gives every element a zero-size box; the overlay needs a real one to map pixels. */
function stubBox(element: SVGSVGElement): void {
  element.getBoundingClientRect = () =>
    ({
      left: 40,
      top: 40,
      width: 160,
      height: 200,
      right: 200,
      bottom: 240,
      x: 40,
      y: 40,
    }) as DOMRect
}
