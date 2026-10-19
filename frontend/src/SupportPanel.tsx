import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError } from './api'
import PageFrame from './PageFrame'
import Pagination from './Pagination'
import { navigate, useLocation } from './navigation'
import { useAdminResource } from './useAdminResource'
import { useVisiblePolling } from './useVisiblePolling'
import type { SupportChat, SupportMessage } from './types'

interface Props { apiKey: string; onUnauthorized: () => void }

function requestKey(ref: {current: {text: string; key: string} | null}, text: string) {
  if (!ref.current || ref.current.text !== text) ref.current = {text, key: crypto.randomUUID()}
  return ref.current.key
}

export default function SupportPanel(props: Props) {
  return <SupportInbox key={props.apiKey} {...props}/>
}

function SupportInbox({apiKey, onUnauthorized}: Props) {
  const location = useLocation()
  const rawId = new URLSearchParams(location.split('?')[1]).get('chat') ?? ''
  const chatId = /^[1-9]\d*$/.test(rawId) && Number.isSafeInteger(Number(rawId)) ? Number(rawId) : null
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)
  const [status, setStatus] = useState('all')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [permissions, setPermissions] = useState<{is_staff: boolean; enabled: boolean} | null>(null)
  const creationKey = useRef<{text: string; key: string} | null>(null)
  const loader = useCallback((signal?: AbortSignal) => api.supportChats(apiKey, page, size, status, signal),
    [apiKey, page, size, status])
  const {data, error, stale, pending, refresh, refreshInBackground, save} =
    useAdminResource(loader, onUnauthorized, 'Support access denied.')
  useVisiblePolling(refreshInBackground)
  useEffect(() => {if (data && data.page !== page) setPage(data.page)}, [data, page])
  useEffect(() => {
    if (data) setPermissions(previous => previous?.is_staff === data.is_staff && previous.enabled === data.enabled
      ? previous : {is_staff: data.is_staff, enabled: data.enabled})
  }, [data])
  const capabilities = error === 'Support access denied.' ? null : data ?? permissions

  async function create(event: FormEvent) {
    event.preventDefault()
    const trimmedSubject = subject.trim(), trimmedBody = body.trim()
    if (!trimmedSubject || !trimmedBody || pending || !data?.enabled) return
    const key = requestKey(creationKey, JSON.stringify([trimmedSubject, trimmedBody]))
    let created: SupportChat | null = null
    const success = await save(async signal => {
      created = await api.createSupportChat(apiKey, trimmedSubject, trimmedBody, key)
      return loader(signal)
    })
    if (success && created) {
      setSubject(''); setBody(''); creationKey.current = null
      navigate(`/support?chat=${(created as SupportChat).id}`)
    }
  }

  return <PageFrame title={capabilities?.is_staff ? 'Central support inbox' : 'Support'}
    subtitle={capabilities?.is_staff ? 'Private support conversations across all tenants.' : 'Private chat with the support team.'}
    actions={<button type="button" className="btn-primary" disabled={pending} onClick={() => void refresh()}>Refresh support</button>}>
    <div className="p-4 sm:p-6 space-y-5">
      <p className="text-sm text-slate-500">Messages update automatically while this page is open. Replies may not be immediate.</p>
      {error && <p role="alert" className="notice-error">{error}{stale && ' Previously loaded support chats may be out of date.'}</p>}
      {!data && pending && <p role="status">Loading support…</p>}
      {capabilities && <>
        {!capabilities.enabled && <p role="status" className="notice-warning">Support is not configured yet. Existing conversations remain available.</p>}
        <div className="grid gap-5 lg:grid-cols-[minmax(260px,1fr)_minmax(0,2fr)]">
          <section aria-label="Support conversations" className="space-y-3 min-w-0">
            {data && <>
            <label className="text-sm">Status <select aria-label="Support status filter" value={status}
              onChange={e => {setStatus(e.target.value); setPage(1)}} className="border rounded-lg p-2 ml-2">
              <option value="all">All</option><option value="open">Open</option><option value="closed">Closed</option>
            </select></label>
            <ul className="space-y-2">
              {data.items.map(chat => <li key={chat.id}><button type="button" aria-pressed={chat.id === chatId}
                className={`w-full text-left border rounded-xl p-3 bg-white ${chat.id === chatId ? 'border-indigo-500' : 'border-slate-200'}`}
                onClick={() => navigate(`/support?chat=${chat.id}`)}>
                <span className="font-semibold break-words">{chat.subject}</span>
                <span className="block text-xs text-slate-500 mt-1">{chat.status === 'open' ? 'Open' : 'Closed'} · {new Date(chat.updated_at).toLocaleString()}</span>
                {data.is_staff && <span className="block text-xs text-slate-500">{chat.username} · tenant #{chat.tenant_id}</span>}
              </button></li>)}
            </ul>
            {data.items.length === 0 && <p className="text-sm text-slate-500">No support conversations match this filter.</p>}
            <Pagination page={data.page} pageSize={size} total={data.total} disabled={pending}
              onPage={setPage} onPageSize={value => {setSize(value); setPage(1)}}/>
            <form aria-label="Start support chat" onSubmit={create} className="space-y-3 bg-white border rounded-xl p-4">
              <h2 className="font-semibold">Start a support chat</h2>
              <label className="block text-sm">Subject<input value={subject} onChange={e => setSubject(e.target.value)}
                maxLength={120} required disabled={pending || !data.enabled} className="block w-full border rounded-lg p-2 mt-1"/></label>
              <label className="block text-sm">Describe your issue<textarea value={body} onChange={e => setBody(e.target.value)}
                maxLength={4000} required rows={3} disabled={pending || !data.enabled} className="block w-full border rounded-lg p-2 mt-1"/></label>
              <button type="submit" className="btn-primary" disabled={pending || !data.enabled || !subject.trim() || !body.trim()}>Start chat</button>
            </form>
            </>}
          </section>
          {chatId ? <SupportThread key={`${apiKey}:${chatId}:${capabilities.is_staff}`} apiKey={apiKey} chatId={chatId}
            isStaff={capabilities.is_staff} enabled={capabilities.enabled} onUnauthorized={onUnauthorized} onChanged={refreshInBackground}/>
            : <p className="text-sm text-slate-500 p-5">Select a conversation or start a new support chat.</p>}
        </div>
      </>}
    </div>
  </PageFrame>
}

function SupportThread({apiKey, chatId, isStaff, enabled, onUnauthorized, onChanged}: Props & {
  chatId: number; isStaff: boolean; enabled: boolean; onChanged: () => Promise<boolean>
}) {
  const accumulated = useRef<SupportMessage[]>([])
  const [draft, setDraft] = useState('')
  const messageKey = useRef<{text: string; key: string} | null>(null)
  const logRef = useRef<HTMLDivElement>(null)
  const nearBottom = useRef(true)
  const loader = useCallback(async (signal?: AbortSignal) => {
    try {
      const after = accumulated.current.at(-1)?.id ?? 0
      const next = await api.supportMessages(apiKey, chatId, after, signal)
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
      const messages = new Map(accumulated.current.map(message => [message.id, message]))
      next.messages.forEach(message => messages.set(message.id, message))
      accumulated.current = [...messages.values()].sort((a, b) => a.id - b.id)
      return {...next, messages: accumulated.current}
    } catch (err) {
      if (!signal?.aborted && err instanceof ApiError && [401, 403, 404].includes(err.status)) {
        accumulated.current = []
        if (err.status === 404) throw new ApiError(403, 'Support chat access is no longer available.')
      }
      throw err
    }
  }, [apiKey, chatId])
  const {data, error, stale, pending, refresh, refreshInBackground, save} =
    useAdminResource(loader, onUnauthorized, 'Support chat access is no longer available.')
  useVisiblePolling(refreshInBackground)
  // Catch up in bounded pages, then use the normal three-second poll interval.
  useEffect(() => {
    if (data?.has_more && document.visibilityState === 'visible' && navigator.onLine) void refreshInBackground()
  }, [data, refreshInBackground])
  useEffect(() => {
    const log = logRef.current
    if (log && nearBottom.current) log.scrollTop = log.scrollHeight
  }, [data?.messages.length])

  async function send(event: FormEvent) {
    event.preventDefault()
    const body = draft.trim()
    if (!body || pending || data?.chat.status !== 'open' || !enabled) return
    const key = requestKey(messageKey, body)
    const success = await save(async signal => {
      await api.sendSupportMessage(apiKey, chatId, body, key)
      return loader(signal)
    })
    if (success) {setDraft(''); messageKey.current = null; void onChanged()}
  }
  async function changeStatus() {
    if (!data || pending || !isStaff) return
    const status = data.chat.status === 'open' ? 'closed' : 'open'
    const success = await save(async signal => {
      await api.setSupportStatus(apiKey, chatId, status)
      return loader(signal)
    })
    if (success) void onChanged()
  }

  return <section aria-label="Support chat" className="bg-white border rounded-xl p-4 space-y-4 min-w-0">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="font-semibold break-words">{data?.chat.subject ?? 'Support conversation'}</h2>
      <div className="flex gap-2">
        <button type="button" className="table-button" disabled={pending} onClick={() => void refresh()}>Refresh messages</button>
        {isStaff && data && <button type="button" className="table-button" disabled={pending} onClick={() => void changeStatus()}>
          {data.chat.status === 'open' ? 'Close chat' : 'Reopen chat'}</button>}
      </div>
    </div>
    {error && <p role="alert" className="notice-error">{error}{stale && ' Previously loaded messages may be out of date.'}</p>}
    {!data && pending && <p role="status">Loading messages…</p>}
    {data && <>
      <div role="log" aria-label="Support messages" aria-live="polite" aria-relevant="additions" ref={logRef}
        onScroll={e => {const log = e.currentTarget; nearBottom.current = log.scrollHeight - log.scrollTop - log.clientHeight < 80}}
        className="max-h-[50dvh] overflow-y-auto space-y-3 p-1">
        {data.messages.map(message => <article key={message.id} className={`rounded-xl p-3 ${message.author_kind === 'staff' ? 'bg-indigo-50' : 'bg-slate-50'}`}>
          <p className="text-xs font-semibold text-slate-600">{message.author_kind === 'staff' ? 'Support' : message.username} · {new Date(message.created_at).toLocaleString()}</p>
          <p className="whitespace-pre-wrap break-words text-sm mt-1">{message.body}</p>
        </article>)}
      </div>
      {data.has_more && <p role="status" className="text-sm text-slate-500">Loading more messages…</p>}
      {data.chat.status === 'closed' ? <p role="status" className="text-sm text-slate-500">This chat is closed. Support staff can reopen it.</p>
        : <form aria-label="Reply to support" onSubmit={send} className="space-y-3">
          <label className="block text-sm">Message<textarea value={draft} onChange={e => setDraft(e.target.value)} maxLength={4000}
            required rows={3} disabled={pending || !enabled} className="block w-full border rounded-lg p-2 mt-1"/></label>
          <button type="submit" className="btn-primary" disabled={pending || !enabled || !draft.trim()}>Send message</button>
        </form>}
    </>}
  </section>
}
