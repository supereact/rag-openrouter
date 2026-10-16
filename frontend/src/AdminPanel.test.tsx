import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DashboardPanel } from './AdminPanel'
import { api, ApiError } from './api'
import type { AdminBudgets, AdminDashboard, AdminFeedback, AdminUsage } from './types'

vi.mock('./api', async importOriginal => {
  const actual = await importOriginal<typeof import('./api')>()
  return { ...actual, api: { ...actual.api,
    adminDashboard: vi.fn(), adminUsage: vi.fn(), adminBudgets: vi.fn(), adminFeedback: vi.fn(),
  } }
})

const overview: AdminDashboard = {
  users_total: 2, users_active: 1, documents_total: 3,
  jobs: {queued: 1, failed: 2}, recent_actions: [],
}
const usage: AdminUsage = {
  scope: 'tenant', provider: 'openrouter', cost_unit: 'provider_reported_credits',
  history_since: 'migration', week_starts_utc: '2026-10-12', chart_days: 30,
  overall_credits: '0.01', week_credits: '0.01', requests: 1, cost_reported_requests: 1,
  week_requests: 1, week_cost_reported_requests: 1, daily: [], users: [],
}
const budgets: AdminBudgets = {
  month_start_utc: '2026-10-01T00:00:00Z',
  tenant: {monthly_limit_credits: null, paused: false, reservation_credits: '0.01',
    spent_credits: '0', reserved_credits: '0', remaining_credits: null, unknown_cost_requests: 0},
  users: [],
}
const feedback: AdminFeedback = {
  scope: 'tenant', days: 30, all_time: {total: 0, up: 0, down: 0},
  period: {total: 0, up: 0, down: 0}, positive_rate: null, daily: [],
  downvote_reasons: [], recent_downvotes: [], disclaimer: 'Subjective ratings',
}

beforeEach(() => {
  vi.mocked(api.adminDashboard).mockReset().mockResolvedValue(overview)
  vi.mocked(api.adminUsage).mockReset().mockResolvedValue(usage)
  vi.mocked(api.adminBudgets).mockReset().mockResolvedValue(budgets)
  vi.mocked(api.adminFeedback).mockReset().mockResolvedValue(feedback)
})
afterEach(cleanup)

describe('independent admin dashboard sections', () => {
  it('starts every section before the overview finishes, and isolates its failure', async () => {
    let reject!: (error: Error) => void
    vi.mocked(api.adminDashboard).mockReturnValue(new Promise((_, no) => { reject = no }))
    render(<DashboardPanel apiKey="session" onUnauthorized={vi.fn()}/>)
    expect(api.adminDashboard).toHaveBeenCalledWith('session')
    expect(api.adminUsage).toHaveBeenCalledWith('session', 30)
    expect(api.adminBudgets).toHaveBeenCalledWith('session')
    expect(api.adminFeedback).toHaveBeenCalledWith('session', 30)
    expect(screen.getByRole('button', {name: 'Refresh overview'})).toBeDisabled()
    await screen.findByText('Overall OpenRouter usage')
    expect(screen.getByLabelText('Tenant monthly limit')).toBeInTheDocument()
    expect(screen.getByText('All-time ratings')).toBeInTheDocument()
    await act(async () => { reject(new Error('Overview unavailable')) })
    expect(screen.getByRole('alert')).toHaveTextContent('Overview unavailable')
    expect(screen.getByRole('button', {name: 'Refresh overview'})).toBeEnabled()
    expect(screen.getByText('Overall OpenRouter usage')).toBeInTheDocument()
  })

  it('refreshes only the chosen section and retries an overview error', async () => {
    vi.mocked(api.adminDashboard).mockRejectedValueOnce(new Error('Overview unavailable'))
    render(<DashboardPanel apiKey="session" onUnauthorized={vi.fn()}/>)
    await screen.findByText('Overview unavailable')
    fireEvent.click(screen.getByRole('button', {name: 'Refresh overview'}))
    await screen.findByText('No recent audit events.')
    expect(api.adminDashboard).toHaveBeenCalledTimes(2)
    expect(api.adminUsage).toHaveBeenCalledTimes(1)
    expect(api.adminBudgets).toHaveBeenCalledTimes(1)
    expect(api.adminFeedback).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', {name: 'Refresh feedback'}))
    await waitFor(() => expect(api.adminFeedback).toHaveBeenCalledTimes(2))
    expect(api.adminDashboard).toHaveBeenCalledTimes(2)
    expect(api.adminUsage).toHaveBeenCalledTimes(1)
    expect(api.adminBudgets).toHaveBeenCalledTimes(1)
  })

  it('keeps overview data visible with a stale warning when refresh fails', async () => {
    render(<DashboardPanel apiKey="session" onUnauthorized={vi.fn()}/>)
    await screen.findByText('No recent audit events.')
    vi.mocked(api.adminDashboard).mockRejectedValueOnce(new Error('Offline'))
    fireEvent.click(screen.getByRole('button', {name: 'Refresh overview'}))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Previously loaded overview may be out of date/)
    expect(screen.getByText('No recent audit events.')).toBeInTheDocument()
    expect(screen.getByText('Documents')).toBeInTheDocument()
  })

  it('removes overview data on 403 without blocking the independent sections', async () => {
    const unauthorized = vi.fn()
    render(<DashboardPanel apiKey="session" onUnauthorized={unauthorized}/>)
    await screen.findByText('No recent audit events.')
    vi.mocked(api.adminDashboard).mockRejectedValueOnce(new ApiError(403, 'Forbidden'))
    fireEvent.click(screen.getByRole('button', {name: 'Refresh overview'}))
    expect(await screen.findByRole('alert')).toHaveTextContent('Access denied')
    expect(screen.queryByText('No recent audit events.')).not.toBeInTheDocument()
    expect(screen.queryByText('Documents')).not.toBeInTheDocument()
    expect(screen.getByText('Overall OpenRouter usage')).toBeInTheDocument()
    expect(unauthorized).not.toHaveBeenCalled()
  })
})
