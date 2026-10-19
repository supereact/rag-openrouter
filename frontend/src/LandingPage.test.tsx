import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import LandingPage from './LandingPage'

// JSDOM cannot evaluate responsive media queries. Test behavior here; real
// desktop/mobile styling needs a browser, rather than injected CSS in JSDOM.
vi.mock('./landing.css', () => ({}))

const motionState = vi.hoisted(() => ({ reduced: false, inView: true }))
vi.mock('motion/react', async importOriginal => ({
  ...await importOriginal<typeof import('motion/react')>(),
  useReducedMotion: () => motionState.reduced,
  useInView: () => motionState.inView,
}))

beforeEach(() => {
  vi.mocked(Element.prototype.scrollIntoView).mockClear()
  motionState.reduced = false
  motionState.inView = true
  window.history.replaceState({}, '', '/')
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('Precision landing page', () => {
  it('resolves a direct section link after the lazy page mounts', () => {
    window.history.replaceState({}, '', '/#security')
    render(<LandingPage/>)
    const scroll = vi.mocked(Element.prototype.scrollIntoView)
    expect(scroll).toHaveBeenCalledWith({ behavior: 'instant', block: 'start' })
    expect(scroll.mock.instances[0]).toBe(document.getElementById('security'))
  })

  it('ignores unknown fragments', () => {
    window.history.replaceState({}, '', '/#unknown-section')
    render(<LandingPage/>)
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled()
  })

  it('provides the complete page, real destinations and a skip link', () => {
    render(<LandingPage/>)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Your company’s knowledge.Answers you can verify.')
    expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveAttribute('href', '#landing-main')
    const main = screen.getByRole('main')
    expect(main).toHaveAttribute('id', 'landing-main')
    for (const link of within(screen.getByRole('navigation', { name: 'Website navigation' })).getAllByRole('link')) {
      expect(document.querySelector(link.getAttribute('href')!)).toBeInTheDocument()
    }
    expect(screen.getByRole('heading', { name: 'From document to dialogue.' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Your knowledge\.\s*Your boundaries\./ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Good questions\.\s*Clear answers\./ })).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /Get started/ })).toHaveLength(3)
    screen.getAllByRole('link', { name: /Get started/ }).forEach(link => expect(link).toHaveAttribute('href', '/login?mode=register'))
    expect(screen.getByText('Fictional content · no live documents')).toBeInTheDocument()
  })

  it('switches example questions and reveals their matching source without a request', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    render(<LandingPage/>)
    expect(screen.getByText('How do we welcome a new teammate?')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Operations', pressed: false }))
    expect(screen.getByRole('button', { name: 'Operations', pressed: true })).toBeInTheDocument()
    expect(screen.getByText('What goes into a project handover?')).toBeInTheDocument()
    const source = screen.getByRole('region', { name: 'Example PDF source' })
    expect(source).toHaveTextContent('A thoughtful handover')
    expect(source).toHaveTextContent('7 / 24')
    fireEvent.click(screen.getByRole('button', { name: /Hide example source/ }))
    expect(source).not.toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: /View example source/ }))
    expect(source).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Onboarding' }))
    expect(source).toHaveTextContent('A great first week')
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('provides accessible FAQ expansion, keyboard focus and honest provider details', () => {
    render(<LandingPage/>)
    const question = screen.getByRole('button', { name: 'Where is document data processed?' })
    expect(question).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(question)
    expect(question).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('region', { name: 'Where is document data processed?' })).toHaveTextContent('Relevant document excerpts and question context are sent to the configured generation provider')
    question.focus()
    fireEvent.keyDown(question, { key: 'ArrowDown' })
    expect(screen.getByRole('button', { name: 'How do I get started?' })).toHaveFocus()
    fireEvent.click(screen.getByRole('button', { name: 'How do I get started?' }))
    expect(question).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByRole('region', { name: 'How do I get started?' })).toHaveTextContent('invitation code')
  })

  it('opens a labeled mobile menu, closes on a section link, and returns focus', async () => {
    render(<LandingPage/>)
    const trigger = screen.getByRole('button', { name: 'Open menu' })
    trigger.focus()
    fireEvent.click(trigger)
    const dialog = screen.getByRole('dialog', { name: 'Explore KnowledgeBase' })
    expect(dialog).toHaveAttribute('aria-describedby')
    fireEvent.click(within(dialog).getByRole('link', { name: 'Security' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('closes the mobile menu with Escape and follows its Get started link', () => {
    render(<LandingPage/>)
    fireEvent.click(screen.getByRole('button', { name: 'Open menu' }))
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Open menu' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('link', { name: /Get started/ }))
    expect(window.location.pathname + window.location.search).toBe('/login?mode=register')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('links signed-in visitors directly to their workspace', () => {
    render(<LandingPage signedIn/>)
    expect(screen.queryByRole('link', { name: 'Sign in' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Get started/ })).not.toBeInTheDocument()
    screen.getAllByRole('link', { name: /Open workspace/ }).forEach(link => expect(link).toHaveAttribute('href', '/assistant'))
  })

  it('removes decorative motion for reduced-motion preferences', () => {
    motionState.reduced = true
    const { container } = render(<LandingPage/>)
    expect(container.querySelector('.landing-page')).toHaveAttribute('data-reduced-motion', 'true')
    expect(container.querySelector('.landing-beam')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1 })).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Operations' }))
    expect(screen.getByText('What goes into a project handover?')).toBeVisible()
  })

  it('stops the decorative effect outside the viewport and while the tab is hidden', () => {
    motionState.inView = false
    const { container, rerender } = render(<LandingPage/>)
    expect(container.querySelector('.landing-beam')).not.toBeInTheDocument()
    motionState.inView = true
    rerender(<LandingPage/>)
    expect(container.querySelector('.landing-beam')).toBeInTheDocument()
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    expect(container.querySelector('.landing-beam')).not.toBeInTheDocument()
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    expect(container.querySelector('.landing-beam')).toBeInTheDocument()
  })
})
