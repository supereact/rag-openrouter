export type Role = 'admin' | 'editor' | 'reader'
export interface Identity {
  user_id: number
  tenant_id: number
  username: string
  role: Role
}

export interface CreditSummary {
  mode: 'disabled' | 'sandbox' | 'live'
  payments_enabled: boolean; usage_enforced: boolean
  balance: string; reserved: string; available: string
  service_fee_percent: string; minimum_credits: string; maximum_credits: string
  networks: {id: string; label: string}[]
}
export interface CreditOrder {
  id: string; mode: 'sandbox' | 'live'; credits: string; service_fee: string
  total_usd: string; network: string; status: string; pay_address: string | null
  pay_amount: string | null; expires_at: string | null; created_at: string
}
export interface CreditTransaction {
  id: number; kind: 'topup' | 'usage' | 'refund'; amount: string; created_at: string
}
export interface CreditHistory<T> { items: T[]; total: number; page: number; page_size: number; pages: number }
export interface DocumentRecord {
  id: number
  title: string
  owner_user_id: number
  created_at: string
}
export interface LibraryRow {
  kind: 'document' | 'upload'; id: string; title: string; created_at: string;
  status: 'indexed' | 'queued' | 'processing' | 'failed'; owner_user_id: number;
  error: string | null; can_manage: boolean;
  assigned_users: {id: number; username: string}[] | null
}
export interface DocumentLibrary { items: LibraryRow[]; total: number; page: number; page_size: number; pages: number }
export interface DocumentAccessUser {
  id: number
  username: string
  email: string | null
  is_active: boolean
  shared: boolean
  automatic_access: 'owner' | 'admin' | null
}
export interface DocumentAccess { users: DocumentAccessUser[] }
export interface DocumentAccessUpdate { grant_user_ids: number[]; revoke_user_ids: number[] }
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
  redacted?: boolean
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

export interface AuthToken { access_token: string; token_type: 'bearer'; expires_in: number }
export interface AdminUser {
  id: number; username: string; email: string | null; role: Role; is_active: boolean; created_at: string
}
export interface AdminInvitation {
  id: number; email: string; role: 'reader' | 'editor'; created_at: string; expires_at: string; used_at: string | null
}
export interface NewInvitation { invitation_id: number; invitation_code: string; email: string; role: 'reader' | 'editor'; expires_in_hours: number }
export interface AdminDashboard {
  users_total: number; users_active: number; documents_total: number;
  jobs: Record<string, number>;
  recent_actions: {action: string; username: string; created_at: string}[]
}
export interface AuditLog {
  items: {id: number; created_at: string; user_id: number; username: string; action: string;
    document_id: number | null; document_title: string | null; result_count: number | null}[]
  page: number; page_size: number; total: number; pages: number;
  actions: string[]; users: {id: number; username: string}[]
}


export interface UsageUser {
  user_id: number; username: string; email: string | null; is_active: boolean
  overall_credits: string; week_credits: string
  requests: number; cost_reported_requests: number
  week_requests: number; week_cost_reported_requests: number
}
export interface UsageDay {
  date: string; credits: string; requests: number; cost_reported_requests: number
}
export interface AdminUsage {
  scope: 'tenant'; provider: 'openrouter'; cost_unit: 'provider_reported_credits'
  history_since: string; week_starts_utc: string; chart_days: number
  overall_credits: string; week_credits: string
  requests: number; cost_reported_requests: number
  week_requests: number; week_cost_reported_requests: number
  daily: UsageDay[]; users: UsageUser[]
}

// M10.2: monthly credit guardrails (all amounts are decimal strings).
export interface BudgetStatus {
  monthly_limit_credits: string | null
  paused: boolean
  spent_credits: string
  reserved_credits: string
  remaining_credits: string | null
  unknown_cost_requests: number
}
export interface TenantBudgetStatus extends BudgetStatus {
  reservation_credits: string
}
export interface UserBudgetStatus extends BudgetStatus {
  user_id: number
  username: string
  email: string | null
}
export interface AdminBudgets {
  month_start_utc: string
  tenant: TenantBudgetStatus
  users: UserBudgetStatus[]
}

// M10.3: private, persistent conversation history.
export interface SavedConversation {
  id: number
  title: string
  created_at: string
  updated_at: string
}
export interface SavedExchange {
  id: number
  question: string
  answer: string
  sources: SearchHit[]
  redacted: boolean
  created_at: string
}
export interface SavedConversationDetail extends SavedConversation {
  messages: SavedExchange[]
}
export interface ConversationAskResponse extends AskResponse { message_id: number }

// M10.4: tenant-scoped knowledge bases; document ACLs still apply.
export interface KnowledgeBase {
  id: number
  name: string
  description: string
  created_by: number
  created_at: string
  document_count: number
  can_manage: boolean
}

// M10.5: owner-only answer ratings and tenant-scoped aggregate reporting.
export type FeedbackRating = 'up' | 'down'
export type FeedbackReason = 'incorrect' | 'incomplete' | 'irrelevant' | 'outdated' | 'other'
export interface AnswerFeedback {
  message_id: number
  rating: FeedbackRating
  reason: FeedbackReason | null
  updated_at: string
}
export interface AdminFeedback {
  scope: 'tenant'
  days: 7 | 30
  all_time: {total: number; up: number; down: number}
  period: {total: number; up: number; down: number}
  positive_rate: number | null
  daily: {date: string; up: number; down: number}[]
  downvote_reasons: {reason: string; count: number}[]
  recent_downvotes: {username: string; reason: string | null; created_at: string}[]
  disclaimer: string
}
