import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import FeedbackQualitySection from './FeedbackQualitySection'
import { api, ApiError } from './api'
import type { AdminFeedback } from './types'

vi.mock('./api', async importOriginal => {
  const actual = await importOriginal<typeof import('./api')>()
  return { ...actual, api: {...actual.api, adminFeedback: vi.fn()} }
})
afterEach(() => { cleanup(); vi.clearAllMocks() })

const feedback: AdminFeedback = {
  scope: 'tenant', days: 30, all_time: {total: 2, up: 1, down: 1},
  period: {total: 2, up: 1, down: 1}, positive_rate: 0.5,
  daily: [{date: '2026-10-16', up: 1, down: 1}],
  downvote_reasons: [{reason: 'incorrect', count: 1}],
  recent_downvotes: [{username: 'reviewer', reason: 'incorrect', created_at: '2026-10-16T00:00:00Z'}],
  disclaimer: 'User sentiment',
}

describe('feedback report loading', () => {
  it('clears old-period feedback and ignores a late report after switching back', async () => {
    let finish!: (value: AdminFeedback) => void
    vi.mocked(api.adminFeedback).mockResolvedValue(feedback)
    render(<FeedbackQualitySection apiKey="session" onUnauthorized={vi.fn()}/>)
    await screen.findByText('50.0%')
    vi.mocked(api.adminFeedback).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    fireEvent.change(screen.getByLabelText('Feedback reporting period'), {target: {value: '7'}})
    expect(screen.queryByText('50.0%')).not.toBeInTheDocument()
    expect(screen.queryByText('reviewer · incorrect')).not.toBeInTheDocument()
    expect(screen.getByRole('button', {name: 'Refresh feedback'})).toBeDisabled()
    vi.mocked(api.adminFeedback).mockResolvedValueOnce({...feedback, positive_rate: 1})
    fireEvent.change(screen.getByLabelText('Feedback reporting period'), {target: {value: '30'}})
    await screen.findByText('100.0%')
    await act(async () => { finish({...feedback, days: 7}) })
    expect(screen.getByText('100.0%')).toBeInTheDocument()
    expect(screen.queryByText('50.0%')).not.toBeInTheDocument()
  })

  it('marks retained feedback stale after failure and removes it after access denial', async () => {
    vi.mocked(api.adminFeedback).mockResolvedValue(feedback)
    const unauthorized = vi.fn()
    render(<FeedbackQualitySection apiKey="session" onUnauthorized={unauthorized}/>)
    await screen.findByText('50.0%')
    vi.mocked(api.adminFeedback).mockRejectedValueOnce(new Error('Offline'))
    fireEvent.click(screen.getByRole('button', {name: 'Refresh feedback'}))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Previously loaded feedback may be out of date/)
    expect(screen.getByText('50.0%')).toBeInTheDocument()
    vi.mocked(api.adminFeedback).mockRejectedValueOnce(new ApiError(403, 'Forbidden'))
    fireEvent.click(screen.getByRole('button', {name: 'Refresh feedback'}))
    await screen.findByText(/Access denied/)
    expect(screen.queryByText('50.0%')).not.toBeInTheDocument()
    expect(screen.queryByText('reviewer · incorrect')).not.toBeInTheDocument()
    expect(unauthorized).not.toHaveBeenCalled()
  })
})
