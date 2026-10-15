import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import MarkdownAnswer from './MarkdownAnswer'
import type { SearchHit } from './types'

const source: SearchHit = {
  source_number: 1,
  document_id: 11,
  title: 'incident-response.pdf',
  chunk_index: 146,
  content: 'NIST describes preparation.',
  page_number: 31,
  similarity: 0.72,
}

afterEach(cleanup)

describe('MarkdownAnswer', () => {
  it('renders bold, headings, numbered lists, tables, and inline code', () => {
    render(<MarkdownAnswer entryId={2} sources={[source]} text={
      '## NIST phases\n\n**Preparation** is first.\n\n1. Detect\n2. Recover\n\n| Phase | Detail |\n|---|---|\n| 1 | Prepare |\n\nUse `pgvector`.'
    } />)
    expect(screen.getByRole('heading', { name: 'NIST phases', level: 2 })).toBeInTheDocument()
    expect(screen.getByText('Preparation').tagName).toBe('STRONG')
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByText('pgvector').tagName).toBe('CODE')
  })

  it('preserves citations and jumps to an authorized source', () => {
    const target = document.createElement('div')
    target.id = 'source-3-1'
    target.tabIndex = -1
    // jsdom may expose these DOM methods as read-only; define own test spies.
    Object.defineProperty(target, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    })
    Object.defineProperty(target, 'focus', {
      configurable: true,
      value: vi.fn(),
    })
    document.body.append(target)
    try {
      render(<MarkdownAnswer entryId={3} sources={[source]} text={'**Preparation** [1] and [99].'} />)
      fireEvent.click(screen.getByRole('button', { name: 'Jump to source 1' }))
      expect(target.scrollIntoView).toHaveBeenCalled()
      expect(target.focus).toHaveBeenCalled()
      expect(screen.queryByRole('button', { name: 'Jump to source 99' })).toBeNull()
      // GFM renders the unknown citation as inline text inside a paragraph,
      // not as a standalone element. Verify it stays literal and unlinked.
      expect(screen.getByText('Preparation').closest('p')).toHaveTextContent('and [99].')
    } finally {
      target.remove()
    }
  })

  it('does not interpret untrusted HTML or load remote Markdown images', () => {
    const { container } = render(<MarkdownAnswer entryId={1} sources={[]} text={
      '<script>alert("xss")</script>\n\n![remote image](https://example.com/tracker.png)\n\n[bad link](javascript:alert(1))'
    } />)
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull()
  })

  it('leaves code citations as literal text', () => {
    const { container } = render(<MarkdownAnswer entryId={2} sources={[source]} text={
      '```text\nsource [1]\n```\n\n`[1]`'
    } />)
    expect(container.querySelectorAll('code')).toHaveLength(2)
    expect(screen.queryByRole('button', { name: 'Jump to source 1' })).toBeNull()
  })
})
