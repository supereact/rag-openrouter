import {act, cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react'
import {afterEach, beforeEach, expect, it, vi} from 'vitest'
import CreditsPanel, {creditQuote} from './CreditsPanel'
import {api, ApiError} from './api'
import type {CreditOrder, CreditSummary} from './types'

vi.mock('./api', async original => {
  const actual = await original<typeof import('./api')>()
  return {...actual, api: {...actual.api, credits: vi.fn(), creditOrders: vi.fn(),
    creditTransactions: vi.fn(), purchaseCredits: vi.fn(), checkCreditOrder: vi.fn()}}
})
const summary: CreditSummary = {mode: 'sandbox', payments_enabled: true, usage_enforced: false,
  balance: '10', reserved: '0.01', available: '9.99', service_fee_percent: '5.5',
  minimum_credits: '10.00', maximum_credits: '1000.00',
  networks: [{id: 'usdttrc20', label: 'USDT · Tron (TRC-20)'}, {id: 'usdtbsc', label: 'USDT · BNB Smart Chain (BEP-20)'}]}
const order: CreditOrder = {id: '00000000-0000-0000-0000-000000000001', mode: 'sandbox',
  credits: '10.00', service_fee: '0.55', total_usd: '10.55', network: 'usdttrc20',
  status: 'waiting', pay_address: 'synthetic-test-address', pay_amount: '10.56',
  expires_at: '2099-10-19T12:00:00Z', created_at: '2026-10-19T11:00:00Z'}
const empty = {items: [], total: 0, page: 1, page_size: 20, pages: 1}
const props = {apiKey: 'key', onUnauthorized: vi.fn()}

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
  vi.mocked(api.credits).mockReset().mockResolvedValue(summary)
  vi.mocked(api.creditOrders).mockReset().mockResolvedValue(empty)
  vi.mocked(api.creditTransactions).mockReset().mockResolvedValue(empty)
  vi.mocked(api.purchaseCredits).mockReset().mockResolvedValue(order)
  vi.mocked(api.checkCreditOrder).mockReset().mockResolvedValue(order)
})
afterEach(() => {cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks()})

it('shows personal balances, sandbox context and the purchase fee without a card option', async () => {
  render(<CreditsPanel {...props}/>)
  await screen.findByText('Available credits')
  expect(screen.getByText('9.99')).toBeInTheDocument()
  expect(screen.getByText(/Test credits cannot pay for real AI usage/)).toBeInTheDocument()
  expect(screen.getByText('US$ 10.55')).toBeInTheDocument()
  expect(screen.queryByText(/credit card/i)).not.toBeInTheDocument()
  expect(creditQuote('25')).toEqual({credits: '25.00', fee: '1.38', total: '26.38'})
  for (const value of ['NaN', '9.99', '1000.01', '10.001']) expect(creditQuote(value)).toBeNull()
  fireEvent.change(screen.getByLabelText('Usable credits (USD)'), {target: {value: '9'}})
  expect(screen.getByRole('button', {name: 'Create test payment'})).toBeDisabled()
})

it('disables purchases when the provider is not configured', async () => {
  vi.mocked(api.credits).mockResolvedValue({...summary, mode: 'disabled', payments_enabled: false})
  render(<CreditsPanel {...props}/>)
  await screen.findByText(/USDT top-ups are not enabled/)
  expect(screen.getByRole('button', {name: 'Create USDT payment'})).toBeDisabled()
  expect(api.purchaseCredits).not.toHaveBeenCalled()
})

it('creates one order for duplicate clicks and displays payment amount and network', async () => {
  let finish!: (value: CreditOrder) => void
  vi.mocked(api.purchaseCredits).mockImplementationOnce(() => new Promise(resolve => {finish = resolve}))
  render(<CreditsPanel {...props}/>)
  const button = await screen.findByRole('button', {name: 'Create test payment'})
  fireEvent.click(button); fireEvent.click(button)
  expect(api.purchaseCredits).toHaveBeenCalledOnce()
  expect(api.purchaseCredits).toHaveBeenCalledWith('key', '10.00', 'usdttrc20', expect.any(String))
  vi.mocked(api.creditOrders).mockResolvedValue({...empty, items: [order], total: 1})
  await act(async () => finish(order))
  fireEvent.click(await screen.findByRole('button', {name: `Payment details ${order.id}`}))
  expect(screen.getByText('synthetic-test-address')).toBeInTheDocument()
  expect(screen.getByText('10.56 USDT')).toBeInTheDocument()
  expect(screen.getByText('USDT · Tron (TRC-20) only')).toBeInTheDocument()
  expect(screen.getByText(/Quote expires/)).toBeInTheDocument()
})

it('reuses the checkout key after an interrupted request', async () => {
  vi.mocked(api.purchaseCredits).mockRejectedValueOnce(new ApiError(502, 'Payment creation needs review'))
  render(<CreditsPanel {...props}/>)
  fireEvent.click(await screen.findByRole('button', {name: 'Create test payment'}))
  await screen.findByRole('alert')
  const first = vi.mocked(api.purchaseCredits).mock.calls[0][3]
  fireEvent.click(screen.getByRole('button', {name: 'Create test payment'}))
  await screen.findByText(/Payment order ready/)
  expect(vi.mocked(api.purchaseCredits).mock.calls[1][3]).toBe(first)
})

it('retains stale balances on a refresh failure and allows retry', async () => {
  render(<CreditsPanel {...props}/>)
  await screen.findByText('9.99')
  vi.mocked(api.credits).mockRejectedValueOnce(new Error('Temporary outage'))
  fireEvent.click(screen.getByRole('button', {name: 'Refresh credits'}))
  expect(await screen.findByRole('alert')).toHaveTextContent('Previously loaded balances may be out of date')
  expect(screen.getByText('9.99')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', {name: 'Refresh credits'}))
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
})

it.each([401, 403])('clears protected balances on HTTP %i', async status => {
  render(<CreditsPanel {...props}/>)
  await screen.findByText('9.99')
  vi.mocked(api.credits).mockRejectedValueOnce(new ApiError(status, 'Denied'))
  fireEvent.click(screen.getByRole('button', {name: 'Refresh credits'}))
  await screen.findByRole('alert')
  expect(screen.queryByText('9.99')).not.toBeInTheDocument()
  expect(props.onUnauthorized).toHaveBeenCalledTimes(status === 401 ? 1 : 0)
})

it('checks payment status and paginates orders independently of transactions', async () => {
  vi.mocked(api.creditOrders).mockImplementation(async (_, page, size) => ({...empty, items: [order], total: 21, pages: 2, page, page_size: size}))
  render(<CreditsPanel {...props}/>)
  fireEvent.click(await screen.findByRole('button', {name: 'Check status'}))
  await screen.findByText('Payment status checked.')
  expect(api.checkCreditOrder).toHaveBeenCalledWith('key', order.id)
  const section = screen.getByRole('table', {name: 'Credit payments'}).closest('section')!
  fireEvent.click(within(section).getByRole('button', {name: 'Next'}))
  await waitFor(() => expect(api.creditOrders).toHaveBeenLastCalledWith('key', 2, 20, expect.any(AbortSignal)))
  expect(api.creditTransactions).toHaveBeenLastCalledWith('key', 1, 20, expect.any(AbortSignal))
})

it('polls without disabling controls and stops after unmount', async () => {
  vi.useFakeTimers()
  vi.mocked(api.creditOrders).mockResolvedValue({...empty, items: [order], total: 1})
  let view!: ReturnType<typeof render>
  await act(async () => {view = render(<CreditsPanel {...props}/>)})
  expect(screen.getByRole('button', {name: 'Check status'})).toBeEnabled()
  let finish!: (value: CreditSummary) => void
  vi.mocked(api.credits).mockReturnValueOnce(new Promise(resolve => {finish = resolve}))
  await act(async () => vi.advanceTimersByTime(5000))
  expect(screen.getByRole('button', {name: 'Check status'})).toBeEnabled()
  expect(screen.getByText('9.99')).toBeInTheDocument()
  expect(api.credits).toHaveBeenCalledTimes(2)
  view.unmount()
  await act(async () => {finish(summary); vi.advanceTimersByTime(15000)})
  expect(api.credits).toHaveBeenCalledTimes(2)
})

it('pauses polling while hidden or offline and refreshes on return', async () => {
  vi.useFakeTimers()
  vi.mocked(api.creditOrders).mockResolvedValue({...empty, items: [order], total: 1})
  await act(async () => {render(<CreditsPanel {...props}/>)})
  const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
  await act(async () => {vi.advanceTimersByTime(10000)})
  expect(api.credits).toHaveBeenCalledOnce()
  visibility.mockReturnValue('visible')
  await act(async () => {document.dispatchEvent(new Event('visibilitychange'))})
  expect(api.credits).toHaveBeenCalledTimes(2)
  const online = vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
  await act(async () => {vi.advanceTimersByTime(10000)})
  expect(api.credits).toHaveBeenCalledTimes(2)
  online.mockReturnValue(true)
  await act(async () => {window.dispatchEvent(new Event('online'))})
  expect(api.credits).toHaveBeenCalledTimes(3)
})

it.each(['partially_paid', 'review', 'confirmed'])('does not instruct another payment for %s orders', async status => {
  vi.mocked(api.creditOrders).mockResolvedValue({...empty, items: [{...order, status}], total: 1})
  render(<CreditsPanel {...props}/>)
  fireEvent.click(await screen.findByRole('button', {name: `Payment details ${order.id}`}))
  expect(screen.queryByRole('button', {name: 'Copy address'})).not.toBeInTheDocument()
  expect(screen.queryByText('synthetic-test-address')).not.toBeInTheDocument()
})

it('ignores an obsolete session response', async () => {
  let finish!: (value: CreditSummary) => void
  vi.mocked(api.credits).mockReturnValueOnce(new Promise(resolve => {finish = resolve}))
  const view = render(<CreditsPanel {...props}/>)
  vi.mocked(api.credits).mockResolvedValue({...summary, available: '42'})
  view.rerender(<CreditsPanel {...props} apiKey="new-key"/>)
  await screen.findByText('42')
  await act(async () => finish(summary))
  expect(screen.queryByText('9.99')).not.toBeInTheDocument()
})
