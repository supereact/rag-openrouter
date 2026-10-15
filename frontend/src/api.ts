import type { AskResponse, DocumentRecord, Identity, IngestResponse, IngestionJob, EnqueuedJob } from './types'

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(key: string, path: string, init: RequestInit = {}): Promise<T> {
  // Same-origin Vite proxy: the browser never sends the key to another host.
  const headers = new Headers(init.headers)
  headers.set('Authorization', `Bearer ${key}`)
  if (init.body && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  let response: Response
  try {
    response = await fetch(`/api${path}`, { ...init, headers, cache: 'no-store' })
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

export const api = {
  me: (key: string) => request<Identity>(key, '/me'),
  ask: (key: string, question: string, topK: number) =>
    request<AskResponse>(key, '/ask', {
      method: 'POST', body: JSON.stringify({ question, top_k: topK }),
    }),
  documents: async (key: string) => {
    const result = await request<{ documents: DocumentRecord[] }>(key, '/documents')
    return result.documents
  },
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
  reindex: (key: string, id: number, file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request<IngestResponse>(key, `/documents/${id}/reindex-pdf`, { method: 'POST', body })
  },
  pdf: async (key: string, id: number): Promise<Blob> => {
    const response = await fetch(`/api/documents/${id}/original-pdf`, {
      headers: { Authorization: `Bearer ${key}` }, cache: 'no-store',
    })
    if (!response.ok) throw new ApiError(response.status,
      response.status === 404 ? 'Original PDF unavailable or not authorized' :
      response.status === 401 ? 'Unauthorized' : `PDF request failed (${response.status})`)
    return response.blob()
  },
  remove: (key: string, id: number) =>
    request<void>(key, `/documents/${id}`, { method: 'DELETE' }),
}
