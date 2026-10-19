import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import App from './App'
import { api, ApiError } from './api'
import { navigate } from './navigation'

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>()
  return {
    ...actual,
    api: {
      credits: vi.fn(), creditOrders: vi.fn(), creditTransactions: vi.fn(), purchaseCredits: vi.fn(), checkCreditOrder: vi.fn(),
      library: vi.fn(), removeJob: vi.fn(), documentAccess: vi.fn(), updateDocumentAccess: vi.fn(),
      me: vi.fn(), ask: vi.fn(), documents: vi.fn(), upload: vi.fn(),
      conversationFeedback: vi.fn(), setAnswerFeedback: vi.fn(), deleteAnswerFeedback: vi.fn(), adminFeedback: vi.fn(),
      conversations: vi.fn(), conversation: vi.fn(), createConversation: vi.fn(),
      askConversation: vi.fn(), renameConversation: vi.fn(), deleteConversation: vi.fn(),
      loginPassword: vi.fn(), register: vi.fn(), logout: vi.fn(),
      browserSession: vi.fn(), browserLogin: vi.fn(), browserRegister: vi.fn(), browserLogout: vi.fn(),
      adminAuditLog: vi.fn(), adminDashboard: vi.fn(), adminUsage: vi.fn(), adminBudgets: vi.fn(), adminUsers: vi.fn(), adminInvitations: vi.fn(),
      adminInvite: vi.fn(), adminUpdateUser: vi.fn(), adminRevokeSessions: vi.fn(),
      knowledgeBases: vi.fn(), createKnowledgeBase: vi.fn(), renameKnowledgeBase: vi.fn(),
      deleteKnowledgeBase: vi.fn(), knowledgeBaseDocuments: vi.fn(),
      addKnowledgeBaseDocument: vi.fn(), removeKnowledgeBaseDocument: vi.fn(),
      uploadQueued: vi.fn(), jobs: vi.fn(), job: vi.fn(),
      share: vi.fn(), reindex: vi.fn(), remove: vi.fn(), pdf: vi.fn(),
    },
  }
})

// Mock browser storage so the test detects accidental key persistence,
// even in environments that do not expose localStorage.
const storage = {
  getItem: vi.fn(),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn(),
  key: vi.fn(),
  length: 0,
}

const account = { user_id: 2, tenant_id: 1, role: 'reader' as const, username: 'analyst' }

async function login() {
  fireEvent.click(await screen.findByRole('button', {name:'API key'}))
  fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'rag_dummy_key' } })
  fireEvent.click(screen.getByRole('button', { name: /connect to workspace/i }))
  await screen.findByRole('navigation', { name: 'Main navigation' })
}

beforeEach(() => {
  vi.clearAllMocks()
  window.history.replaceState({}, "", "/")
  vi.stubGlobal('localStorage', storage)
  vi.mocked(api.browserSession).mockReset().mockRejectedValue(new ApiError(401, 'No session'))
  vi.mocked(api.browserLogin).mockReset().mockResolvedValue(account)
  vi.mocked(api.browserRegister).mockReset().mockResolvedValue(account)
  vi.mocked(api.browserLogout).mockReset().mockResolvedValue(undefined)
  vi.mocked(api.me).mockResolvedValue(account)
  vi.mocked(api.credits).mockResolvedValue({mode:'disabled',payments_enabled:false,usage_enforced:false,balance:'0',reserved:'0',available:'0',service_fee_percent:'5.5',minimum_credits:'10.00',maximum_credits:'1000.00',networks:[]})
  vi.mocked(api.creditOrders).mockResolvedValue({items:[],total:0,page:1,page_size:20,pages:1})
  vi.mocked(api.creditTransactions).mockResolvedValue({items:[],total:0,page:1,page_size:20,pages:1})
  vi.mocked(api.documents).mockResolvedValue([])
  vi.mocked(api.library).mockResolvedValue({items: [], total: 0, page: 1, page_size: 20, pages: 1})
  vi.mocked(api.knowledgeBases).mockResolvedValue([])
  vi.mocked(api.knowledgeBaseDocuments).mockResolvedValue([])
  vi.mocked(api.jobs).mockResolvedValue([])
  vi.mocked(api.conversations).mockResolvedValue([])
  vi.mocked(api.conversationFeedback).mockResolvedValue([])
  vi.mocked(api.createConversation).mockResolvedValue({
    id: 20, title: 'NIST phases?', created_at: '2026-10-16T08:00:00Z',
    updated_at: '2026-10-16T08:00:00Z',
  })
  vi.mocked(api.adminFeedback).mockResolvedValue({scope:'tenant',days:30, all_time:{total:0,up:0,down:0}, period:{total:0,up:0,down:0}, positive_rate:null, daily:[], downvote_reasons:[], recent_downvotes:[], disclaimer:'User ratings are not verified correctness.'})
  vi.mocked(api.adminAuditLog).mockResolvedValue({items:[],total:0,page:1,page_size:20,pages:1,actions:[],users:[]})
  vi.mocked(api.adminDashboard).mockResolvedValue({
    users_total: 2, users_active: 2, documents_total: 1, jobs: {}, recent_actions: [],
  })
  vi.mocked(api.adminUsage).mockResolvedValue({
    scope: 'tenant', provider: 'openrouter', cost_unit: 'provider_reported_credits',
    history_since: 'migration', week_starts_utc: '2026-10-12', chart_days: 30,
    overall_credits: '0.0025', week_credits: '0.0005', requests: 2,
    cost_reported_requests: 2, week_requests: 1, week_cost_reported_requests: 1,
    daily: [], users: [],
  })
  vi.mocked(api.adminBudgets).mockResolvedValue({
    month_start_utc:'2026-10-01T00:00:00+00:00',
    tenant:{monthly_limit_credits:null,paused:false,reservation_credits:'0.01',spent_credits:'0',reserved_credits:'0',remaining_credits:null,unknown_cost_requests:0},
    users:[],
  })
  vi.mocked(api.adminUsers).mockResolvedValue([])
  vi.mocked(api.adminInvitations).mockResolvedValue([])
  vi.mocked(api.logout).mockResolvedValue(undefined)
  vi.mocked(api.pdf).mockRejectedValue(new Error("Original PDF unavailable"))
})

// Vitest does not always register RTL's automatic cleanup unless its
// afterEach hook is exposed globally. Remove each rendered tree explicitly.
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('browser session restoration', () => {
  it('lets a reader return to Credits after sign-in and navigate Back', async () => {
    window.history.replaceState({}, '', '/credits')
    render(<App/>)
    await login()
    await screen.findByRole('heading', {name: 'Credits'})
    expect(screen.getByRole('link', {name: 'Credits'})).toHaveAttribute('aria-current', 'page')
    expect(screen.queryByRole('link', {name: 'Dashboard'})).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('link', {name: 'Assistant'}))
    await screen.findByRole('heading', {name: 'Knowledge Assistant'})
    await act(async () => {
      window.history.back()
      await new Promise(resolve => setTimeout(resolve, 20))
    })
    await screen.findByRole('heading', {name: 'Credits'})
    expect(api.credits).toHaveBeenCalledWith('rag_dummy_key', expect.any(AbortSignal))
  })
  it('restores password sign-in after a full app remount and preserves the current URL', async () => {
    const view = render(<App/>)
    fireEvent.click(await screen.findByRole('button',{name:'Email sign in'}))
    fireEvent.change(screen.getByLabelText('Email address'),{target:{value:'user@example.org'}})
    fireEvent.change(screen.getByLabelText('Password'),{target:{value:'synthetic-password'}})
    fireEvent.click(screen.getByRole('button',{name:'Sign in'}))
    await screen.findByRole('heading',{name:'Knowledge Assistant'})
    fireEvent.click(screen.getByRole('link',{name:'Documents'}))
    await screen.findByRole('heading',{name:'Documents'})
    const destination = window.location.pathname + window.location.search
    view.unmount()
    vi.mocked(api.browserSession).mockResolvedValue(account)
    render(<App/>)
    await screen.findByRole('heading',{name:'Documents'})
    expect(window.location.pathname + window.location.search).toBe(destination)
    expect(api.library).toHaveBeenLastCalledWith('',new URLSearchParams('page=1&page_size=20'),expect.any(AbortSignal))
    expect(api.me).not.toHaveBeenCalled()
    expect(storage.setItem).not.toHaveBeenCalled()
    expect(storage.getItem).not.toHaveBeenCalled()
  })

  it('does not render protected content or redirect while the session check is pending', async () => {
    window.history.replaceState({},'', '/documents?q=policy')
    let finish!: (identity:typeof account) => void
    vi.mocked(api.browserSession).mockReturnValue(new Promise(resolve => {finish=resolve}))
    render(<App/>)
    expect(screen.getByText('Restoring your session…')).toBeInTheDocument()
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
    expect(api.library).not.toHaveBeenCalled()
    expect(window.location.pathname).toBe('/documents')
    await act(async () => finish(account))
    await screen.findByRole('heading',{name:'Documents'})
  })

  it('keeps a deep link for an expired session and retries a temporary API failure', async () => {
    window.history.replaceState({},'', '/documents?q=policy')
    vi.mocked(api.browserSession).mockRejectedValueOnce(new ApiError(0,'API unavailable'))
    render(<App/>)
    await screen.findByRole('alert')
    expect(window.location.pathname).toBe('/documents')
    expect(screen.queryByRole('button',{name:'Sign in'})).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button',{name:'Retry session check'}))
    await screen.findByRole('button',{name:'API key'})
    expect(new URLSearchParams(window.location.search).get('returnTo')).toBe('/documents?q=policy')
  })

  it('applies current roles to a restored session on admin routes', async () => {
    window.history.replaceState({},'', '/dashboard')
    vi.mocked(api.browserSession).mockResolvedValue(account)
    render(<App/>)
    await screen.findByRole('heading',{name:'Access denied'})
    expect(api.adminDashboard).not.toHaveBeenCalled()
  })

  it('waits for logout revocation, then stays signed out after refresh', async () => {
    vi.mocked(api.browserSession).mockResolvedValue(account)
    let finish!: () => void
    vi.mocked(api.browserLogout).mockReturnValueOnce(new Promise(resolve => {finish=resolve}))
    const view = render(<App/>)
    fireEvent.click(await screen.findByLabelText('Sign out'))
    expect(screen.queryByRole('button',{name:'Sign in'})).not.toBeInTheDocument()
    expect(api.browserLogout).toHaveBeenCalledOnce()
    await act(async () => finish())
    await screen.findByRole('button',{name:'Sign in'})
    view.unmount()
    vi.mocked(api.browserSession).mockRejectedValue(new ApiError(401,'No session'))
    render(<App/>)
    await screen.findByRole('button',{name:'Sign in'})
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })

  it('reports a failed logout and allows retry instead of claiming it succeeded', async () => {
    vi.mocked(api.browserSession).mockResolvedValue(account)
    vi.mocked(api.browserLogout).mockRejectedValueOnce(new ApiError(0,'API unavailable'))
    render(<App/>)
    fireEvent.click(await screen.findByLabelText('Sign out'))
    await screen.findByText(/Sign out failed/)
    expect(screen.getByRole('navigation')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Sign out'))
    await screen.findByRole('button',{name:'Sign in'})
  })

  it('clears protected UI and preserves destination after revocation during use', async () => {
    window.history.replaceState({},'', '/documents')
    vi.mocked(api.browserSession).mockResolvedValue(account)
    vi.mocked(api.library).mockRejectedValueOnce(new ApiError(401,'Session revoked'))
    render(<App/>)
    await screen.findByRole('button',{name:'Sign in'})
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(new URLSearchParams(window.location.search).get('returnTo')).toBe('/documents')
    expect(screen.getByRole('alert')).toHaveTextContent('expired or access was revoked')
  })

  it('ignores a late restoration result after unmount', async () => {
    let finish!: (identity:typeof account) => void
    vi.mocked(api.browserSession).mockReturnValueOnce(new Promise(resolve => {finish=resolve}))
    const view = render(<App/>)
    view.unmount()
    render(<App/>)
    await screen.findByRole('button',{name:'Sign in'})
    await act(async () => finish(account))
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })
})

describe('URL navigation', () => {
  it('preserves a document deep link and filters through sign-in and refresh', async () => {
    const destination = '/documents?q=policy&status=failed&file_type=pdf&page=2&page_size=50'
    window.history.replaceState({}, '', destination)
    const view = render(<App/>)
    await waitFor(() => expect(window.location.pathname).toBe('/login'))
    expect(new URLSearchParams(window.location.search).get('returnTo')).toBe(destination)
    vi.mocked(api.library).mockResolvedValue({items: [], total: 51, page: 2, page_size: 50, pages: 2})
    await login()
    await screen.findByRole('heading', {name:'Documents'})
    expect(window.location.pathname + window.location.search).toBe(destination)
    expect(screen.getByLabelText('Filter documents')).toHaveValue('policy')
    expect(screen.getByLabelText('Document status')).toHaveValue('failed')
    expect(screen.getByLabelText('File type')).toHaveValue('pdf')
    expect(api.library).toHaveBeenCalledWith('rag_dummy_key', new URLSearchParams('page=2&page_size=50&q=policy&status=failed&file_type=pdf'), expect.any(AbortSignal))
    view.unmount()
    render(<App/>)
    await screen.findByRole('button', {name:'API key'})
    expect(new URLSearchParams(window.location.search).get('returnTo')).toBe(destination)
    expect(storage.setItem).not.toHaveBeenCalled()
  })

  it('supports real links, Back/Forward, active highlighting and mobile closure', async () => {
    render(<App/>); await login()
    expect(window.location.pathname).toBe('/assistant')
    fireEvent.click(screen.getByLabelText('Open navigation'))
    expect(screen.getByLabelText('Close navigation')).toBeInTheDocument()
    const link = screen.getByRole('link', {name:'Documents'})
    expect(link).toHaveAttribute('href', '/documents')
    fireEvent.click(link)
    await screen.findByRole('heading', {name:'Documents'})
    expect(link).toHaveAttribute('aria-current', 'page')
    expect(screen.queryByLabelText('Close navigation')).not.toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Open navigation'))
    fireEvent.click(link)
    expect(screen.queryByLabelText('Close navigation')).not.toBeInTheDocument()
    act(() => window.history.back())
    await waitFor(() => expect(window.location.pathname).toBe('/assistant'))
    await screen.findByRole('heading', {name:'Knowledge Assistant'})
    act(() => window.history.forward())
    await screen.findByRole('heading', {name:'Documents'})
  })

  it.each(['/dashboard', '/users', '/audit-log'])('guards direct non-admin navigation to %s', async path => {
    window.history.replaceState({}, '', path)
    render(<App/>); await login()
    await screen.findByRole('heading', {name:'Access denied'})
    expect(screen.queryByRole('link', {name:'Dashboard'})).not.toBeInTheDocument()
    expect(api.adminDashboard).not.toHaveBeenCalled()
    expect(api.adminUsers).not.toHaveBeenCalled()
    expect(api.adminAuditLog).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('link', {name:'Assistant'}))
    act(() => navigate('/users'))
    expect(screen.getByRole('heading', {name:'Access denied'})).toBeInTheDocument()
  })

  it('restores an admin audit-log deep link through sign-in and supports browser history',async () => {
    window.history.replaceState({},'','/audit-log?action=search')
    vi.mocked(api.me).mockResolvedValue({...account,role:'admin'})
    render(<App/>);await login()
    await screen.findByRole('heading',{name:'Audit Log'})
    expect(screen.getByRole('link',{name:'Audit Log'})).toHaveAttribute('aria-current','page')
    expect(new URLSearchParams(window.location.search).get('action')).toBe('search')
    fireEvent.click(screen.getByRole('link',{name:'Documents'}))
    await screen.findByRole('heading',{name:'Documents'})
    act(() => window.history.back())
    await screen.findByRole('heading',{name:'Audit Log'})
  })

  it.each(['https://outside.example/documents', '//outside.example/users', '/documents-evil', '/login', '/documents/11'])('rejects unsafe return destination %s', async destination => {
    window.history.replaceState({}, '', `/login?${new URLSearchParams({returnTo:destination})}`)
    render(<App/>); await login()
    expect(window.location.pathname).toBe('/assistant')
  })

  it('shows unknown routes without granting access or redirecting externally', async () => {
    window.history.replaceState({}, '', '/missing')
    render(<App/>)
    expect(await screen.findByRole('heading', {name:'Page not found'})).toBeInTheDocument()
    fireEvent.click(screen.getByRole('link', {name:'Sign in'})); await login()
    act(() => navigate('/another-missing'))
    expect(await screen.findByRole('heading', {name:'Page not found'})).toBeInTheDocument()
  })
})

describe('Milestone 8 UI', () => {
  it('supports email/password sign-in without saving session in storage', async () => {
    vi.mocked(api.browserLogin).mockResolvedValue(account)
    render(<App />)
    fireEvent.click(await screen.findByRole('button', {name:'Email sign in'}))
    fireEvent.change(screen.getByLabelText('Email address'), {target:{value:'person@example.org'}})
    fireEvent.change(screen.getByLabelText('Password'), {target:{value:'test-only-password-123'}})
    fireEvent.click(screen.getByRole('button', {name:'Sign in'}))
    await screen.findByRole('heading', {name:'Knowledge Assistant'})
    expect(api.browserLogin).toHaveBeenCalledWith('person@example.org','test-only-password-123')
    expect(api.me).not.toHaveBeenCalled()
    expect(storage.setItem).not.toHaveBeenCalled()
  })

  it('creates an account with an invitation code', async () => {
    vi.mocked(api.browserRegister).mockResolvedValue(account)
    render(<App />)
    fireEvent.click(await screen.findByRole('button', {name:'Sign up'}))
    fireEvent.change(screen.getByLabelText('Invitation code'), {target:{value:'invite_abcdefghijklmnopqrstuvwxyz123456789'}})
    fireEvent.change(screen.getByLabelText('Username'), {target:{value:'newuser'}})
    fireEvent.change(screen.getByLabelText('Email address'), {target:{value:'newuser@example.org'}})
    fireEvent.change(screen.getByLabelText('Password'), {target:{value:'test-only-password-123'}})
    fireEvent.change(screen.getByLabelText('Confirm password'), {target:{value:'test-only-password-123'}})
    fireEvent.click(screen.getByRole('button', {name:'Create account'}))
    await screen.findByRole('heading', {name:'Knowledge Assistant'})
    expect(api.browserRegister).toHaveBeenCalledWith(
      'invite_abcdefghijklmnopqrstuvwxyz123456789','newuser@example.org','newuser','test-only-password-123',
    )
  })

  it('shows admin navigation and dashboard only for admins', async () => {
    vi.mocked(api.me).mockResolvedValue({...account,role:'admin'})
    render(<App />)
    await login()
    fireEvent.click(screen.getByRole('link', {name:'Dashboard'}))
    expect(await screen.findByRole('heading',{name:'Admin Dashboard'})).toBeInTheDocument()
    fireEvent.click(screen.getByRole('link', {name:'User Management'}))
    expect(await screen.findByRole('heading',{name:'User Management'})).toBeInTheDocument()
  })

  it('requires sign-in and does not persist key', async () => {
    render(<App />)
    fireEvent.click(await screen.findByRole('button', {name:'API key'}))
    expect(screen.getByLabelText('API key')).toHaveAttribute('type', 'password')
    await login()
    expect(api.me).toHaveBeenCalledWith('rag_dummy_key')
    expect(storage.setItem).not.toHaveBeenCalled()
    expect(storage.getItem).not.toHaveBeenCalled()
    fireEvent.click(screen.getByLabelText('Sign out'))
    fireEvent.click(await screen.findByRole('button', {name:'API key'}))
    expect(screen.getByLabelText('API key')).toBeInTheDocument()
  })

  it('shows cited answer and source page safely', async () => {
    vi.mocked(api.askConversation).mockResolvedValue({
      message_id: 35, question: 'NIST phases?', answer: 'Preparation [1] and recovery.',
      sources: [{source_number:1, document_id:11, title:'incident-response.pdf',
        chunk_index:143, page_number:31, content:'Preparation guidance', similarity:0.72}],
    })
    render(<App />)
    await login()
    fireEvent.change(screen.getByLabelText('Ask a question'), {target: {value: 'NIST phases?'}})
    fireEvent.click(screen.getByLabelText('Send question'))
    await screen.findByText(/Preparation/)
    expect(screen.getByText(/PDF page 31/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', {name:'Jump to source 1'}))
    fireEvent.click(screen.getByRole('button', {name:/incident-response.pdf/i, expanded: false}))
    expect(screen.getByText('Preparation guidance')).toBeInTheDocument()
  })

  it('hides upload and delete actions for readers', async () => {
    vi.mocked(api.library).mockResolvedValue({items:[{
      kind:'document', id:'11', title:'incident-response.pdf', owner_user_id:1, created_at:'2026-10-15T00:00:00Z',
      status:'indexed', can_manage:false, assigned_users:null, error:null,
    }], total:1, page:1, page_size:20, pages:1})
    render(<App />)
    await login()
    fireEvent.click(screen.getByRole('link', {name:'Documents'}))
    await screen.findByText('incident-response.pdf')
    expect(screen.queryByText('Upload documents')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Delete incident-response.pdf')).not.toBeInTheDocument()
  })

  it('renders upload control for editors', async () => {
    vi.mocked(api.me).mockResolvedValue({...account, role:'editor'})
    render(<App />)
    await login()
    fireEvent.click(screen.getByRole('link', {name:'Documents'}))
    await waitFor(() => expect(screen.getByText('Upload documents')).toBeInTheDocument())
    expect(screen.getByLabelText('Select documents to upload')).toBeInTheDocument()
  })

  it('shows background job status to an editor', async () => {
    vi.mocked(api.me).mockResolvedValue({...account, role:'editor'})
    vi.mocked(api.library).mockResolvedValue({items:[{
      kind:'upload', id:'11111111-1111-4111-8111-111111111111', title:'guide.pdf', owner_user_id:2,
      status:'processing', created_at:'2026-10-15T00:00:00Z', error:null, can_manage:true, assigned_users:null,
    }], total:1, page:1, page_size:20, pages:1})
    render(<App />)
    await login()
    fireEvent.click(screen.getByRole('link', {name:'Documents'}))
    expect(await screen.findByLabelText('guide.pdf: processing')).toBeInTheDocument()
  })

  it('preserves chat when navigating to Documents and back' , async () => {
    vi.mocked(api.askConversation).mockResolvedValue({ message_id: 35, question: 'NIST phases?', answer: 'Preparation [1].', sources: [] })
    render(<App />)
    await login()
    fireEvent.change(screen.getByLabelText('Ask a question'), { target: { value: 'NIST phases?' } })
    fireEvent.click(screen.getByLabelText('Send question'))
    // MarkdownAnswer renders block elements and source buttons.
    // Assert the combined rendered answer, not one text node.
    const answerMatches = (_: string, element: Element | null) =>
      element?.tagName === 'DIV' &&
      element.classList.contains('rag-markdown') &&
      element.textContent?.trim() === 'Preparation [1].'
    await screen.findByText(answerMatches)
    fireEvent.click(screen.getByRole('link', {name:'Documents'}))
    fireEvent.click(screen.getByRole('link', {name:'Assistant'}))
    expect(screen.getByText(answerMatches)).toBeInTheDocument()
  })

})
// Conversation history UI regression tests use existing mocked API methods.
describe('M10.3 saved chats', () => {
  it('lists and reopens chats with original citations', async () => {
    vi.mocked(api.conversations).mockResolvedValue([{
      id: 7, title: 'Existing chat', created_at: '2026-10-16T00:00:00Z',
      updated_at: '2026-10-16T00:00:00Z',
    }])
    vi.mocked(api.conversation).mockResolvedValue({
      id: 7, title: 'Existing chat', created_at: '2026-10-16T00:00:00Z',
      updated_at: '2026-10-16T00:00:00Z',
      messages: [{
        id: 8, question: 'What is MFA?', answer: 'Use multi-factor authentication.',
        sources: [], redacted: false, created_at: '2026-10-16T00:00:00Z',
      }],
    })
    render(<App/>)
    await login()
    fireEvent.click(await screen.findByRole('button', { name: 'Open conversation Existing chat' }))
    expect(await screen.findByText('Use multi-factor authentication.')).toBeInTheDocument()
    expect(api.conversation).toHaveBeenCalledWith('rag_dummy_key', 7)
  })

  it('creates and selects a saved chat immediately when New chat is clicked', async () => {
    vi.mocked(api.createConversation).mockResolvedValue({
      id: 42, title: 'New chat', created_at: '2026-10-16T08:00:00Z',
      updated_at: '2026-10-16T08:00:00Z',
    })
    render(<App/>)
    await login()
    const savedSidebar = screen.getByRole('complementary', {name: 'Saved conversations'})
    fireEvent.click(within(savedSidebar).getByRole('button', {name: 'New chat'}))
    await waitFor(() => expect(api.createConversation).toHaveBeenCalledWith('rag_dummy_key', 'New chat'))
    expect(await within(savedSidebar).findByRole('button', {name: 'Open conversation New chat'})).toBeInTheDocument()
    expect(screen.getByRole('heading', {name: 'What would you like to know?'})).toBeInTheDocument()
  })

  it('keeps the previous conversation when creating a new chat fails', async () => {
    vi.mocked(api.conversations).mockResolvedValue([{
      id: 7, title: 'Existing chat', created_at: '2026-10-16T00:00:00Z',
      updated_at: '2026-10-16T00:00:00Z',
    }])
    vi.mocked(api.conversation).mockResolvedValue({
      id: 7, title: 'Existing chat', created_at: '2026-10-16T00:00:00Z',
      updated_at: '2026-10-16T00:00:00Z', messages: [{
        id: 8, question: 'What is MFA?', answer: 'Use multi-factor authentication.',
        sources: [], redacted: false, created_at: '2026-10-16T00:00:00Z',
      }],
    })
    vi.mocked(api.createConversation).mockRejectedValue(new Error('Cannot create chat'))
    render(<App/>)
    await login()
    const savedSidebar = screen.getByRole('complementary', {name: 'Saved conversations'})
    fireEvent.click(await within(savedSidebar).findByRole('button', {name: 'Open conversation Existing chat'}))
    await screen.findByText('Use multi-factor authentication.')
    fireEvent.click(within(savedSidebar).getByRole('button', {name: 'New chat'}))
    expect(await screen.findByRole('alert')).toHaveTextContent('Cannot create chat')
    expect(screen.getByText('Use multi-factor authentication.')).toBeInTheDocument()
  })

  it('renames a new chat after its first successful answer', async () => {
    vi.mocked(api.createConversation).mockResolvedValue({
      id: 42, title: 'New chat', created_at: '2026-10-16T08:00:00Z',
      updated_at: '2026-10-16T08:00:00Z',
    })
    vi.mocked(api.askConversation).mockResolvedValue({
      message_id: 51, question: 'NIST phases?', answer: 'Preparation and recovery.', sources: [],
    })
    vi.mocked(api.renameConversation).mockResolvedValue({
      id: 42, title: 'NIST phases?', created_at: '2026-10-16T08:00:00Z',
      updated_at: '2026-10-16T08:01:00Z',
    })
    render(<App/>)
    await login()
    const savedSidebar = screen.getByRole('complementary', {name: 'Saved conversations'})
    fireEvent.click(within(savedSidebar).getByRole('button', {name: 'New chat'}))
    await within(savedSidebar).findByRole('button', {name: 'Open conversation New chat'})
    fireEvent.change(screen.getByLabelText('Ask a question'), {target:{value:'NIST phases?'}})
    fireEvent.click(screen.getByLabelText('Send question'))
    await waitFor(() => expect(api.askConversation).toHaveBeenCalledWith('rag_dummy_key', 42, 'NIST phases?', 5, null))
    await waitFor(() => expect(api.renameConversation).toHaveBeenCalledWith('rag_dummy_key', 42, 'NIST phases?'))
    expect(await within(savedSidebar).findByRole('button', {name: 'Open conversation NIST phases?'})).toBeInTheDocument()
  })

  it('creates a persistent conversation before calling OpenRouter', async () => {
    vi.mocked(api.askConversation).mockResolvedValue({
      message_id: 35, question: 'NIST phases?', answer: 'Four phases.', sources: [],
    })
    render(<App/>)
    await login()
    fireEvent.change(screen.getByLabelText('Ask a question'), {target:{value:'NIST phases?'}})
    fireEvent.click(screen.getByLabelText('Send question'))
    await waitFor(() => expect(api.askConversation).toHaveBeenCalledWith('rag_dummy_key', 20, 'NIST phases?', 5, null))
    expect(api.ask).not.toHaveBeenCalled()
    expect(await screen.findByText('Four phases.')).toBeInTheDocument()
  })
})


describe('Milestone 10.4 knowledge-base selection', () => {
  it('passes selected knowledge base to the saved-chat ask API', async () => {
    vi.mocked(api.knowledgeBases).mockResolvedValue([{
      id: 7, name: 'Security Policies', description: '', created_by: 1,
      created_at: '2026-10-16T08:00:00Z', document_count: 1, can_manage: false,
    }])
    vi.mocked(api.askConversation).mockResolvedValue({
      message_id: 44, question: 'What is incident response?',
      answer: 'The answer', sources: [],
    })
    render(<App />)
    await login()
    await screen.findByRole('option', {name: 'Security Policies'})
    fireEvent.change(screen.getByLabelText('Knowledge base'), {target: {value: '7'}})
    fireEvent.change(screen.getByLabelText('Ask a question'), {target: {value: 'What is incident response?'}})
    fireEvent.click(screen.getByRole('button', {name: 'Send question'}))
    await waitFor(() => expect(api.askConversation).toHaveBeenCalledWith(
      'rag_dummy_key', 20, 'What is incident response?', 5, 7,
    ))
  })
})


describe('Milestone 10.5 feedback controls', () => {
  it('lets the conversation owner rate a saved answer', async () => {
    vi.mocked(api.conversations).mockResolvedValue([{
      id: 7, title: 'Security', created_at: '2026-10-16T00:00:00Z', updated_at: '2026-10-16T00:00:00Z',
    }])
    vi.mocked(api.conversation).mockResolvedValue({
      id: 7, title: 'Security', created_at: '2026-10-16T00:00:00Z', updated_at: '2026-10-16T00:00:00Z',
      messages: [{id: 28, question:'What is NIST?',answer:'Preparation.',sources:[], redacted:false,created_at:'2026-10-16T00:00:00Z'}],
    })
    vi.mocked(api.setAnswerFeedback).mockResolvedValue({message_id:28,rating:'up',reason:null,updated_at:'2026-10-16T00:00:00Z'})
    render(<App />)
    await login()
    fireEvent.click(await screen.findByRole('button',{name:'Open conversation Security'}))
    const helpful = await screen.findByRole('button',{name:'Helpful answer 28'})
    fireEvent.click(helpful)
    await waitFor(()=>expect(api.setAnswerFeedback).toHaveBeenCalledWith('rag_dummy_key',7,28,'up',null))
    expect(helpful).toHaveAttribute('aria-pressed','true')
  })
  it('shows the admin quality section only to admins', async () => {
    vi.mocked(api.me).mockResolvedValue({...account,role:'admin'})
    render(<App />)
    await login()
    fireEvent.click(screen.getByRole('link', {name:'Dashboard'}))
    expect(await screen.findByText('Answer Feedback & Quality Signals')).toBeInTheDocument()
    expect(api.adminFeedback).toHaveBeenCalled()
  })
})


describe('Milestone 10.5 saved feedback state', () => {
  it('restores saved feedback when reopening a conversation', async () => {
    vi.mocked(api.conversations).mockResolvedValue([{
      id:9,title:'VPN',created_at:'2026-10-16T00:00:00Z',updated_at:'2026-10-16T00:00:00Z',
    }])
    vi.mocked(api.conversation).mockResolvedValue({
      id:9,title:'VPN',created_at:'2026-10-16T00:00:00Z',updated_at:'2026-10-16T00:00:00Z',
      messages:[{id:44,question:'What is VPN?',answer:'Remote access.',sources:[],redacted:false,created_at:'2026-10-16T00:00:00Z'}],
    })
    vi.mocked(api.conversationFeedback).mockResolvedValue([{
      message_id:44,rating:'down',reason:'incomplete',updated_at:'2026-10-16T00:00:00Z',
    }])
    render(<App />)
    await login()
    fireEvent.click(await screen.findByRole('button',{name:'Open conversation VPN'}))
    expect(await screen.findByRole('button',{name:'Not helpful answer 44'})).toHaveAttribute('aria-pressed','true')
    expect(screen.getByLabelText('Downvote reason for answer 44')).toHaveValue('incomplete')
  })
})
