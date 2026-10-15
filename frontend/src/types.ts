export type Role = 'admin' | 'editor' | 'reader'
export interface Identity {
  user_id: number
  tenant_id: number
  username: string
  role: Role
}
export interface DocumentRecord {
  id: number
  title: string
  owner_user_id: number
  created_at: string
}
export interface SearchHit {
  source_number: number
  document_id: number
  title: string
  chunk_index: number
  content: string
  similarity: number
  page_number: number | null
}
export interface AskResponse {
  question: string
  answer: string
  sources: SearchHit[]
}
export interface IngestResponse {
  document_id: number
  chunk_count: number
  already_exists: boolean
}
export interface ChatEntry {
  id: number
  question: string
  answer: string
  sources: SearchHit[]
  createdAt: Date
}

export type JobStatus = 'queued' | 'processing' | 'completed' | 'failed'
export interface IngestionJob {
  id: string
  filename: string
  status: JobStatus
  document_id: number | null
  chunk_count: number | null
  already_exists: boolean | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}
export interface EnqueuedJob {
  id: string
  filename: string
  status: 'queued'
  created_at: string
}
