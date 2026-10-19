import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('browser API client', () => {
  it('uses owner-only account endpoints and keeps credentials inside request bodies', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response('{}', {status:200}))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()
    await api.accountSessions('', 2, 50, controller.signal)
    await api.changePassword('', 'old-test-password', 'new-test-password')
    await api.revokeOwnSession('', 17)
    await api.revokeOtherSessions('')
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/auth/sessions?page=2&page_size=50', '/api/auth/password',
      '/api/auth/sessions/17', '/api/auth/sessions/revoke-others',
    ])
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({current_password:'old-test-password',new_password:'new-test-password'})
    expect(fetchMock.mock.calls[2][1].method).toBe('DELETE')
    expect(fetchMock.mock.calls[0][1].signal).toBe(controller.signal)
    for (const [url, options] of fetchMock.mock.calls) {
      expect(url).not.toMatch(/old-test-password|new-test-password/)
      expect(options.headers.get('X-RAG-CSRF')).toBe('1')
      expect(options.credentials).toBe('same-origin')
      expect(options.cache).toBe('no-store')
    }
  })
  it('uses protected support endpoints with CSRF, pagination and idempotency keys', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response('{}', {status: 200}))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()
    await api.supportChats('', 2, 50, 'open', controller.signal)
    await api.createSupportChat('', 'Help', 'Please help', 'request-key')
    await api.supportMessages('', 4, 12, controller.signal)
    await api.sendSupportMessage('', 4, 'Reply', 'message-key')
    await api.setSupportStatus('', 4, 'closed')
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/support/chats?page=2&page_size=50&status=open', '/api/support/chats',
      '/api/support/chats/4/messages?after_id=12', '/api/support/chats/4/messages', '/api/support/chats/4',
    ])
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({subject:'Help',body:'Please help',request_key:'request-key'})
    expect(JSON.parse(fetchMock.mock.calls[3][1].body)).toEqual({body:'Reply',request_key:'message-key'})
    for (const [, options] of fetchMock.mock.calls) {
      expect(options.headers.get('X-RAG-CSRF')).toBe('1')
      expect(options.headers.has('Authorization')).toBe(false)
      expect(options.credentials).toBe('same-origin')
      expect(options.cache).toBe('no-store')
    }
  })
  it('uses private credits endpoints, CSRF and a stable checkout key', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response('{}', {status: 200}))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()
    await api.credits('', controller.signal)
    await api.creditOrders('', 2, 50, controller.signal)
    await api.creditTransactions('', 1, 20, controller.signal)
    await api.purchaseCredits('', '10.00', 'usdttrc20', 'synthetic-request-id')
    await api.checkCreditOrder('', 'synthetic-order-id')
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/credits', '/api/credits/orders?page=2&page_size=50',
      '/api/credits/transactions?page=1&page_size=20', '/api/credits/orders',
      '/api/credits/orders/synthetic-order-id/check',
    ])
    expect(JSON.parse(fetchMock.mock.calls[3][1].body)).toEqual({credits:'10.00',network:'usdttrc20',request_key:'synthetic-request-id'})
    for (const [, options] of fetchMock.mock.calls) {
      expect(options.headers.get('X-RAG-CSRF')).toBe('1')
      expect(options.headers.has('Authorization')).toBe(false)
      expect(options.credentials).toBe('same-origin')
      expect(options.cache).toBe('no-store')
    }
  })
  it('requests audit history with filters, bearer auth and cancellation',async () => {
    const fetchMock=vi.fn().mockResolvedValue(new Response('{}',{status:200}))
    vi.stubGlobal('fetch',fetchMock)
    const controller=new AbortController()
    await api.adminAuditLog('key',new URLSearchParams('page=2&action=search&user_id=3&date_from=2026-10-16'),controller.signal)
    const [url,options]=fetchMock.mock.calls[0]
    expect(url).toBe('/api/admin/audit-log?page=2&action=search&user_id=3&date_from=2026-10-16')
    expect(options.headers.get('Authorization')).toBe('Bearer key')
    expect(options.signal).toBe(controller.signal)
  })
  it('passes a cancellation signal through to the library request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}',{status:200}))
    vi.stubGlobal('fetch',fetchMock)
    const controller = new AbortController()
    await api.library('key',new URLSearchParams('page=1'),controller.signal)
    expect(fetchMock.mock.calls[0][1].signal).toBe(controller.signal)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/documents/library?page=1')
  })
  it('uses same-origin cookies and CSRF headers without exposing a session token', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response(JSON.stringify({
      user_id:2,tenant_id:7,username:'writer',role:'editor',
    }), {status:200}))
    vi.stubGlobal('fetch',fetchMock)
    await api.browserLogin('user@example.org','synthetic-password')
    await api.browserSession()
    await api.documents('')
    await api.pdf('',11)
    await api.browserRegister('invite_synthetic','user@example.org','writer','synthetic-password')
    fetchMock.mockResolvedValueOnce(new Response(null,{status:204}))
    await api.browserLogout()
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/auth/browser/login','/api/auth/session','/api/documents',
      '/api/documents/11/original-pdf','/api/auth/browser/register','/api/auth/browser/logout',
    ])
    for (const [,options] of fetchMock.mock.calls) {
      expect(options.credentials).toBe('same-origin')
      expect(new Headers(options.headers).has('Authorization')).toBe(false)
    }
    for (const index of [0,1,2,4,5]) {
      expect(new Headers(fetchMock.mock.calls[index][1].headers).get('X-RAG-CSRF')).toBe('1')
    }
  })
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
