import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from './api'
import PageFrame from './PageFrame'
import Pagination from './Pagination'
import { useAdminResource } from './useAdminResource'
import { useVisiblePolling } from './useVisiblePolling'
import type { AccountAction } from './types'

interface Props {
  apiKey: string
  onUnauthorized: () => void
  onSignedOut: (message: string) => void
}

export default function AccountPanel(props: Props) {
  return <AccountSecurity key={props.apiKey} {...props}/>
}

function AccountSecurity({apiKey, onUnauthorized, onSignedOut}: Props) {
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [formError, setFormError] = useState('')
  const [notice, setNotice] = useState('')
  const loader = useCallback((signal?: AbortSignal) => api.accountSessions(apiKey, page, size, signal), [apiKey, page, size])
  const {data, error, stale, pending, refresh, refreshInBackground, save} =
    useAdminResource(loader, onUnauthorized, 'Account security access denied.')
  useVisiblePolling(refreshInBackground, 15000)
  useEffect(() => {if (data && data.page !== page) setPage(data.page)}, [data, page])
  const otherCount = Math.max(0, (data?.total ?? 0) - Number(data?.password_session ?? false))

  async function changePassword(event: FormEvent) {
    event.preventDefault()
    if (pending || !data?.password_enabled) return
    setFormError(''); setNotice('')
    const chars = Array.from(newPassword).length
    if (!currentPassword) {setFormError('Enter your current password.'); return}
    if (chars < 12 || chars > 128 || new TextEncoder().encode(newPassword).length > 512) {
      setFormError('Use 12–128 characters and at most 512 UTF-8 bytes.'); return
    }
    if (newPassword !== confirmation) {setFormError('New passwords do not match.'); return}
    if (currentPassword === newPassword) {setFormError('Choose a password different from your current password.'); return}
    let result: AccountAction | null = null
    const success = await save(async () => {
      try {
        result = await api.changePassword(apiKey, currentPassword, newPassword)
      } catch (err) {
        if (err instanceof ApiError && err.status === 0) {
          throw new ApiError(0, 'Could not confirm the password change. Try signing in with the new password before submitting again.')
        }
        throw err
      }
      return {...data, password_enabled: true, sessions: [], total: 0, page: 1}
    })
    if (!success || !result) return
    setCurrentPassword(''); setNewPassword(''); setConfirmation('')
    if ((result as AccountAction).sign_in_required) onSignedOut('Password changed. Sign in again with your new password.')
    else {
      setNotice('Password changed. All password sessions are signed out. Your API key connection remains active.')
      void refreshInBackground()
    }
  }

  async function revoke(sessionId: number | 'others') {
    if (!data || pending) return
    const current = typeof sessionId === 'number' && data.sessions.some(s => s.id === sessionId && s.current)
    const prompt = sessionId === 'others'
      ? data.password_session ? 'Sign out all other password sessions?' : 'Sign out all password sessions? Your API key connection will remain active.'
      : current ? 'Sign out this session? You will need to sign in again.' : 'Sign out this password session?'
    if (!window.confirm(prompt)) return
    setNotice(''); setFormError('')
    let result: AccountAction | null = null
    const success = await save(async () => {
      result = sessionId === 'others' ? await api.revokeOtherSessions(apiKey) : await api.revokeOwnSession(apiKey, sessionId)
      const total = Math.max(0, data.total - (result.revoked_count ?? 0))
      return {...data, total, page: Math.min(data.page, Math.max(1, Math.ceil(total / size))),
        sessions: data.sessions.filter(s => sessionId === 'others' ? s.current : s.id !== sessionId)}
    })
    if (!success || !result) return
    if ((result as AccountAction).sign_in_required) onSignedOut('This session was signed out. Sign in again to continue.')
    else {setNotice(`Signed out ${(result as AccountAction).revoked_count ?? 0} password session(s).`); void refreshInBackground()}
  }

  return <PageFrame title="Account security" subtitle="Manage your password and active sign-ins."
    actions={<button type="button" className="btn-primary" disabled={pending} onClick={() => void refresh()}>Refresh sessions</button>}>
    <div className="max-w-5xl mx-auto p-4 sm:p-8 space-y-6">
      {error && <p role="alert" className="notice-error">{error}{stale && ' Previously loaded sessions may be out of date.'}</p>}
      {notice && <p role="status" className="notice-success">{notice}</p>}
      {!data && pending && <p role="status">Loading account security…</p>}
      {data && <>
        <section className="bg-white border rounded-xl p-5 space-y-4" aria-label="Change password">
          <h2 className="font-semibold">Change password</h2>
          {data.password_enabled ? <>
            <p className="text-sm text-slate-500">Changing your password signs out all password sessions, including this one when using password sign-in. API keys remain active.</p>
            <form aria-label="Change password" onSubmit={changePassword} noValidate className="space-y-4 max-w-lg">
              <label className="block text-sm">Current password<input type="password" autoComplete="current-password" required
                value={currentPassword} onChange={e => setCurrentPassword(e.target.value)} maxLength={256} disabled={pending}
                className="block border rounded-lg p-2 mt-1 w-full"/></label>
              <label className="block text-sm">New password<input type="password" autoComplete="new-password" required
                value={newPassword} onChange={e => setNewPassword(e.target.value)} maxLength={256} disabled={pending}
                className="block border rounded-lg p-2 mt-1 w-full"/></label>
              <label className="block text-sm">Confirm new password<input type="password" autoComplete="new-password" required
                value={confirmation} onChange={e => setConfirmation(e.target.value)} maxLength={256} disabled={pending}
                className="block border rounded-lg p-2 mt-1 w-full"/></label>
              <p className="text-xs text-slate-500">Use a unique password with 12–128 characters, up to 512 UTF-8 bytes.</p>
              {formError && <p role="alert" className="notice-error">{formError}</p>}
              <button type="submit" className="btn-primary" disabled={pending || !currentPassword || !newPassword || !confirmation}>Update password</button>
            </form>
          </> : <p className="text-sm text-slate-500">Password sign-in is not configured for this account. Ask your administrator to set an initial password.</p>}
        </section>
        <section className="bg-white border rounded-xl p-5 space-y-4" aria-label="Active sessions">
          <div className="flex flex-wrap gap-3 justify-between items-center"><h2 className="font-semibold">Active password sessions</h2>
            <button type="button" className="table-button" disabled={pending || otherCount === 0} onClick={() => void revoke('others')}>
              {data.password_session ? 'Sign out other sessions' : 'Sign out all password sessions'}</button></div>
          <p className="text-sm text-slate-500">Sessions are listed by creation and expiry time. Device names and locations are not recorded. API keys are managed separately.</p>
          <div className="overflow-x-auto"><table className="management-table" aria-label="Active password sessions">
            <thead><tr><th>Session</th><th>Started</th><th>Expires</th><th>Actions</th></tr></thead>
            <tbody>{data.sessions.map(session => <tr key={session.id}>
              <td>Session #{session.id}{session.current && <span className="block text-xs text-indigo-600">Current session</span>}</td>
              <td>{new Date(session.created_at).toLocaleString()}</td><td>{new Date(session.expires_at).toLocaleString()}</td>
              <td><button type="button" className="table-button" disabled={pending} aria-label={session.current ? 'Sign out current session' : `Sign out session ${session.id}`}
                onClick={() => void revoke(session.id)}>Sign out</button></td>
            </tr>)}</tbody></table></div>
          {data.sessions.length === 0 && <p className="text-sm text-slate-500">No active password sessions.</p>}
          <Pagination page={data.page} pageSize={size} total={data.total} disabled={pending}
            onPage={setPage} onPageSize={value => {setSize(value); setPage(1)}}/>
        </section>
      </>}
    </div>
  </PageFrame>
}
