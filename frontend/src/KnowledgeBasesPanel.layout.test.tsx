import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import KnowledgeBasesPanel from './KnowledgeBasesPanel'
import { api } from './api'

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      knowledgeBases: vi.fn(),
      knowledgeBaseDocuments: vi.fn(),
      documents: vi.fn(),
    },
  }
})

beforeEach(() => {
  vi.mocked(api.knowledgeBases).mockResolvedValue([{
    id: 1,
    name: 'Security Base',
    description: '',
    created_by: 1,
    created_at: '2026-10-16T00:00:00Z',
    document_count: 0,
    can_manage: true,
  }])
  vi.mocked(api.knowledgeBaseDocuments).mockResolvedValue([])
  vi.mocked(api.documents).mockResolvedValue([{
    id: 11,
    title: 'A very long document title that can force the native select element wider than its card in narrow layouts.pdf',
    owner_user_id: 1,
    created_at: '2026-10-16T00:00:00Z',
  }])
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('knowledge base card layout', () => {
  it('keeps the document picker constrained even when an option has a long filename', async () => {
    render(<KnowledgeBasesPanel session={{
      key: 'fake-key',
      identity: { user_id: 1, tenant_id: 1, role: 'admin', username: 'admin' },
    }} onUnauthorized={vi.fn()} />)

    const select = await screen.findByLabelText('Document to add')
    expect(select).toHaveClass('min-w-0', 'w-full', 'max-w-full')
    expect(select.closest('form')).toHaveClass('min-w-0', 'grid-cols-1')
    expect(select.closest('section')).toHaveClass('min-w-0')
    expect(screen.getByRole('option', { name: /A very long document title/ })).toBeInTheDocument()
  })
})
