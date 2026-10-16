import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { UsageSection } from './UsageSection'
import { api } from './api'
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
    expect(screen.getByText('This week')).toBeInTheDocument()
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
})
