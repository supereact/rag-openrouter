import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BudgetSection } from './BudgetSection'
import { api } from './api'
import type { AdminBudgets } from './types'

vi.mock('./api', async (importOriginal) => {
  const original = await importOriginal<typeof import('./api')>()
  return { ...original, api: {...original.api, adminBudgets:vi.fn(), setTenantBudget:vi.fn(), setUserBudget:vi.fn()} }
})

afterEach(() => { cleanup(); vi.clearAllMocks() })

const example: AdminBudgets = {
  month_start_utc:'2026-10-01T00:00:00Z',
  tenant:{monthly_limit_credits:'0.1',paused:false,reservation_credits:'0.01',
    spent_credits:'0.08',reserved_credits:'0.005',remaining_credits:'0.015',unknown_cost_requests:1},
  users:[{user_id:2,username:'analyst',email:'analyst@example.org',
    monthly_limit_credits:'0.04',paused:false,spent_credits:'0.02',reserved_credits:'0.001',
    remaining_credits:'0.019',unknown_cost_requests:0}],
}

describe('Admin credit budget controls', () => {
  it('shows budget and warning for usage over 80 percent', async () => {
    vi.mocked(api.adminBudgets).mockResolvedValue(example)
    render(<BudgetSection apiKey="key" onUnauthorized={vi.fn()}/>)
    await screen.findByText('Monthly credit budgets')
    expect(await screen.findByText('Spent this month')).toBeInTheDocument()
    expect(screen.getByText(/Tenant has used or reserved at least 80%/)).toBeInTheDocument()
    expect(screen.getByText('analyst')).toBeInTheDocument()
  })

  it('saves tenant and user limits through authorized API', async () => {
    vi.mocked(api.adminBudgets).mockResolvedValue(example)
    vi.mocked(api.setTenantBudget).mockResolvedValue(example)
    vi.mocked(api.setUserBudget).mockResolvedValue(example)
    render(<BudgetSection apiKey="secret" onUnauthorized={vi.fn()}/>)
    await screen.findByDisplayValue('0.1')
    fireEvent.change(screen.getByLabelText('Tenant monthly limit'), {target:{value:'0.2'}})
    fireEvent.click(screen.getByRole('button', {name:'Save tenant budget'}))
    await waitFor(()=>expect(api.setTenantBudget).toHaveBeenCalledWith('secret',
      {monthly_limit_credits:'0.2',paused:false,reservation_credits:'0.01'}))
    fireEvent.click(screen.getByRole('button', {name:'Edit'}))
    fireEvent.change(screen.getByLabelText('User monthly limit'),{target:{value:'0.03'}})
    fireEvent.click(screen.getByRole('button', {name:'Save user budget'}))
    await waitFor(()=>expect(api.setUserBudget).toHaveBeenCalledWith('secret',2,
      {monthly_limit_credits:'0.03',paused:false}))
  })
})
