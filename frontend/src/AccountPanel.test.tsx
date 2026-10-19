import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, ApiError } from './api'
import AccountPanel from './AccountPanel'
import type { AccountAction, AccountSessions } from './types'

vi.mock('./api', async original => ({
  ...await original<typeof import('./api')>(),
  api: {accountSessions: vi.fn(), changePassword: vi.fn(), revokeOwnSession: vi.fn(), revokeOtherSessions: vi.fn()},
}))

const current = {id: 101, created_at: '2026-10-19T08:00:00Z', expires_at: '2026-10-19T20:00:00Z', current: true}
const other = {...current, id: 102, current: false}
const listing: AccountSessions = {password_enabled: true, password_session: true,
  sessions: [current, other], total: 2, page: 1, page_size: 20}
const props = {apiKey: '', onUnauthorized: vi.fn(), onSignedOut: vi.fn()}

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true)
  vi.mocked(api.accountSessions).mockReset().mockResolvedValue(listing)
  vi.mocked(api.changePassword).mockReset().mockResolvedValue({sign_in_required: true})
  vi.mocked(api.revokeOwnSession).mockReset().mockResolvedValue({sign_in_required: false, revoked_count: 1})
  vi.mocked(api.revokeOtherSessions).mockReset().mockResolvedValue({sign_in_required: false, revoked_count: 1})
})
afterEach(() => {cleanup(); vi.useRealTimers(); vi.restoreAllMocks()})

function fill(currentPassword = 'old-password-for-tests', newPassword = 'new-password-for-tests', confirm = newPassword) {
  fireEvent.change(screen.getByLabelText('Current password'), {target: {value: currentPassword}})
  fireEvent.change(screen.getByLabelText('New password'), {target: {value: newPassword}})
  fireEvent.change(screen.getByLabelText('Confirm new password'), {target: {value: confirm}})
}

it('shows active sessions with current markers and password fields without device guesses', async () => {
  render(<AccountPanel {...props}/>)
  await screen.findByText('Current session')
  expect(screen.getByRole('table', {name: 'Active password sessions'})).toBeInTheDocument()
  expect(screen.getByLabelText('Current password')).toHaveAttribute('type', 'password')
  expect(screen.getByLabelText('New password')).toHaveAttribute('autocomplete', 'new-password')
  expect(screen.getByText(/Device names and locations are not recorded/)).toBeInTheDocument()
  expect(api.accountSessions).toHaveBeenCalledWith('', 1, 20, expect.any(AbortSignal))
})

it.each([
  ['new-password-for-tests', 'different-value', 'New passwords do not match.'],
  ['short', 'short', 'Use 12–128 characters'],
  ['old-password-for-tests', 'old-password-for-tests', 'Choose a password different'],
])('validates new password %s locally', async (password, confirmation, error) => {
  render(<AccountPanel {...props}/>)
  await screen.findByLabelText('Current password')
  fill('old-password-for-tests', password, confirmation)
  fireEvent.submit(screen.getByRole('form', {name: 'Change password'}))
  expect(screen.getByRole('alert')).toHaveTextContent(error)
  expect(api.changePassword).not.toHaveBeenCalled()
})

it('requires the current password and keeps the user signed in after a wrong-password response', async () => {
  vi.mocked(api.changePassword).mockRejectedValueOnce(new ApiError(400, 'Current password is incorrect.'))
  render(<AccountPanel {...props}/>)
  await screen.findByLabelText('Current password')
  fill()
  fireEvent.click(screen.getByRole('button', {name: 'Update password'}))
  expect(await screen.findByRole('alert')).toHaveTextContent('Current password is incorrect.')
  expect(screen.getByText('Current session')).toBeInTheDocument()
  expect(props.onUnauthorized).not.toHaveBeenCalled()
  expect(props.onSignedOut).not.toHaveBeenCalled()
})

it('updates a password once, clears fields and signs out only after confirmed success', async () => {
  let finish!: (value: AccountAction) => void
  vi.mocked(api.changePassword).mockReturnValueOnce(new Promise(resolve => {finish = resolve}))
  render(<AccountPanel {...props}/>)
  await screen.findByLabelText('Current password')
  fill()
  const form = screen.getByRole('form', {name: 'Change password'})
  fireEvent.submit(form); fireEvent.submit(form)
  expect(api.changePassword).toHaveBeenCalledOnce()
  expect(api.changePassword).toHaveBeenCalledWith('', 'old-password-for-tests', 'new-password-for-tests')
  expect(props.onSignedOut).not.toHaveBeenCalled()
  await act(async () => finish({sign_in_required: true}))
  expect(props.onSignedOut).toHaveBeenCalledWith('Password changed. Sign in again with your new password.')
  expect(screen.getByLabelText('Current password')).toHaveValue('')
  expect(screen.getByLabelText('New password')).toHaveValue('')
  expect(api.accountSessions).toHaveBeenCalledOnce()
})

it('explains an uncertain password change without blindly resubmitting', async () => {
  vi.mocked(api.changePassword).mockRejectedValueOnce(new ApiError(0, 'Connection interrupted'))
  render(<AccountPanel {...props}/>)
  await screen.findByLabelText('Current password')
  fill()
  fireEvent.submit(screen.getByRole('form', {name: 'Change password'}))
  expect(await screen.findByRole('alert')).toHaveTextContent('Try signing in with the new password')
  expect(api.changePassword).toHaveBeenCalledOnce()
  expect(props.onSignedOut).not.toHaveBeenCalled()
})

it('preserves an API key connection after password changes and offers sign-out of all password sessions', async () => {
  vi.mocked(api.accountSessions).mockResolvedValue({...listing, password_session: false, sessions: [{...current, current: false}]})
  vi.mocked(api.changePassword).mockResolvedValue({sign_in_required: false})
  render(<AccountPanel {...props} apiKey="rag_key"/>)
  await screen.findByLabelText('Current password')
  expect(screen.getByRole('button', {name: 'Sign out all password sessions'})).toBeInTheDocument()
  fill()
  fireEvent.submit(screen.getByRole('form', {name: 'Change password'}))
  await screen.findByText(/Your API key connection remains active/)
  expect(props.onSignedOut).not.toHaveBeenCalled()
  expect(api.changePassword).toHaveBeenCalledWith('rag_key', expect.any(String), expect.any(String))
})

it('requires confirmation and prevents duplicate individual revocation', async () => {
  render(<AccountPanel {...props}/>)
  await screen.findByRole('button', {name: 'Sign out session 102'})
  vi.mocked(window.confirm).mockReturnValueOnce(false)
  fireEvent.click(screen.getByRole('button', {name: 'Sign out session 102'}))
  expect(api.revokeOwnSession).not.toHaveBeenCalled()
  let finish!: (value: AccountAction) => void
  vi.mocked(api.revokeOwnSession).mockReturnValueOnce(new Promise(resolve => {finish = resolve}))
  vi.mocked(api.accountSessions).mockResolvedValue({...listing, sessions: [current], total: 1})
  const button = screen.getByRole('button', {name: 'Sign out session 102'})
  fireEvent.click(button); fireEvent.click(button)
  expect(api.revokeOwnSession).toHaveBeenCalledOnce()
  await act(async () => finish({sign_in_required: false, revoked_count: 1}))
  await waitFor(() => expect(screen.queryByText('Session #102')).not.toBeInTheDocument())
  expect(screen.getByText('Current session')).toBeInTheDocument()
  expect(props.onSignedOut).not.toHaveBeenCalled()
})

it('signs out the current session only after revocation succeeds', async () => {
  vi.mocked(api.revokeOwnSession).mockResolvedValue({sign_in_required: true, revoked_count: 1})
  render(<AccountPanel {...props}/>)
  fireEvent.click(await screen.findByRole('button', {name: 'Sign out current session'}))
  await waitFor(() => expect(props.onSignedOut).toHaveBeenCalledWith('This session was signed out. Sign in again to continue.'))
})

it('signs out other sessions while preserving current authentication and unsaved password edits', async () => {
  render(<AccountPanel {...props}/>)
  await screen.findByLabelText('Current password')
  fill()
  vi.mocked(api.accountSessions).mockResolvedValue({...listing, sessions: [current], total: 1})
  fireEvent.click(screen.getByRole('button', {name: 'Sign out other sessions'}))
  await screen.findByText('Signed out 1 password session(s).')
  expect(api.revokeOtherSessions).toHaveBeenCalledWith('')
  expect(screen.getByText('Current session')).toBeInTheDocument()
  expect(screen.getByLabelText('New password')).toHaveValue('new-password-for-tests')
  expect(props.onSignedOut).not.toHaveBeenCalled()
})

it('adjusts to a valid page after revoking its last session', async () => {
  let removed = false
  vi.mocked(api.accountSessions).mockImplementation(async (_, page, size) => ({...listing,
    total: removed ? 20 : 21, page: removed ? 1 : page, page_size: size,
    sessions: page === 2 && !removed ? [{...other, id: 121}] : [current],
  }))
  vi.mocked(api.revokeOwnSession).mockImplementation(async () => {removed = true; return {sign_in_required: false, revoked_count: 1}})
  render(<AccountPanel {...props}/>)
  fireEvent.click(await screen.findByRole('button', {name: 'Next'}))
  fireEvent.click(await screen.findByRole('button', {name: 'Sign out session 121'}))
  await screen.findByText('20 results · Page 1 of 1')
  await waitFor(() => expect(api.accountSessions).toHaveBeenLastCalledWith('', 1, 20, expect.any(AbortSignal)))
})

it('retains stale session data after refresh failures and clears it on access denial', async () => {
  render(<AccountPanel {...props}/>)
  await screen.findByText('Current session')
  vi.mocked(api.accountSessions).mockRejectedValueOnce(new Error('Temporary outage'))
  fireEvent.click(screen.getByRole('button', {name: 'Refresh sessions'}))
  expect(await screen.findByRole('alert')).toHaveTextContent('Previously loaded sessions may be out of date')
  expect(screen.getByText('Current session')).toBeInTheDocument()
  vi.mocked(api.accountSessions).mockRejectedValueOnce(new ApiError(403, 'Denied'))
  fireEvent.click(screen.getByRole('button', {name: 'Refresh sessions'}))
  await waitFor(() => expect(screen.queryByText('Current session')).not.toBeInTheDocument())
})

it('handles expired authentication and API-key-only accounts', async () => {
  vi.mocked(api.accountSessions).mockResolvedValue({...listing, password_enabled: false})
  render(<AccountPanel {...props}/>)
  await screen.findByText(/Ask your administrator to set an initial password/)
  expect(screen.queryByLabelText('New password')).not.toBeInTheDocument()
  vi.mocked(api.accountSessions).mockRejectedValueOnce(new ApiError(401, 'Expired'))
  fireEvent.click(screen.getByRole('button', {name: 'Refresh sessions'}))
  await waitFor(() => expect(props.onUnauthorized).toHaveBeenCalledOnce())
})

it('polls without clearing password drafts and pauses hidden/offline requests', async () => {
  vi.useFakeTimers()
  await act(async () => {render(<AccountPanel {...props}/>)})
  fill()
  await act(async () => vi.advanceTimersByTime(15000))
  expect(api.accountSessions).toHaveBeenCalledTimes(2)
  expect(screen.getByLabelText('New password')).toHaveValue('new-password-for-tests')
  const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
  await act(async () => vi.advanceTimersByTime(30000))
  expect(api.accountSessions).toHaveBeenCalledTimes(2)
  visibility.mockReturnValue('visible')
  await act(async () => document.dispatchEvent(new Event('visibilitychange')))
  expect(api.accountSessions).toHaveBeenCalledTimes(3)
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
  await act(async () => vi.advanceTimersByTime(30000))
  expect(api.accountSessions).toHaveBeenCalledTimes(3)
})

it('ignores old-session password results and clears secrets when switching accounts', async () => {
  let finish!: (value: AccountAction) => void
  vi.mocked(api.changePassword).mockReturnValueOnce(new Promise(resolve => {finish = resolve}))
  const view = render(<AccountPanel {...props}/>)
  await screen.findByLabelText('Current password')
  fill()
  fireEvent.submit(screen.getByRole('form', {name: 'Change password'}))
  view.rerender(<AccountPanel {...props} apiKey="new-account-key"/>)
  await screen.findByLabelText('Current password')
  expect(screen.getByLabelText('Current password')).toHaveValue('')
  await act(async () => finish({sign_in_required: true}))
  expect(props.onSignedOut).not.toHaveBeenCalled()
})
