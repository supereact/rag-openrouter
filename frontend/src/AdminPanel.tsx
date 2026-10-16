import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Activity, FileText, RefreshCw, Shield, UserCheck, UserMinus, UserPlus, Users } from 'lucide-react'
import { ApiError, api } from './api'
import { UsageSection } from './UsageSection'
import { BudgetSection } from './BudgetSection'
import FeedbackQualitySection from './FeedbackQualitySection'
import type { AdminInvitation, AdminUser, Role } from './types'
import { useAdminResource } from './useAdminResource'
import PageFrame from './PageFrame'
import Pagination from './Pagination'

interface Props { apiKey: string; onUnauthorized: () => void; selfUserId?: number }
function errorText(err: unknown) { return err instanceof Error ? err.message : 'Request failed' }
function authError(err: unknown, onUnauthorized: () => void) {
  if (err instanceof ApiError && err.status === 401) onUnauthorized()
}

export function DashboardPanel({ apiKey, onUnauthorized }: Props) {
  const loader = useCallback(() => api.adminDashboard(apiKey), [apiKey])
  const { data, error, loading, stale, updatedAt, refresh } = useAdminResource(loader, onUnauthorized)
  const tiles = [
    ['Users', data?.users_total ?? 0, Users],
    ['Active users', data?.users_active ?? 0, UserCheck],
    ['Documents', data?.documents_total ?? 0, FileText],
    ['Queued jobs', data?.jobs.queued ?? 0, Activity],
    ['Processing jobs', data?.jobs.processing ?? 0, Activity],
    ['Failed jobs', data?.jobs.failed ?? 0, Shield],
  ] as const
  return <PageFrame title="Admin Dashboard" subtitle="Statistics for your tenant only."
    actions={<button type="button" disabled={loading} onClick={() => void refresh()} className="btn-primary"><RefreshCw size={15}/> Refresh overview</button>}>
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      {loading && <p role="status">{data ? 'Refreshing overview…' : 'Loading overview…'}</p>}
      {error && <p role="alert" className="notice-error">{error}{stale && ' Previously loaded overview may be out of date.'}</p>}
      {updatedAt && <p className="text-xs text-slate-500">Overview last updated: {updatedAt.toLocaleTimeString()}</p>}
      {data && <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
        {tiles.map(([title, number, Icon]) => <div key={title} className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
          <div className="flex items-center gap-2 text-slate-500 text-sm"><Icon size={18}/>{title}</div>
          <p className="text-3xl font-semibold text-slate-900 mt-3">{number}</p>
        </div>)}
      </div>}
      <UsageSection apiKey={apiKey} onUnauthorized={onUnauthorized}/>
      <BudgetSection apiKey={apiKey} onUnauthorized={onUnauthorized}/>
      <FeedbackQualitySection apiKey={apiKey} onUnauthorized={onUnauthorized}/>
      {data && <div className="bg-white rounded-xl border border-slate-200 p-5">
        <h2 className="font-semibold text-slate-900 mb-3">Recent activity</h2>
        {data.recent_actions.length === 0 ? <p className="text-sm text-slate-500">No recent audit events.</p> :
        <div className="divide-y divide-slate-100">{data.recent_actions.map((action, i) =>
          <div key={i} className="py-3 text-sm flex flex-wrap justify-between gap-2">
            <span><b>{action.username}</b> · {action.action.replaceAll('_',' ')}</span>
            <span className="text-slate-500">{new Date(action.created_at).toLocaleString()}</span>
          </div>)}</div>}
      </div>}
    </div>
  </PageFrame>
}

export function UserManagementPanel({ apiKey, onUnauthorized, selfUserId }: Props) {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [invitations, setInvitations] = useState<AdminInvitation[]>([])
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<'reader' | 'editor'>('reader')
  const [newCode, setNewCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const reload = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const [rows, invites] = await Promise.all([api.adminUsers(apiKey), api.adminInvitations(apiKey)])
      setUsers(rows); setInvitations(invites)
    } catch (err) { authError(err, onUnauthorized); setError(errorText(err)) }
    finally { setLoading(false) }
  }, [apiKey, onUnauthorized])
  useEffect(() => { void reload() }, [reload])

  async function invite(event: FormEvent) {
    event.preventDefault(); setError(''); setNotice(''); setNewCode('')
    try {
      const response = await api.adminInvite(apiKey, email, role)
      setNewCode(response.invitation_code)
      setNotice(`Invitation created for ${response.email} (expires in ${response.expires_in_hours} hours). Copy the code now.`)
      setEmail(''); await reload()
    } catch (err) { authError(err, onUnauthorized); setError(errorText(err)) }
  }
  async function changeUser(user: AdminUser, next: {role?: Role; is_active?: boolean}) {
    setBusyId(user.id); setError(''); setNotice('')
    try {
      await api.adminUpdateUser(apiKey, user.id, next)
      setNotice(`Updated ${user.username}. Their browser sessions have been revoked.`)
      await reload()
    } catch (err) { authError(err, onUnauthorized); setError(errorText(err)) }
    finally { setBusyId(null) }
  }
  async function revoke(user: AdminUser) {
    setBusyId(user.id); setError('')
    try {
      await api.adminRevokeSessions(apiKey, user.id)
      setNotice(`Signed out all password sessions for ${user.username}.`)
    } catch (err) { authError(err, onUnauthorized); setError(errorText(err)) }
    finally { setBusyId(null) }
  }
  const [query, setQuery] = useState('')
  const [filterRole, setFilterRole] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const filtered = users.filter(user => `${user.username} ${user.email ?? ''}`.toLowerCase().includes(query.trim().toLowerCase()) &&
    (!filterRole || user.role === filterRole) && (!filterStatus || user.is_active === (filterStatus === 'active')))
  const currentPage = Math.min(page, Math.max(1, Math.ceil(filtered.length / pageSize)))
  const shown = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize)
  return <PageFrame title="User Management" subtitle="Invite colleagues and manage their access within your tenant."
    actions={<button type="button" className="btn-primary" disabled={loading} onClick={() => void reload()}><RefreshCw size={15}/> Refresh users</button>}>
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      {error && <p role="alert" className="notice-error">{error}</p>}
      {notice && <p role="status" className="notice-success">{notice}</p>}
      <section className="bg-white p-5 border border-slate-200 rounded-xl">
        <h2 className="font-semibold mb-3 flex gap-2 items-center"><UserPlus size={18}/> Create invitation</h2>
        <p className="text-sm text-slate-500 mb-4">Invite-only sign-up keeps tenant membership controlled. Invitations cannot create admins.</p>
        <form onSubmit={event => void invite(event)} className="flex flex-wrap gap-3 items-end">
          <label className="text-sm flex-1 min-w-52">Invitee email
            <input aria-label="Invitee email" type="email" required value={email} onChange={e => setEmail(e.target.value)} className="block w-full border border-slate-300 rounded-lg mt-1 p-2.5"/>
          </label>
          <label className="text-sm">Role
            <select aria-label="Invitation role" className="block border border-slate-300 rounded-lg mt-1 p-2.5" value={role} onChange={e => setRole(e.target.value as 'reader' | 'editor')}>
              <option value="reader">Reader</option><option value="editor">Editor</option>
            </select>
          </label>
          <button className="btn-primary" type="submit">Create invitation</button>
        </form>
        {newCode && <div className="mt-4 bg-indigo-50 border border-indigo-200 p-4 rounded-lg space-y-2">
          <p className="text-sm font-semibold">One-time signup code (visible only now)</p>
          <code className="text-xs break-all">{newCode}</code>
          <button type="button" onClick={() => void navigator.clipboard.writeText(newCode)} className="block text-sm text-indigo-700 font-medium">Copy code</button>
          <p className="text-xs text-slate-500">Share this securely with the invited user. Do not paste it into public channels.</p>
        </div>}
      </section>
      <section className="bg-white border border-slate-200 rounded-xl p-5">
        <h2 className="font-semibold mb-3">Users ({users.length})</h2>
        {loading && <p role="status">Loading users…</p>}
        <div className="flex flex-wrap gap-3 mb-4">
          <label className="text-sm flex-1 min-w-40">Search users<input aria-label="Search users" value={query} onChange={e => {setQuery(e.target.value); setPage(1)}} className="block border rounded-lg p-2 w-full mt-1"/></label>
          <label className="text-sm">Role<select aria-label="Filter user role" value={filterRole} onChange={e => {setFilterRole(e.target.value); setPage(1)}} className="block border rounded-lg p-2 mt-1">
            <option value="">All roles</option>{['reader','editor','admin'].map(role => <option key={role} value={role}>{role}</option>)}
          </select></label>
          <label className="text-sm">Status<select aria-label="Filter user status" value={filterStatus} onChange={e => {setFilterStatus(e.target.value); setPage(1)}} className="block border rounded-lg p-2 mt-1">
            <option value="">All statuses</option><option value="active">Active</option><option value="disabled">Disabled</option>
          </select></label>
        </div>
        <div className="overflow-x-auto"><table className="management-table" aria-label="Users"><thead><tr>
          {['Username','Email','Role','Status','Created','Actions'].map(title => <th key={title} scope="col">{title}</th>)}
        </tr></thead><tbody>{shown.map(user => <tr key={user.id}>
          <td className="font-semibold">{user.username}{user.id === selfUserId ? ' · You' : ''}</td>
          <td>{user.email || 'API-key-only user'}</td>
          <td><select aria-label={`Role for ${user.username}`} value={user.role} disabled={busyId === user.id || user.id === selfUserId}
              onChange={e => void changeUser(user, { role: e.target.value as Role })} className="border rounded-lg p-2 text-sm">
              <option value="reader">Reader</option><option value="editor">Editor</option><option value="admin">Admin</option>
            </select></td>
          <td>{user.is_active ? 'Active' : 'Disabled'}</td><td className="whitespace-nowrap">{new Date(user.created_at).toLocaleDateString()}</td>
          <td><div className="flex flex-wrap gap-2">
            <button type="button" disabled={busyId === user.id || user.id === selfUserId} onClick={() => void changeUser(user, {is_active: !user.is_active})}
              className="table-button text-sm flex gap-1 items-center">
              {user.is_active ? <><UserMinus size={14}/> Disable</> : <><UserCheck size={14}/> Enable</>}
            </button>
            <button type="button" disabled={busyId === user.id} onClick={() => void revoke(user)} className="text-sm text-indigo-700">Revoke sessions</button>
          </div></td>
        </tr>)}</tbody></table></div>
        {!loading && filtered.length === 0 && <p className="p-4 text-sm text-slate-500">No users match your filters.</p>}
        <Pagination page={currentPage} pageSize={pageSize} total={filtered.length} onPage={setPage} onPageSize={size => {setPageSize(size); setPage(1)}}/>
      </section>
      <section className="bg-white border border-slate-200 rounded-xl p-5">
        <h2 className="font-semibold mb-3">Recent invitations</h2>
        <div className="space-y-2">{invitations.map(inv => <div key={inv.id} className="text-sm flex justify-between gap-2 border-t border-slate-100 pt-2">
          <span>{inv.email} · {inv.role}</span>
          <span className="text-slate-500">{inv.used_at ? 'Used' : new Date(inv.expires_at).getTime() < Date.now() ? 'Expired' : 'Pending'}</span>
        </div>)}</div>
      </section>
    </div>
  </PageFrame>
}
