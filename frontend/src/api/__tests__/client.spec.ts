import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api, authHeaders, getToken, uploadWorkspaceFile, wsUrl } from '../client'

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

class FakeXhr {
  static instances: FakeXhr[] = []
  static status = 201
  static body: unknown = { complete: true, received: 3, upload_id: null, file: null }
  method = ''
  url = ''
  headers: Record<string, string> = {}
  responseType = ''
  response: unknown = null
  status = 0
  statusText = 'Created'
  form: FormData | null = null
  upload = {
    onprogress: null as
      ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null,
  }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  onabort: (() => void) | null = null
  aborted = false
  constructor() {
    FakeXhr.instances.push(this)
  }
  open(method: string, url: string) {
    this.method = method
    this.url = url
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value
  }
  abort() {
    this.aborted = true
    this.onabort?.()
  }
  send(form: FormData) {
    this.form = form
    queueMicrotask(() => {
      this.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 3 })
      this.status = FakeXhr.status
      this.response = FakeXhr.body
      this.onload?.()
    })
  }
}

describe('api client', () => {
  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('XMLHttpRequest', FakeXhr)
    FakeXhr.instances = []
    FakeXhr.status = 201
    window.sessionStorage.clear()
    window.history.replaceState(null, '', '/')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('moves the token from the query string into session storage', () => {
    window.history.replaceState(null, '', '/w/abc?token=secret&x=1')
    expect(getToken()).toBe('secret')
    expect(window.location.search).toBe('?x=1')
    expect(getToken()).toBe('secret')
    expect(authHeaders()).toEqual({ Authorization: 'Bearer secret' })
    expect(wsUrl('c1')).toContain('/ws?token=secret&client_id=c1')
    expect(api.workspaceFileUrl('a/b.fits')).toBe(
      '/api/workspace/file?path=a%2Fb.fits&token=secret',
    )
  })

  it('requests JSON with auth headers and maps errors to ApiError', async () => {
    window.sessionStorage.setItem('astro-canvas-token', 'tok')
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: 'ok', version: '1' }))
    expect(await api.getHealth()).toEqual({ status: 'ok', version: '1' })
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/health')
    expect((init.headers as Record<string, string>)['Authorization']).toBe('Bearer tok')

    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'nope' }, 404))
    await expect(api.getWorkflow('x')).rejects.toMatchObject({ status: 404, message: 'nope' })
    fetchMock.mockResolvedValueOnce(new Response('oops', { status: 500, statusText: 'Boom' }))
    await expect(api.getTypes()).rejects.toBeInstanceOf(ApiError)
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))
    expect(await api.deleteWorkspacePath('a', true)).toBeUndefined()
    expect(fetchMock.mock.calls[3]?.[0]).toBe('/api/workspace/file?path=a&recursive=true')
  })

  it('builds the workspace and output URLs', async () => {
    fetchMock.mockImplementation(async () => jsonResponse({}))
    await api.getWorkspaceTree('samples/rbcodes', 2, true)
    await api.getWorkspaceFileInfo('a.fits', false)
    await api.sniffWorkspaceFile('a.fits')
    await api.makeWorkspaceDir('new')
    await api.selectWorkspace('C:/ws', true)
    const urls = fetchMock.mock.calls.map((c) => c[0])
    expect(urls).toEqual([
      '/api/workspace/tree?path=samples%2Frbcodes&depth=2&hidden=true',
      '/api/workspace/info?path=a.fits&hash=false',
      '/api/workspace/sniff?path=a.fits',
      '/api/workspace/mkdir',
      '/api/workspace/select',
    ])
    const select = fetchMock.mock.calls[4]?.[1] as RequestInit | undefined
    expect(JSON.parse(String(select?.body))).toEqual({ path: 'C:/ws', create: true })
    expect(api.outputUrl('wf', 'n', 'out', 'arrow')).toBe(
      '/api/outputs/n/out?workflow_id=wf&fmt=arrow',
    )
    fetchMock.mockResolvedValueOnce(new Response(new Uint8Array([1, 2, 3]), { status: 200 }))
    const buffer = await api.fetchOutputArrow('wf', 'n', 'out')
    expect(new Uint8Array(buffer)).toEqual(new Uint8Array([1, 2, 3]))
    fetchMock.mockResolvedValueOnce(new Response('', { status: 404, statusText: 'Not Found' }))
    await expect(api.fetchOutputArrow('wf', 'n', 'out')).rejects.toBeInstanceOf(ApiError)
  })

  it('uploads small files in one request with progress', async () => {
    window.sessionStorage.setItem('astro-canvas-token', 'tok')
    const progress: number[] = []
    const result = await uploadWorkspaceFile(new File(['abc'], 'a.dat'), {
      dir: 'data',
      onConflict: 'rename',
      onProgress: (loaded) => progress.push(loaded),
    })
    expect(result.complete).toBe(true)
    expect(progress).toEqual([1])
    const xhr = FakeXhr.instances[0]
    expect(xhr?.method).toBe('POST')
    expect(xhr?.url).toBe('/api/workspace/upload')
    expect(xhr?.headers['Authorization']).toBe('Bearer tok')
    expect(xhr?.form?.get('dir')).toBe('data')
    expect(xhr?.form?.get('filename')).toBe('a.dat')
    expect(xhr?.form?.get('on_conflict')).toBe('rename')
    expect(xhr?.form?.get('chunk_index')).toBeNull()
  })

  it('chunks large files and reports errors and aborts', async () => {
    const file = new File(['0123456789'], 'big.bin')
    const progress: number[] = []
    const result = await uploadWorkspaceFile(file, {
      chunkThreshold: 4,
      chunkSize: 4,
      onProgress: (loaded, total) => progress.push(Math.round((loaded / total) * 100)),
    })
    expect(result.complete).toBe(true)
    expect(FakeXhr.instances).toHaveLength(3)
    const indexes = FakeXhr.instances.map((x) => x.form?.get('chunk_index'))
    expect(indexes).toEqual(['0', '1', '2'])
    expect(FakeXhr.instances[0]?.form?.get('chunk_count')).toBe('3')
    const ids = new Set(FakeXhr.instances.map((x) => x.form?.get('upload_id')))
    expect(ids.size).toBe(1)
    expect(progress.length).toBe(3)

    FakeXhr.status = 409
    FakeXhr.body = { detail: 'exists' }
    await expect(uploadWorkspaceFile(new File(['x'], 'x.bin'))).rejects.toMatchObject({
      status: 409,
      message: 'exists',
    })
    FakeXhr.status = 500
    FakeXhr.body = 'not json'
    await expect(uploadWorkspaceFile(new File(['x'], 'x.bin'))).rejects.toMatchObject({
      status: 500,
    })

    FakeXhr.status = 201
    FakeXhr.body = { complete: true, received: 1 }
    const controller = new AbortController()
    controller.abort()
    await expect(
      uploadWorkspaceFile(new File(['x'], 'x.bin'), { signal: controller.signal }),
    ).rejects.toMatchObject({ message: 'upload cancelled' })
  })
})
