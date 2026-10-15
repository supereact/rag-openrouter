import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import PdfViewer from './PdfViewer'
import { api, ApiError } from './api'

vi.mock('./api', async (original) => {
  const actual = await original<typeof import('./api')>()
  return { ...actual, api: { ...actual.api, pdf: vi.fn() } }
})

const createDescriptor = Object.getOwnPropertyDescriptor(URL, 'createObjectURL')
const revokeDescriptor = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL')
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  if (createDescriptor) Object.defineProperty(URL, 'createObjectURL', createDescriptor)
  else delete (URL as unknown as {createObjectURL?: unknown}).createObjectURL
  if (revokeDescriptor) Object.defineProperty(URL, 'revokeObjectURL', revokeDescriptor)
  else delete (URL as unknown as {revokeObjectURL?: unknown}).revokeObjectURL
})

describe('authorized original PDF viewer', () => {
  it('uses temporary object URL at cited page and revokes it on close', async () => {
    vi.mocked(api.pdf).mockResolvedValue(new Blob(['%PDF-1.4\n...'], { type: 'application/pdf' }))
    const create = vi.fn().mockReturnValue('blob:test-original')
    const revoke = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: create })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revoke })
    const close = vi.fn()
    const { unmount } = render(<PdfViewer apiKey="secret" documentId={11} title="guide.pdf"
      page={31} onClose={close} onUnauthorized={vi.fn()}/>)
    const iframe = await screen.findByTitle('Original PDF: guide.pdf')
    expect(iframe).toHaveAttribute('src', 'blob:test-original#page=31')
    expect(api.pdf).toHaveBeenCalledWith('secret', 11)
    expect(create).toHaveBeenCalledOnce()
    fireEvent.click(screen.getByRole('button', { name: 'Close PDF viewer' }))
    expect(close).toHaveBeenCalledOnce()
    unmount()
    expect(revoke).toHaveBeenCalledWith('blob:test-original')
  })

  it('shows missing original file as an error', async () => {
    vi.mocked(api.pdf).mockRejectedValue(new ApiError(404, 'Original PDF unavailable or not authorized'))
    render(<PdfViewer apiKey="secret" documentId={11} title="old.pdf"
      page={1} onClose={vi.fn()} onUnauthorized={vi.fn()}/>)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Original PDF unavailable'))
  })
})
