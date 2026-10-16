import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BudgetSection } from './BudgetSection'
import { api, ApiError } from './api'
import type { AdminBudgets } from './types'

vi.mock('./api', async (importOriginal) => {
  const original = await importOriginal<typeof import('./api')>()
  return { ...original, api: {...original.api, adminBudgets:vi.fn(), setTenantBudget:vi.fn(), setUserBudget:vi.fn()} }
})

afterEach(() => { cleanup(); vi.resetAllMocks() })

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

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
    await screen.findByText('User budget saved')
    expect(api.adminBudgets).toHaveBeenCalledTimes(1)
  })

  it('uses the full save response without reloading or erasing another form draft', async () => {
    vi.mocked(api.adminBudgets).mockResolvedValue(example)
    vi.mocked(api.setUserBudget).mockResolvedValue({
      ...example, tenant: {...example.tenant, spent_credits: '0.091'},
      users: [{...example.users[0], monthly_limit_credits: '0.03'}],
    })
    render(<BudgetSection apiKey="session" onUnauthorized={vi.fn()}/>)
    await screen.findByDisplayValue('0.1')
    fireEvent.change(screen.getByLabelText('Tenant monthly limit'), {target: {value: '0.2'}})
    fireEvent.click(screen.getByRole('button', {name: 'Edit'}))
    fireEvent.change(screen.getByLabelText('User monthly limit'), {target: {value: '0.03'}})
    fireEvent.click(screen.getByRole('button', {name: 'Save user budget'}))
    await screen.findByText('User budget saved')
    expect(screen.getByText('0.091')).toBeInTheDocument()
    expect(screen.getByText('0.03 credits')).toBeInTheDocument()
    expect(screen.getByLabelText('Tenant monthly limit')).toHaveValue('0.2')
    expect(api.adminBudgets).toHaveBeenCalledTimes(1)
  })

  it('preserves tenant and user edits while refreshing balances', async () => {
    const read = deferred<AdminBudgets>()
    vi.mocked(api.adminBudgets).mockResolvedValueOnce(example).mockReturnValueOnce(read.promise)
    render(<BudgetSection apiKey="session" onUnauthorized={vi.fn()}/>)
    await screen.findByDisplayValue('0.1')
    fireEvent.change(screen.getByLabelText('Tenant monthly limit'), {target: {value: '0.2'}})
    fireEvent.click(screen.getByRole('button', {name: 'Edit'}))
    fireEvent.change(screen.getByLabelText('User monthly limit'), {target: {value: '0.03'}})
    fireEvent.click(screen.getByRole('button', {name: 'Refresh budgets'}))
    expect(screen.getByText('Refreshing budgets…')).toBeInTheDocument()
    expect(screen.getByRole('button', {name: 'Save tenant budget'})).toBeDisabled()
    expect(screen.getByRole('button', {name: 'Save user budget'})).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Tenant monthly limit'), {target: {value: '0.25'}})
    await act(async () => { read.resolve({...example, tenant: {...example.tenant,
      monthly_limit_credits: '0.3', spent_credits: '0.095'}}) })
    expect(screen.getByText('0.095')).toBeInTheDocument()
    expect(screen.getByLabelText('Tenant monthly limit')).toHaveValue('0.25')
    expect(screen.getByLabelText('User monthly limit')).toHaveValue('0.03')
  })

  it('prevents overlapping refreshes and saves, then keeps the authoritative PUT response', async () => {
    const read = deferred<AdminBudgets>()
    const write = deferred<AdminBudgets>()
    vi.mocked(api.adminBudgets).mockResolvedValueOnce(example).mockReturnValueOnce(read.promise)
    vi.mocked(api.setTenantBudget).mockReturnValue(write.promise)
    render(<BudgetSection apiKey="session" onUnauthorized={vi.fn()}/>)
    await screen.findByDisplayValue('0.1')
    fireEvent.change(screen.getByLabelText('Tenant monthly limit'), {target: {value: '0.2'}})
    const refresh = screen.getByRole('button', {name: 'Refresh budgets'})
    const form = screen.getByLabelText('Tenant monthly limit').closest('form')!
    fireEvent.click(refresh)
    fireEvent.click(refresh)
    fireEvent.submit(form)
    expect(api.adminBudgets).toHaveBeenCalledTimes(2)
    expect(api.setTenantBudget).not.toHaveBeenCalled()
    await act(async () => { read.resolve(example) })
    fireEvent.submit(form)
    fireEvent.submit(form)
    fireEvent.click(refresh)
    expect(screen.getByText('Saving budget…')).toBeInTheDocument()
    expect(refresh).toBeDisabled()
    expect(screen.getByLabelText('Tenant monthly limit')).toBeDisabled()
    expect(api.setTenantBudget).toHaveBeenCalledTimes(1)
    expect(api.adminBudgets).toHaveBeenCalledTimes(2)
    await act(async () => { write.resolve({...example, tenant: {...example.tenant,
      monthly_limit_credits: '0.2', spent_credits: '0.099'}}) })
    expect(screen.getByLabelText('Tenant monthly limit')).toHaveValue('0.2')
    expect(screen.getByText('0.099')).toBeInTheDocument()
    expect(refresh).toBeEnabled()
    expect(api.adminBudgets).toHaveBeenCalledTimes(2)
  })

  it('keeps a failed save editable and marks retained balances as potentially stale', async () => {
    vi.mocked(api.adminBudgets).mockResolvedValue(example)
    vi.mocked(api.setTenantBudget).mockRejectedValue(new Error('Save unavailable'))
    render(<BudgetSection apiKey="session" onUnauthorized={vi.fn()}/>)
    await screen.findByDisplayValue('0.1')
    fireEvent.change(screen.getByLabelText('Tenant monthly limit'), {target: {value: '0.2'}})
    fireEvent.click(screen.getByRole('button', {name: 'Save tenant budget'}))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Previously loaded budgets may be out of date/)
    expect(screen.getByLabelText('Tenant monthly limit')).toHaveValue('0.2')
    expect(screen.getByRole('button', {name: 'Save tenant budget'})).toBeEnabled()
  })

  it('removes protected forms when a save is forbidden', async () => {
    vi.mocked(api.adminBudgets).mockResolvedValue(example)
    vi.mocked(api.setTenantBudget).mockRejectedValue(new ApiError(403, 'Forbidden'))
    render(<BudgetSection apiKey="session" onUnauthorized={vi.fn()}/>)
    await screen.findByDisplayValue('0.1')
    fireEvent.click(screen.getByRole('button', {name: 'Save tenant budget'}))
    expect(await screen.findByRole('alert')).toHaveTextContent('Access denied')
    expect(screen.queryByLabelText('Tenant monthly limit')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', {name: 'Edit'})).not.toBeInTheDocument()
  })

  it('clears drafts on a session change and ignores an old save failure', async () => {
    const write = deferred<AdminBudgets>()
    const unauthorized = vi.fn()
    vi.mocked(api.adminBudgets).mockResolvedValueOnce(example).mockResolvedValueOnce({
      ...example, tenant: {...example.tenant, monthly_limit_credits: '0.9'}, users: [],
    })
    vi.mocked(api.setTenantBudget).mockReturnValue(write.promise)
    const { rerender } = render(<BudgetSection apiKey="first" onUnauthorized={unauthorized}/>)
    await screen.findByDisplayValue('0.1')
    fireEvent.change(screen.getByLabelText('Tenant monthly limit'), {target: {value: '0.2'}})
    fireEvent.click(screen.getByRole('button', {name: 'Save tenant budget'}))
    rerender(<BudgetSection apiKey="second" onUnauthorized={unauthorized}/>)
    expect(screen.queryByDisplayValue('0.2')).not.toBeInTheDocument()
    await screen.findByDisplayValue('0.9')
    await act(async () => { write.reject(new ApiError(401, 'Old session expired')) })
    expect(unauthorized).not.toHaveBeenCalled()
    expect(screen.queryByText('Tenant budget saved')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Tenant monthly limit')).toHaveValue('0.9')
  })

  it('validates credit values before submitting a budget', async () => {
    vi.mocked(api.adminBudgets).mockResolvedValue(example)
    render(<BudgetSection apiKey="session" onUnauthorized={vi.fn()}/>)
    await screen.findByDisplayValue('0.1')
    fireEvent.change(screen.getByLabelText('Tenant monthly limit'), {target: {value: '-1'}})
    fireEvent.click(screen.getByRole('button', {name: 'Save tenant budget'}))
    expect(screen.getByRole('alert')).toHaveTextContent('Use a nonnegative credit amount')
    fireEvent.change(screen.getByLabelText('Tenant monthly limit'), {target: {value: ''}})
    fireEvent.change(screen.getByLabelText('Per-request reservation'), {target: {value: '0'}})
    fireEvent.click(screen.getByRole('button', {name: 'Save tenant budget'}))
    expect(screen.getByRole('alert')).toHaveTextContent('Reservation must be positive')
    expect(api.setTenantBudget).not.toHaveBeenCalled()
  })
})
