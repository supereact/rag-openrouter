import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('browser API client', () => {
  it('uses protected library queries, access deltas and failed-job deletion', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response('{}', {status:200}))
    vi.stubGlobal('fetch',fetchMock)
    await api.library('key',new URLSearchParams({page:'2',page_size:'50',q:'a & b',status:'failed',file_type:'pdf'}))
    expect(fetchMock.mock.calls[0][0]).toBe('/api/documents/library?page=2&page_size=50&q=a+%26+b&status=failed&file_type=pdf')
    await api.documentAccess('key',11)
    expect(fetchMock.mock.calls[1][0]).toBe('/api/documents/11/access')
    await api.updateDocumentAccess('key',11,{grant_user_ids:[2,3],revoke_user_ids:[4]})
    expect(fetchMock.mock.calls[2][1].method).toBe('PATCH')
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({grant_user_ids:[2,3],revoke_user_ids:[4]})
    fetchMock.mockResolvedValueOnce(new Response(null,{status:204}))
    await expect(api.removeJob('key','failed-id')).resolves.toBeUndefined()
    expect(fetchMock.mock.calls[3][0]).toBe('/api/ingestion-jobs/failed-id')
    expect(fetchMock.mock.calls[3][1].method).toBe('DELETE')
    for (const [, options] of fetchMock.mock.calls) expect(options.headers.get('Authorization')).toBe('Bearer key')
  })
  it('password login sends no Authorization header and never persists a token', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      access_token:'rags_test',token_type:'bearer',expires_in:43200,
    }), {status:200,headers:{'Content-Type':'application/json'}}))
    vi.stubGlobal('fetch',fetchMock)
    await expect(api.loginPassword('person@example.org','my strong passphrase')).resolves.toHaveProperty('access_token','rags_test')
    const [url,opts] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/auth/login')
    expect(opts.headers.Authorization).toBeUndefined()
    expect(JSON.parse(opts.body)).toEqual({email:'person@example.org',password:'my strong passphrase'})
  })

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

describe('knowledge-base API (M10.4)', () => {
  it('sends the selected knowledge base in the saved-chat request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      question: 'What is the backup policy?', answer: 'Backups are daily', sources: [], message_id: 12,
    }), {status: 200, headers: {'Content-Type':'application/json'}}))
    vi.stubGlobal('fetch', fetchMock)
    await api.askConversation('rag_test_key', 42, 'What is the backup policy?', 5, 17)
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/conversations/42/ask')
    expect(JSON.parse(options.body).knowledge_base_id).toBe(17)
    expect((options.headers as Headers).get('Authorization')).toBe('Bearer rag_test_key')
  })

  it('uses protected same-origin endpoints for collection memberships', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, {status: 204}))
    vi.stubGlobal('fetch', fetchMock)
    await api.addKnowledgeBaseDocument('rag_test_key', 3, 8)
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/knowledge-bases/3/documents/8')
    expect(options.method).toBe('PUT')
    expect((options.headers as Headers).get('Authorization')).toBe('Bearer rag_test_key')
  })
})
