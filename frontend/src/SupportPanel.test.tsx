import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, ApiError } from './api'
import SupportPanel from './SupportPanel'
import type { SupportChatList, SupportMessages } from './types'
import { navigate } from './navigation'

vi.mock('./api', async importOriginal => ({
  ...await importOriginal<typeof import('./api')>(),
  api: {supportChats: vi.fn(), createSupportChat: vi.fn(), supportMessages: vi.fn(),
    sendSupportMessage: vi.fn(), setSupportStatus: vi.fn()},
}))

const stamp = '2026-10-19T12:00:00Z'
const chat = {id: 1, tenant_id: 7, user_id: 2, username: 'reader', subject: 'Upload problem',
  status: 'open' as const, created_at: stamp, updated_at: stamp}
const message = {id: 1, sender_user_id: 2, username: 'reader', author_kind: 'user' as const,
  body: 'My upload is waiting.', created_at: stamp}
const list: SupportChatList = {items: [chat], total: 1, page: 1, page_size: 20, is_staff: false, enabled: true}
const detail: SupportMessages = {chat, messages: [message], has_more: false}
const props = {apiKey: 'user-key', onUnauthorized: vi.fn()}

beforeEach(() => {
  vi.clearAllMocks()
  window.history.replaceState({}, '', '/support?chat=1')
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true)
  vi.mocked(api.supportChats).mockReset().mockResolvedValue(list)
  vi.mocked(api.supportMessages).mockReset().mockResolvedValue(detail)
  vi.mocked(api.createSupportChat).mockReset().mockResolvedValue(chat)
  vi.mocked(api.sendSupportMessage).mockReset().mockResolvedValue(message)
  vi.mocked(api.setSupportStatus).mockReset().mockResolvedValue({...chat, status: 'closed'})
})
afterEach(() => {cleanup(); vi.useRealTimers(); vi.restoreAllMocks()})

it('opens a direct chat URL, renders messages as text and hides staff controls', async () => {
  vi.mocked(api.supportMessages).mockResolvedValue({...detail, messages: [{...message, body: '<img src=x onerror=alert(1)>'}]})
  const {container} = render(<SupportPanel {...props}/>)
  expect(await screen.findByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
  expect(container.querySelector('img')).toBeNull()
  expect(api.supportMessages).toHaveBeenCalledWith('user-key', 1, 0, expect.any(AbortSignal))
  expect(screen.queryByRole('button', {name: 'Close chat'})).not.toBeInTheDocument()
  expect(screen.queryByText(/tenant #7/)).not.toBeInTheDocument()
  expect(screen.getByRole('log', {name: 'Support messages'})).toHaveAttribute('aria-live', 'polite')
})

it('creates a private chat once and navigates to its URL', async () => {
  window.history.replaceState({}, '', '/support')
  let finish!: (value: typeof chat) => void
  vi.mocked(api.createSupportChat).mockReturnValueOnce(new Promise(resolve => {finish = resolve}))
  render(<SupportPanel {...props}/>)
  fireEvent.change(await screen.findByLabelText('Subject'), {target: {value: 'New issue'}})
  fireEvent.change(screen.getByLabelText('Describe your issue'), {target: {value: 'Please help.'}})
  const form = screen.getByRole('form', {name: 'Start support chat'})
  fireEvent.submit(form); fireEvent.submit(form)
  expect(api.createSupportChat).toHaveBeenCalledOnce()
  expect(api.createSupportChat).toHaveBeenCalledWith('user-key', 'New issue', 'Please help.', expect.any(String))
  await act(async () => finish(chat))
  await screen.findByText('My upload is waiting.')
  expect(window.location.search).toBe('?chat=1')
  expect(screen.getByLabelText('Subject')).toHaveValue('')
})

it('sends once, reuses a request key after failure and preserves the draft', async () => {
  let fail!: (reason: Error) => void
  vi.mocked(api.sendSupportMessage).mockReturnValueOnce(new Promise((_, reject) => {fail = reject}))
  render(<SupportPanel {...props}/>)
  fireEvent.change(await screen.findByLabelText('Message'), {target: {value: 'Can you check it?'}})
  const form = screen.getByRole('form', {name: 'Reply to support'})
  fireEvent.submit(form); fireEvent.submit(form)
  expect(api.sendSupportMessage).toHaveBeenCalledOnce()
  const key = vi.mocked(api.sendSupportMessage).mock.calls[0][3]
  await act(async () => fail(new ApiError(0, 'Connection interrupted')))
  expect(await screen.findByRole('alert')).toHaveTextContent('Connection interrupted')
  expect(screen.getByLabelText('Message')).toHaveValue('Can you check it?')
  fireEvent.submit(form)
  await waitFor(() => expect(screen.getByLabelText('Message')).toHaveValue(''))
  expect(vi.mocked(api.sendSupportMessage).mock.calls[1][3]).toBe(key)
})

it('shows the central inbox and lets designated staff close/reopen a chat', async () => {
  vi.mocked(api.supportChats).mockResolvedValue({...list, is_staff: true})
  render(<SupportPanel {...props}/>)
  await screen.findByRole('heading', {name: 'Central support inbox'})
  expect(screen.getByText('reader · tenant #7')).toBeInTheDocument()
  vi.mocked(api.supportMessages).mockResolvedValue({...detail, chat: {...chat, status: 'closed'}})
  fireEvent.click(await screen.findByRole('button', {name: 'Close chat'}))
  await screen.findByRole('button', {name: 'Reopen chat'})
  expect(api.setSupportStatus).toHaveBeenCalledWith('user-key', 1, 'closed')
  expect(screen.queryByLabelText('Message')).not.toBeInTheDocument()
  vi.mocked(api.supportMessages).mockResolvedValue(detail)
  fireEvent.click(screen.getByRole('button', {name: 'Reopen chat'}))
  await screen.findByLabelText('Message')
  expect(api.setSupportStatus).toHaveBeenLastCalledWith('user-key', 1, 'open')
})

it('paginates and filters the inbox without changing the selected conversation', async () => {
  vi.mocked(api.supportChats).mockImplementation(async (_, page, size) => ({...list, page, page_size: size, total: 21}))
  render(<SupportPanel {...props}/>)
  await screen.findByText('My upload is waiting.')
  fireEvent.change(screen.getByLabelText('Message'), {target: {value: 'Keep this draft'}})
  fireEvent.click(screen.getByRole('button', {name: 'Next'}))
  await waitFor(() => expect(api.supportChats).toHaveBeenLastCalledWith('user-key', 2, 20, 'all', expect.any(AbortSignal)))
  fireEvent.change(screen.getByLabelText('Support status filter'), {target: {value: 'closed'}})
  await waitFor(() => expect(api.supportChats).toHaveBeenLastCalledWith('user-key', 1, 20, 'closed', expect.any(AbortSignal)))
  expect(window.location.search).toBe('?chat=1')
  expect(screen.getByText('My upload is waiting.')).toBeInTheDocument()
  expect(screen.getByLabelText('Message')).toHaveValue('Keep this draft')
})

it('keeps messages after an ordinary refresh failure and preserves edits', async () => {
  render(<SupportPanel {...props}/>)
  fireEvent.change(await screen.findByLabelText('Message'), {target: {value: 'Unsaved reply'}})
  vi.mocked(api.supportMessages).mockRejectedValueOnce(new Error('Temporary outage'))
  fireEvent.click(screen.getByRole('button', {name: 'Refresh messages'}))
  expect(await screen.findByRole('alert')).toHaveTextContent('Previously loaded messages may be out of date')
  expect(screen.getByText('My upload is waiting.')).toBeInTheDocument()
  expect(screen.getByLabelText('Message')).toHaveValue('Unsaved reply')
  fireEvent.click(screen.getByRole('button', {name: 'Refresh messages'}))
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
})

it.each([401, 403, 404])('clears protected thread content on HTTP %i', async status => {
  render(<SupportPanel {...props}/>)
  await screen.findByText('My upload is waiting.')
  vi.mocked(api.supportMessages).mockRejectedValueOnce(new ApiError(status, 'Unavailable'))
  fireEvent.click(screen.getByRole('button', {name: 'Refresh messages'}))
  await screen.findByRole('alert')
  expect(screen.queryByText('My upload is waiting.')).not.toBeInTheDocument()
  expect(props.onUnauthorized).toHaveBeenCalledTimes(status === 401 ? 1 : 0)
})

it('catches up in incremental pages and deduplicates messages', async () => {
  const reply = {...message, id: 2, author_kind: 'staff' as const, body: 'Please restart the worker.'}
  vi.mocked(api.supportMessages).mockResolvedValueOnce({...detail, has_more: true})
    .mockResolvedValue({...detail, messages: [message, reply]})
  render(<SupportPanel {...props}/>)
  await screen.findByText('Please restart the worker.')
  expect(api.supportMessages).toHaveBeenNthCalledWith(2, 'user-key', 1, 1, expect.any(AbortSignal))
  expect(within(screen.getByRole('log')).getAllByText('My upload is waiting.')).toHaveLength(1)
})

it('polls without flicker, preserves drafts and prevents overlapping requests', async () => {
  vi.useFakeTimers()
  let finish!: (value: SupportMessages) => void
  let view!: ReturnType<typeof render>
  await act(async () => {view = render(<SupportPanel {...props}/>)})
  fireEvent.change(screen.getByLabelText('Message'), {target: {value: 'Draft'}})
  vi.mocked(api.supportMessages).mockReturnValueOnce(new Promise(resolve => {finish = resolve}))
  await act(async () => vi.advanceTimersByTime(9000))
  expect(api.supportMessages).toHaveBeenCalledTimes(2)
  expect(screen.getByText('My upload is waiting.')).toBeInTheDocument()
  expect(screen.getByRole('button', {name: 'Send message'})).toBeEnabled()
  expect(screen.getByLabelText('Message')).toHaveValue('Draft')
  view.unmount()
  await act(async () => {finish(detail); vi.advanceTimersByTime(9000)})
  expect(api.supportMessages).toHaveBeenCalledTimes(2)
})

it('pauses hidden/offline polling and resumes on visibility/network restoration', async () => {
  vi.useFakeTimers()
  await act(async () => {render(<SupportPanel {...props}/>)})
  const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
  await act(async () => vi.advanceTimersByTime(9000))
  expect(api.supportMessages).toHaveBeenCalledOnce()
  visibility.mockReturnValue('visible')
  await act(async () => document.dispatchEvent(new Event('visibilitychange')))
  expect(api.supportMessages).toHaveBeenCalledTimes(2)
  const online = vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
  await act(async () => vi.advanceTimersByTime(9000))
  expect(api.supportMessages).toHaveBeenCalledTimes(2)
  online.mockReturnValue(true)
  await act(async () => window.dispatchEvent(new Event('online')))
  expect(api.supportMessages).toHaveBeenCalledTimes(3)
})

it('ignores late replies after switching conversations or sessions', async () => {
  let finish!: (value: SupportMessages) => void
  vi.mocked(api.supportMessages).mockReturnValueOnce(new Promise(resolve => {finish = resolve}))
  const view = render(<SupportPanel {...props}/>)
  await waitFor(() => expect(api.supportMessages).toHaveBeenCalled())
  vi.mocked(api.supportMessages).mockResolvedValue({...detail, chat: {...chat, id: 2}, messages: [{...message, id: 2, body: 'Second chat'}]})
  act(() => navigate('/support?chat=2'))
  await screen.findByText('Second chat')
  await act(async () => finish(detail))
  expect(screen.queryByText('My upload is waiting.')).not.toBeInTheDocument()
  vi.mocked(api.supportMessages).mockResolvedValue({...detail, messages: [{...message, body: 'New session'}]})
  view.rerender(<SupportPanel {...props} apiKey="new-key"/>)
  await screen.findByText('New session')
  expect(screen.queryByText('Second chat')).not.toBeInTheDocument()
})

it('disables new chats while unconfigured but leaves existing history readable', async () => {
  vi.mocked(api.supportChats).mockResolvedValue({...list, enabled: false})
  render(<SupportPanel {...props}/>)
  await screen.findByText('My upload is waiting.')
  expect(screen.getByText(/Support is not configured yet/)).toBeInTheDocument()
  expect(screen.getByRole('button', {name: 'Start chat'})).toBeDisabled()
  expect(screen.getByRole('button', {name: 'Send message'})).toBeDisabled()
})
