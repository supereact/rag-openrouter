import type { AskResponse, DocumentRecord, DocumentAccess, DocumentAccessUpdate, Identity, IngestResponse, IngestionJob, EnqueuedJob, AuthToken, AdminUser, AdminInvitation, NewInvitation, AdminDashboard, AdminUsage, AdminBudgets, Role, SavedConversation, SavedConversationDetail, KnowledgeBase, ConversationAskResponse, AnswerFeedback, AdminFeedback } from './types'
import type { DocumentLibrary, AuditLog } from './types'
import type { CreditSummary, CreditHistory, CreditOrder, CreditTransaction } from './types'
import type { SupportChat, SupportChatList, SupportMessage, SupportMessages } from './types'
import type { AccountSessions, AccountAction } from './types'

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(key: string, path: string, init: RequestInit = {}): Promise<T> {
  // Same-origin Vite proxy: the browser never sends the key to another host.
  const headers = new Headers(init.headers)
  // An empty key selects the server-validated HttpOnly browser session.
  if (key) headers.set('Authorization', `Bearer ${key}`)
  else headers.set('X-RAG-CSRF', '1')
  if (init.body && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  let response: Response
  try {
    response = await fetch(`/api${path}`, { ...init, headers, credentials: 'same-origin', cache: 'no-store' })
  } catch {
    throw new ApiError(0, 'Cannot reach the API. Check that FastAPI is running on port 8000.')
  }
  if (!response.ok) {
    let detail = `Request failed (HTTP ${response.status})`
    try {
      const payload: unknown = await response.json()
      if (payload && typeof payload === 'object' && 'detail' in payload) {
        const value = (payload as { detail: unknown }).detail
        if (typeof value === 'string') detail = value
      }
    } catch { /* Invalid response body: retain HTTP message */ }
    throw new ApiError(response.status, detail)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}


async function publicPost<T>(path: string, body: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-RAG-CSRF': '1'},
      body: JSON.stringify(body), credentials: 'same-origin', cache: 'no-store',
    })
  } catch { throw new ApiError(0, 'Cannot reach FastAPI') }
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as {detail?: string} | null
    throw new ApiError(response.status, typeof payload?.detail === 'string' ? payload.detail : `Request failed (${response.status})`)
  }
  return await response.json() as T
}

export const api = {
  accountSessions: (key: string, page: number, size: number, signal?: AbortSignal) =>
    request<AccountSessions>(key, `/auth/sessions?page=${page}&page_size=${size}`, {signal}),
  changePassword: (key: string, current_password: string, new_password: string) =>
    request<AccountAction>(key, '/auth/password', {method: 'POST', body: JSON.stringify({current_password, new_password})}),
  revokeOwnSession: (key: string, id: number) =>
    request<AccountAction>(key, `/auth/sessions/${id}`, {method: 'DELETE'}),
  revokeOtherSessions: (key: string) =>
    request<AccountAction>(key, '/auth/sessions/revoke-others', {method: 'POST'}),
  supportChats: (key: string, page: number, pageSize: number, status: string, signal?: AbortSignal) =>
    request<SupportChatList>(key, `/support/chats?${new URLSearchParams({page: String(page), page_size: String(pageSize), status})}`, {signal}),
  createSupportChat: (key: string, subject: string, body: string, request_key: string) =>
    request<SupportChat>(key, '/support/chats', {method: 'POST', body: JSON.stringify({subject, body, request_key})}),
  supportMessages: (key: string, id: number, afterId: number, signal?: AbortSignal) =>
    request<SupportMessages>(key, `/support/chats/${id}/messages?after_id=${afterId}`, {signal}),
  sendSupportMessage: (key: string, id: number, body: string, request_key: string) =>
    request<SupportMessage>(key, `/support/chats/${id}/messages`, {method: 'POST', body: JSON.stringify({body, request_key})}),
  setSupportStatus: (key: string, id: number, status: 'open' | 'closed') =>
    request<SupportChat>(key, `/support/chats/${id}`, {method: 'PATCH', body: JSON.stringify({status})}),
  credits: (key: string, signal?: AbortSignal) => request<CreditSummary>(key, '/credits', {signal}),
  creditOrders: (key: string, page: number, size: number, signal?: AbortSignal) =>
    request<CreditHistory<CreditOrder>>(key, `/credits/orders?page=${page}&page_size=${size}`, {signal}),
  creditTransactions: (key: string, page: number, size: number, signal?: AbortSignal) =>
    request<CreditHistory<CreditTransaction>>(key, `/credits/transactions?page=${page}&page_size=${size}`, {signal}),
  purchaseCredits: (key: string, credits: string, network: string, request_key: string) =>
    request<CreditOrder>(key, '/credits/orders', {method: 'POST', body: JSON.stringify({credits, network, request_key})}),
  checkCreditOrder: (key: string, id: string) =>
    request<CreditOrder>(key, `/credits/orders/${encodeURIComponent(id)}/check`, {method: 'POST'}),
  browserSession: () => request<Identity>('', '/auth/session'),
  browserLogin: (email: string, password: string) => publicPost<Identity>('/auth/browser/login', {email, password}),
  browserRegister: (invitation_code: string, email: string, username: string, password: string) =>
    publicPost<Identity>('/auth/browser/register', {invitation_code, email, username, password}),
  browserLogout: () => request<void>('', '/auth/browser/logout', {method: 'POST'}),
  loginPassword: (email: string, password: string) => publicPost<AuthToken>('/auth/login', {email, password}),
  register: (invitation_code: string, email: string, username: string, password: string) => publicPost<AuthToken>('/auth/register', { invitation_code, email, username, password }),
  logout: (token: string) => request<void>(token, '/auth/logout', {method: 'POST'}),
  adminDashboard: (token: string) => request<AdminDashboard>(token, '/admin/dashboard'),
  adminAuditLog: (key: string, query: URLSearchParams, signal?: AbortSignal) =>
    request<AuditLog>(key, `/admin/audit-log?${query}`, {signal}),
  adminUsage: (token: string, days: 7 | 30 = 30) => request<AdminUsage>(token, `/admin/usage?days=${days}`),
  adminBudgets: (token: string) => request<AdminBudgets>(token, '/admin/budgets'),
  setTenantBudget: (token: string, values: {monthly_limit_credits: string | null; paused: boolean; reservation_credits: string}) =>
    request<AdminBudgets>(token, '/admin/budgets/tenant', {method: 'PUT', body: JSON.stringify(values)}),
  setUserBudget: (token: string, userId: number, values: {monthly_limit_credits: string | null; paused: boolean}) =>
    request<AdminBudgets>(token, `/admin/budgets/users/${userId}`, {method: 'PUT', body: JSON.stringify(values)}),
  adminUsers: async (token: string) => (await request<{users: AdminUser[]}>(token, '/admin/users')).users,
  adminInvitations: async (token: string) => (await request<{invitations: AdminInvitation[]}>(token, '/admin/invitations')).invitations,
  adminInvite: (token: string, email: string, role: 'reader' | 'editor') => request<NewInvitation>(token, '/admin/invitations', { method: 'POST', body: JSON.stringify({email,role}) }),
  adminUpdateUser: (token: string, userId: number, values: {role?: Role; is_active?: boolean}) => request<AdminUser>(token, `/admin/users/${userId}`, {method: 'PATCH', body: JSON.stringify(values)}),
  adminRevokeSessions: (token: string, userId: number) => request<void>(token, `/admin/users/${userId}/revoke-sessions`, {method: 'POST'}),
  conversationFeedback: async (key: string, conversationId: number) =>
    (await request<{ feedback: AnswerFeedback[] }>(key, `/conversations/${conversationId}/feedback`)).feedback,
  setAnswerFeedback: (key: string, conversationId: number, messageId: number,
                      rating: 'up' | 'down', reason: string | null = null) =>
    request<AnswerFeedback>(key, `/conversations/${conversationId}/messages/${messageId}/feedback`, {
      method: 'PUT', body: JSON.stringify({rating, reason}),
    }),
  deleteAnswerFeedback: (key: string, conversationId: number, messageId: number) =>
    request<void>(key, `/conversations/${conversationId}/messages/${messageId}/feedback`, {method:'DELETE'}),
  adminFeedback: (key: string, days: 7 | 30 = 30) =>
    request<AdminFeedback>(key, `/admin/feedback?days=${days}`),
  conversations: async (key: string) =>
    (await request<{ conversations: SavedConversation[] }>(key, '/conversations')).conversations,
  conversation: (key: string, id: number) =>
    request<SavedConversationDetail>(key, `/conversations/${id}`),
  createConversation: (key: string, title: string) =>
    request<SavedConversation>(key, '/conversations', { method: 'POST', body: JSON.stringify({ title }) }),
  renameConversation: (key: string, id: number, title: string) =>
    request<SavedConversation>(key, `/conversations/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) }),
  deleteConversation: (key: string, id: number) =>
    request<void>(key, `/conversations/${id}`, { method: 'DELETE' }),
  askConversation: (key: string, id: number, question: string, topK: number, knowledgeBaseId: number | null = null) =>
    request<ConversationAskResponse>(key, `/conversations/${id}/ask`, {
      method: 'POST', body: JSON.stringify({ question, top_k: topK, knowledge_base_id: knowledgeBaseId }),
    }),
  knowledgeBases: async (key: string) =>
    (await request<{ knowledge_bases: KnowledgeBase[] }>(key, '/knowledge-bases')).knowledge_bases,
  createKnowledgeBase: (key: string, name: string, description = '') =>
    request<KnowledgeBase>(key, '/knowledge-bases', {
      method: 'POST', body: JSON.stringify({ name, description }),
    }),
  renameKnowledgeBase: (key: string, id: number, name: string, description: string) =>
    request<KnowledgeBase>(key, `/knowledge-bases/${id}`, {
      method: 'PATCH', body: JSON.stringify({ name, description }),
    }),
  deleteKnowledgeBase: (key: string, id: number) =>
    request<void>(key, `/knowledge-bases/${id}`, { method: 'DELETE' }),
  knowledgeBaseDocuments: async (key: string, id: number) =>
    (await request<{ documents: DocumentRecord[] }>(key, `/knowledge-bases/${id}/documents`)).documents,
  addKnowledgeBaseDocument: (key: string, id: number, documentId: number) =>
    request<void>(key, `/knowledge-bases/${id}/documents/${documentId}`, { method: 'PUT' }),
  removeKnowledgeBaseDocument: (key: string, id: number, documentId: number) =>
    request<void>(key, `/knowledge-bases/${id}/documents/${documentId}`, { method: 'DELETE' }),
  me: (key: string) => request<Identity>(key, '/me'),
  ask: (key: string, question: string, topK: number, knowledgeBaseId: number | null = null) =>
    request<AskResponse>(key, '/ask', {
      method: 'POST', body: JSON.stringify({ question, top_k: topK, knowledge_base_id: knowledgeBaseId }),
    }),
  documents: async (key: string) => {
    const result = await request<{ documents: DocumentRecord[] }>(key, '/documents')
    return result.documents
  },
  library: (key: string, query: URLSearchParams, signal?: AbortSignal) =>
    request<DocumentLibrary>(key, `/documents/library?${query}`, {signal}),
  removeJob: (key: string, id: string) => request<void>(key, `/ingestion-jobs/${encodeURIComponent(id)}`, {method: 'DELETE'}),
  upload: (key: string, file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request<IngestResponse>(key, '/documents/upload', { method: 'POST', body })
  },
  uploadQueued: (key: string, file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request<EnqueuedJob>(key, '/documents/upload-async', { method: 'POST', body })
  },
  jobs: (key: string) => request<IngestionJob[]>(key, '/ingestion-jobs'),
  job: (key: string, id: string) =>
    request<IngestionJob>(key, `/ingestion-jobs/${encodeURIComponent(id)}`),
  share: (key: string, id: number, username: string) =>
    request<{ status: string }>(key, `/documents/${id}/share`, {
      method: 'POST', body: JSON.stringify({ username }),
    }),
  documentAccess: (key: string, id: number) =>
    request<DocumentAccess>(key, `/documents/${id}/access`),
  updateDocumentAccess: (key: string, id: number, changes: DocumentAccessUpdate) =>
    request<DocumentAccess>(key, `/documents/${id}/access`, {
      method: 'PATCH', body: JSON.stringify(changes),
    }),
  reindex: (key: string, id: number, file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request<IngestResponse>(key, `/documents/${id}/reindex-pdf`, { method: 'POST', body })
  },
  pdf: async (key: string, id: number): Promise<Blob> => {
    const response = await fetch(`/api/documents/${id}/original-pdf`, {
      headers: key ? { Authorization: `Bearer ${key}` } : {}, credentials: 'same-origin', cache: 'no-store',
    })
    if (!response.ok) throw new ApiError(response.status,
      response.status === 404 ? 'Original PDF unavailable or not authorized' :
      response.status === 401 ? 'Unauthorized' : `PDF request failed (${response.status})`)
    return response.blob()
  },
  remove: (key: string, id: number) =>
    request<void>(key, `/documents/${id}`, { method: 'DELETE' }),
}
