import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('browser API client', () => {
  it('sends bearer key to same-origin proxied path', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      user_id: 1, tenant_id: 2, username: 'admin', role: 'admin',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(api.me('rag_test_key')).resolves.toMatchObject({ username: 'admin' })
    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/me')
    expect((options.headers as Headers).get('Authorization')).toBe('Bearer rag_test_key')
    expect(options.cache).toBe('no-store')
  })

  it('never sets multipart Content-Type manually (browser sets boundary)', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      document_id: 9, chunk_count: 2, already_exists: false,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    const file = new File(['# test document\nThis is a sufficiently long policy.'], 'test.md', {type: 'text/markdown'})
    await api.upload('key', file)
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/documents/upload')
    expect(options.body).toBeInstanceOf(FormData)
    expect((options.headers as Headers).has('Content-Type')).toBe(false)
  })

  it('reports unauthorized without leaking API key', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({detail: 'Invalid or revoked API key'}),
      { status: 401, headers: { 'Content-Type': 'application/json' } },
    )))
    await expect(api.me('rag_secret')).rejects.toEqual(
      expect.objectContaining({ status: 401, message: 'Invalid or revoked API key' }),
    )
  })

  it('uses DELETE and handles HTTP 204 empty response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(api.remove('key', 11)).resolves.toBeUndefined()
    expect(fetchMock.mock.calls[0][1].method).toBe('DELETE')
  })

  it('fetches PDF bytes with Authorization header and never a key in URL', async () => {
    const bytes = new Blob(['%PDF-1.4'], { type: 'application/pdf' })
    const fetchMock = vi.fn().mockResolvedValue(new Response(bytes, { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const result = await api.pdf('sensitive-key', 17)
    expect(result).toBeInstanceOf(Blob)
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/documents/17/original-pdf')
    expect(url).not.toContain('sensitive-key')
    expect(options.headers.Authorization).toBe('Bearer sensitive-key')
    expect(options.cache).toBe('no-store')
  })

  it('gives a useful network error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))
    await expect(api.me('secret')).rejects.toBeInstanceOf(ApiError)
  })
})
