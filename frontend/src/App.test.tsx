import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import App from './App'
import { api } from './api'

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>()
  return {
    ...actual,
    api: {
      me: vi.fn(), ask: vi.fn(), documents: vi.fn(), upload: vi.fn(),
      conversationFeedback: vi.fn(), setAnswerFeedback: vi.fn(), deleteAnswerFeedback: vi.fn(), adminFeedback: vi.fn(),
      conversations: vi.fn(), conversation: vi.fn(), createConversation: vi.fn(),
      askConversation: vi.fn(), renameConversation: vi.fn(), deleteConversation: vi.fn(),
      loginPassword: vi.fn(), register: vi.fn(), logout: vi.fn(),
      adminDashboard: vi.fn(), adminUsage: vi.fn(), adminBudgets: vi.fn(), adminUsers: vi.fn(), adminInvitations: vi.fn(),
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
  fireEvent.click(screen.getByRole('button', {name:'API key'}))
  fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'rag_dummy_key' } })
  fireEvent.click(screen.getByRole('button', { name: /connect to workspace/i }))
  await screen.findByRole('heading', { name: 'Knowledge Assistant' })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('localStorage', storage)
  vi.mocked(api.me).mockResolvedValue(account)
  vi.mocked(api.documents).mockResolvedValue([])
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

describe('Milestone 8 UI', () => {
  it('supports email/password sign-in without saving session in storage', async () => {
    vi.mocked(api.loginPassword).mockResolvedValue({access_token:'rags_example_session',token_type:'bearer',expires_in:43200})
    render(<App />)
    fireEvent.click(screen.getByRole('button', {name:'Email sign in'}))
    fireEvent.change(screen.getByLabelText('Email address'), {target:{value:'person@example.org'}})
    fireEvent.change(screen.getByLabelText('Password'), {target:{value:'test-only-password-123'}})
    fireEvent.click(screen.getByRole('button', {name:'Sign in'}))
    await screen.findByRole('heading', {name:'Knowledge Assistant'})
    expect(api.loginPassword).toHaveBeenCalledWith('person@example.org','test-only-password-123')
    expect(api.me).toHaveBeenCalledWith('rags_example_session')
    expect(storage.setItem).not.toHaveBeenCalled()
  })

  it('creates an account with an invitation code', async () => {
    vi.mocked(api.register).mockResolvedValue({access_token:'rags_registered_session',token_type:'bearer',expires_in:43200})
    render(<App />)
    fireEvent.click(screen.getByRole('button', {name:'Sign up'}))
    fireEvent.change(screen.getByLabelText('Invitation code'), {target:{value:'invite_abcdefghijklmnopqrstuvwxyz123456789'}})
    fireEvent.change(screen.getByLabelText('Username'), {target:{value:'newuser'}})
    fireEvent.change(screen.getByLabelText('Email address'), {target:{value:'newuser@example.org'}})
    fireEvent.change(screen.getByLabelText('Password'), {target:{value:'test-only-password-123'}})
    fireEvent.change(screen.getByLabelText('Confirm password'), {target:{value:'test-only-password-123'}})
    fireEvent.click(screen.getByRole('button', {name:'Create account'}))
    await screen.findByRole('heading', {name:'Knowledge Assistant'})
    expect(api.register).toHaveBeenCalledWith(
      'invite_abcdefghijklmnopqrstuvwxyz123456789','newuser@example.org','newuser','test-only-password-123',
    )
  })

  it('shows admin navigation and dashboard only for admins', async () => {
    vi.mocked(api.me).mockResolvedValue({...account,role:'admin'})
    render(<App />)
    await login()
    fireEvent.click(screen.getByRole('button',{name:'Dashboard'}))
    expect(await screen.findByRole('heading',{name:'Admin Dashboard'})).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button',{name:'User Management'}))
    expect(await screen.findByRole('heading',{name:'User Management'})).toBeInTheDocument()
  })

  it('requires sign-in and does not persist key', async () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', {name:'API key'}))
    expect(screen.getByLabelText('API key')).toHaveAttribute('type', 'password')
    await login()
    expect(api.me).toHaveBeenCalledWith('rag_dummy_key')
    expect(storage.setItem).not.toHaveBeenCalled()
    expect(storage.getItem).not.toHaveBeenCalled()
    fireEvent.click(screen.getByLabelText('Sign out'))
    fireEvent.click(screen.getByRole('button', {name:'API key'}))
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
    fireEvent.click(screen.getByRole('button', {name:/incident-response.pdf/i}))
    expect(screen.getByText('Preparation guidance')).toBeInTheDocument()
  })

  it('hides upload and delete actions for readers', async () => {
    vi.mocked(api.documents).mockResolvedValue([{
      id:11, title:'incident-response.pdf', owner_user_id:1, created_at:'2026-10-15T00:00:00Z',
    }])
    render(<App />)
    await login()
    fireEvent.click(screen.getByRole('button', {name:'Documents'}))
    await screen.findByText('incident-response.pdf')
    expect(screen.queryByText('Upload document')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Delete incident-response.pdf')).not.toBeInTheDocument()
  })

  it('renders upload control for editors', async () => {
    vi.mocked(api.me).mockResolvedValue({...account, role:'editor'})
    render(<App />)
    await login()
    fireEvent.click(screen.getByRole('button', {name:'Documents'}))
    await waitFor(() => expect(screen.getByText('Upload document')).toBeInTheDocument())
    expect(screen.getByLabelText('Select document to upload')).toBeInTheDocument()
  })

  it('shows background job status to an editor', async () => {
    vi.mocked(api.me).mockResolvedValue({...account, role:'editor'})
    vi.mocked(api.jobs).mockResolvedValue([{
      id: '11111111-1111-4111-8111-111111111111', filename: 'guide.pdf', status: 'processing',
      document_id: null, chunk_count: null, already_exists: null, error: null,
      created_at: '2026-10-15T00:00:00Z', started_at: null, finished_at: null,
    }])
    render(<App />)
    await login()
    fireEvent.click(screen.getByRole('button', { name: 'Documents' }))
    expect(await screen.findByLabelText('Upload guide.pdf: processing')).toBeInTheDocument()
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
    fireEvent.click(screen.getByRole('button', { name: 'Documents' }))
    fireEvent.click(screen.getByRole('button', { name: 'Assistant' }))
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
    fireEvent.click(screen.getByRole('button',{name:'Dashboard'}))
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
