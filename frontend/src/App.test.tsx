import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import App from './App'
import { api } from './api'

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>()
  return {
    ...actual,
    api: {
      me: vi.fn(), ask: vi.fn(), documents: vi.fn(), upload: vi.fn(),
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
  fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'rag_dummy_key' } })
  fireEvent.click(screen.getByRole('button', { name: /connect to workspace/i }))
  await screen.findByRole('heading', { name: 'Knowledge Assistant' })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('localStorage', storage)
  vi.mocked(api.me).mockResolvedValue(account)
  vi.mocked(api.documents).mockResolvedValue([])
  vi.mocked(api.jobs).mockResolvedValue([])
  vi.mocked(api.pdf).mockRejectedValue(new Error("Original PDF unavailable"))
})

// Vitest does not always register RTL's automatic cleanup unless its
// afterEach hook is exposed globally. Remove each rendered tree explicitly.
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Milestone 8 UI', () => {
  it('requires sign-in and does not persist key', async () => {
    render(<App />)
    expect(screen.getByLabelText('API key')).toHaveAttribute('type', 'password')
    await login()
    expect(api.me).toHaveBeenCalledWith('rag_dummy_key')
    expect(storage.setItem).not.toHaveBeenCalled()
    expect(storage.getItem).not.toHaveBeenCalled()
    fireEvent.click(screen.getByLabelText('Sign out'))
    expect(screen.getByLabelText('API key')).toBeInTheDocument()
  })

  it('shows cited answer and source page safely', async () => {
    vi.mocked(api.ask).mockResolvedValue({
      question: 'NIST phases?', answer: 'Preparation [1] and recovery.',
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
    vi.mocked(api.ask).mockResolvedValue({ question: 'NIST phases?', answer: 'Preparation [1].', sources: [] })
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
