import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { UsageSection } from './UsageSection'
import { api, ApiError } from './api'
import type { AdminUsage } from './types'

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>()
  return { ...actual, api: {...actual.api, adminUsage: vi.fn()} }
})

afterEach(() => { cleanup(); vi.clearAllMocks() })

const usage: AdminUsage = {
  scope: 'tenant', provider: 'openrouter', cost_unit: 'provider_reported_credits',
  history_since: 'migration', week_starts_utc: '2026-10-12', chart_days: 30,
  overall_credits: '0.0012000000', week_credits: '0.0007000000',
  requests: 3, cost_reported_requests: 2, week_requests: 2, week_cost_reported_requests: 2,
  users: [
    {user_id:1, username:'admin', email:'admin@example.com', is_active:true,
      overall_credits:'0.001', week_credits:'0.0005', requests:2, cost_reported_requests:1,
      week_requests:1, week_cost_reported_requests:1},
    {user_id:2, username:'analyst', email:null, is_active:true,
      overall_credits:'0.0002', week_credits:'0.0002', requests:1, cost_reported_requests:1,
      week_requests:1, week_cost_reported_requests:1},
  ],
  daily: [{date:'2026-10-16', credits:'0.0007', requests:2, cost_reported_requests:2}],
}

describe('OpenRouter admin usage dashboard', () => {
  it('shows overall credits, weekly credits, usage per user, and coverage', async () => {
    vi.mocked(api.adminUsage).mockResolvedValue(usage)
    render(<UsageSection apiKey="secret" onUnauthorized={vi.fn()} />)
    await screen.findByText('Overall OpenRouter usage')
    expect(screen.getByText('This week', {selector: 'p'})).toBeInTheDocument()
    expect(screen.getByText('admin@example.com')).toBeInTheDocument()
    expect(screen.getByText('analyst')).toBeInTheDocument()
    expect(screen.getByText(/Cost coverage: 2 of 3/)).toBeInTheDocument()
    expect(screen.getByRole('img', { name:'Daily OpenRouter usage credits graph' })).toBeInTheDocument()
    expect(api.adminUsage).toHaveBeenCalledWith('secret', 30)
  })

  it('requests seven-day chart data on selection', async () => {
    vi.mocked(api.adminUsage).mockResolvedValue(usage)
    render(<UsageSection apiKey="secret" onUnauthorized={vi.fn()} />)
    await screen.findByRole('img', { name: 'Daily OpenRouter usage credits graph' })
    fireEvent.click(screen.getByRole('button', {name:'7 days'}))
    await waitFor(() => expect(api.adminUsage).toHaveBeenCalledWith('secret',7))
  })

  it('clears the previous period and ignores a late response from an older period', async () => {
    let finishSeven!: (value: AdminUsage) => void
    vi.mocked(api.adminUsage).mockResolvedValue(usage)
    render(<UsageSection apiKey="secret" onUnauthorized={vi.fn()}/>)
    await screen.findByText('analyst')
    vi.mocked(api.adminUsage).mockReturnValueOnce(new Promise(resolve => { finishSeven = resolve }))
    fireEvent.click(screen.getByRole('button', {name: '7 days'}))
    expect(screen.queryByText('analyst')).not.toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.getByText('Loading usage…')).toBeInTheDocument()
    vi.mocked(api.adminUsage).mockResolvedValueOnce({...usage, users: []})
    fireEvent.click(screen.getByRole('button', {name: '30 days'}))
    await screen.findByRole('img')
    await act(async () => { finishSeven({...usage, chart_days: 7}) })
    expect(screen.getByRole('button', {name: '30 days'})).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByText('analyst')).not.toBeInTheDocument()
  })

  it('keeps data visible on a failed refresh and prevents duplicate clicks', async () => {
    let fail!: (error: Error) => void
    vi.mocked(api.adminUsage).mockResolvedValue(usage)
    render(<UsageSection apiKey="secret" onUnauthorized={vi.fn()}/>)
    await screen.findByText('analyst')
    vi.mocked(api.adminUsage).mockReturnValueOnce(new Promise((_, reject) => { fail = reject }))
    const refresh = screen.getByRole('button', {name: 'Refresh usage'})
    fireEvent.click(refresh)
    fireEvent.click(refresh)
    expect(refresh).toBeDisabled()
    expect(screen.getByText('Refreshing usage…')).toBeInTheDocument()
    expect(screen.getByText('analyst')).toBeInTheDocument()
    expect(api.adminUsage).toHaveBeenCalledTimes(2)
    await act(async () => { fail(new Error('Offline')) })
    expect(screen.getByRole('alert')).toHaveTextContent(/Previously loaded usage may be out of date/)
    expect(refresh).toBeEnabled()
  })

  it('does not show the prior tenant or sign out a new session on an obsolete 401', async () => {
    let fail!: (error: Error) => void
    const unauthorized = vi.fn()
    vi.mocked(api.adminUsage).mockResolvedValue(usage)
    const { rerender } = render(<UsageSection apiKey="first" onUnauthorized={unauthorized}/>)
    await screen.findByText('analyst')
    vi.mocked(api.adminUsage).mockReturnValueOnce(new Promise((_, reject) => { fail = reject }))
    fireEvent.click(screen.getByRole('button', {name: 'Refresh usage'}))
    vi.mocked(api.adminUsage).mockResolvedValueOnce({...usage, users: []})
    rerender(<UsageSection apiKey="second" onUnauthorized={unauthorized}/>)
    expect(screen.queryByText('analyst')).not.toBeInTheDocument()
    await screen.findByRole('img')
    await act(async () => { fail(new ApiError(401, 'Old session expired')) })
    expect(unauthorized).not.toHaveBeenCalled()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
