import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { RefreshCw } from 'lucide-react'
import { api } from './api'
import type { AuditLog } from './types'
import { navigate, useLocation } from './navigation'
import { useAdminResource } from './useAdminResource'
import PageFrame from './PageFrame'
import Pagination from './Pagination'

interface Filters { action: string; user_id: string; date_from: string; date_to: string }
function filtersFrom(search: string): Filters {
  const query = new URLSearchParams(search)
  return {action: query.get('action') ?? '', user_id: query.get('user_id') ?? '',
    date_from: query.get('date_from') ?? '', date_to: query.get('date_to') ?? ''}
}

export default function AuditLogPanel({apiKey, onUnauthorized}: {apiKey: string; onUnauthorized: () => void}) {
  const location = useLocation()
  const search = location.split('?')[1] ?? ''
  const params = new URLSearchParams(search)
  const page = Math.max(1, Math.floor(Number(params.get('page')) || 1))
  const pageSize = [20,50,100].includes(Number(params.get('page_size'))) ? Number(params.get('page_size')) : 20
  const query = new URLSearchParams({page: String(page), page_size: String(pageSize)})
  const applied = filtersFrom(search)
  for (const [name,value] of Object.entries(applied)) if (value) query.set(name,value)
  const queryString = query.toString()
  const loader = useCallback((signal?: AbortSignal) => api.adminAuditLog(apiKey, new URLSearchParams(queryString), signal), [apiKey,queryString])
  const {data,error,loading,stale,refresh} = useAdminResource(loader,onUnauthorized)
  const [draft,setDraft] = useState<Filters>(() => filtersFrom(search))
  const [options,setOptions] = useState<{key: string; actions: AuditLog['actions']; users: AuditLog['users']}>({key:apiKey,actions:[],users:[]})
  useEffect(() => {setDraft(filtersFrom(search))},[search])
  useEffect(() => {if (data) setOptions({key:apiKey,actions:data.actions,users:data.users})},[data,apiKey])
  useEffect(() => {
    if (data && data.page !== page) {
      const next = new URLSearchParams(queryString)
      next.set('page',String(data.page)); navigate(`/audit-log?${next}`,true)
    }
  },[data,page,queryString])
  function update(values: Record<string,string>, reset = false) {
    const next = new URLSearchParams(queryString)
    for (const [name,value] of Object.entries(values)) {if (value) next.set(name,value); else next.delete(name)}
    if (reset) next.set('page','1')
    navigate(`/audit-log?${next}`)
  }
  function apply(event: FormEvent) {event.preventDefault(); update({...draft},true)}
  const actions = data?.actions ?? (options.key === apiKey && !error ? options.actions : [])
  const users = data?.users ?? (options.key === apiKey && !error ? options.users : [])
  return <PageFrame title="Audit Log" subtitle="Recorded activity within your tenant. All date filters use UTC."
    actions={<button type="button" className="btn-primary" disabled={loading} onClick={() => void refresh()}><RefreshCw size={15}/> Refresh audit log</button>}>
    <div className="max-w-6xl mx-auto p-4 sm:p-6 space-y-5">
      <form onSubmit={apply} className="bg-white border rounded-xl p-4 flex flex-wrap gap-3 items-end">
        <label className="text-sm">User<select aria-label="Audit user" value={draft.user_id} onChange={e => setDraft({...draft,user_id:e.target.value})} className="block border rounded-lg p-2 mt-1 max-w-60">
          <option value="">All users</option>
          {draft.user_id && !users.some(u => String(u.id) === draft.user_id) && <option value={draft.user_id}>User #{draft.user_id}</option>}
          {users.map(user => <option key={user.id} value={user.id}>{user.username}</option>)}
        </select></label>
        <label className="text-sm">Action<select aria-label="Audit action" value={draft.action} onChange={e => setDraft({...draft,action:e.target.value})} className="block border rounded-lg p-2 mt-1 max-w-60">
          <option value="">All actions</option>
          {draft.action && !actions.includes(draft.action) && <option value={draft.action}>{draft.action}</option>}
          {actions.map(action => <option key={action} value={action}>{action}</option>)}
        </select></label>
        <label className="text-sm">From (UTC)<input aria-label="Audit start date" type="date" value={draft.date_from} max={draft.date_to || undefined}
          onChange={e => setDraft({...draft,date_from:e.target.value})} className="block border rounded-lg p-2 mt-1"/></label>
        <label className="text-sm">To (UTC)<input aria-label="Audit end date" type="date" value={draft.date_to} min={draft.date_from || undefined}
          onChange={e => setDraft({...draft,date_to:e.target.value})} className="block border rounded-lg p-2 mt-1"/></label>
        <button type="submit" className="btn-primary" disabled={loading}>Apply filters</button>
        <button type="button" className="table-button" onClick={() => {setDraft({action:'',user_id:'',date_from:'',date_to:''}); update({action:'',user_id:'',date_from:'',date_to:''},true)}}>Reset filters</button>
      </form>
      {error && <p role="alert" className="notice-error">{error}{stale && ' Previously loaded events may be out of date.'}</p>}
      <p role="status" className="min-h-6 text-sm text-slate-500">{loading ? data ? 'Refreshing audit log…' : 'Loading audit log…' : `${data?.total ?? 0} recorded events`}</p>
      <div className="bg-white border rounded-xl overflow-x-auto"><table className="management-table" aria-label="Audit events"><thead><tr>
        {['Date (UTC)','User','Action','Document','Results'].map(label => <th scope="col" key={label}>{label}</th>)}
      </tr></thead><tbody>{data?.items.map(item => <tr key={item.id}>
        <td className="whitespace-nowrap">{new Date(item.created_at).toLocaleString(undefined,{timeZone:'UTC'})}</td>
        <td>{item.username}</td><td className="break-words">{item.action}</td>
        <td className="min-w-40 max-w-80 break-words">{item.document_id === null ? '—' : `${item.document_title ?? 'Deleted or unavailable document'} (#${item.document_id})`}</td>
        <td>{item.result_count ?? '—'}</td>
      </tr>)}</tbody></table>
        {data?.items.length === 0 && <p className="p-8 text-sm text-slate-500">No audit events match these filters.</p>}
      </div>
      {data && <Pagination page={data.page} pageSize={pageSize} total={data.total} disabled={loading}
        onPage={value => update({page:String(value)})} onPageSize={value => update({page_size:String(value)},true)}/>}
    </div>
  </PageFrame>
}
