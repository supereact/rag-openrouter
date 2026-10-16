import { useCallback, useState, type FormEvent } from 'react'
import { Search } from 'lucide-react'
import { api } from './api'
import { useAdminResource } from './useAdminResource'

interface Props {
  apiKey: string
  documentId: number
  title: string
  onUnauthorized: () => void
  onSaved: () => void
  onCancel: () => void
}

export default function DocumentAccessPanel(props: Props) {
  // Each document/session owns its draft; late requests cannot update a new editor.
  return <AccessEditor key={`${props.apiKey}:${props.documentId}`} {...props}/>
}

function AccessEditor({apiKey, documentId, title, onUnauthorized, onSaved, onCancel}: Props) {
  const loader = useCallback(() => api.documentAccess(apiKey, documentId), [apiKey, documentId])
  const { data, error, loading, saving, pending, refresh, save } = useAdminResource(
    loader, onUnauthorized, 'Access denied. You cannot manage access to this document.',
  )
  const [search, setSearch] = useState('')
  const [selection, setSelection] = useState<Set<number> | null>(null)
  const selected = selection ?? new Set(data?.users.filter(u => u.shared || u.automatic_access).map(u => u.id))
  const editable = data?.users.filter(u => !u.automatic_access) ?? []
  const grants = editable.filter(u => selected.has(u.id) && !u.shared).map(u => u.id)
  const revokes = editable.filter(u => !selected.has(u.id) && u.shared).map(u => u.id)
  const changed = grants.length + revokes.length > 0
  const query = search.trim().toLowerCase()
  const users = data?.users.filter(u => `${u.username} ${u.email ?? ''}`.toLowerCase().includes(query)) ?? []

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!data || pending || !changed) return
    if (await save(() => api.updateDocumentAccess(apiKey, documentId, {
      grant_user_ids: grants, revoke_user_ids: revokes,
    }))) onSaved()
  }

  return <section aria-label={`Manage access for ${title}`} className="mt-4 border-t border-slate-100 pt-4 space-y-3">
    <div><h4 className="font-semibold text-sm text-slate-900">Manage access</h4>
      <p className="text-xs text-slate-500 mt-1">Select people in your workspace. The owner and tenant admins have automatic access while their accounts are active.</p></div>
    {loading && <p role="status" className="text-sm text-slate-500">Loading document access…</p>}
    {error && <p role="alert" className="notice-error">{error}</p>}
    {!data && error && <button type="button" disabled={pending} onClick={() => {
      setSelection(null); void refresh()
    }} className="text-sm text-indigo-700 underline">Retry loading access</button>}
    <form onSubmit={event => void submit(event)} className="space-y-3">
      {data && <>
        <div className="relative"><Search size={15} className="absolute top-3 left-3 text-slate-400"/>
          <input aria-label="Search users to share with" value={search} disabled={saving} onChange={e => setSearch(e.target.value)}
            placeholder="Search by username or email…" className="w-full border border-slate-300 rounded-lg py-2 pl-9 pr-3 text-sm"/></div>
        <div className="max-h-64 overflow-y-auto rounded-lg border border-slate-200 divide-y divide-slate-100">
          {users.length === 0 && <p className="p-3 text-sm text-slate-500">No users match your search.</p>}
          {users.map(user => <label key={user.id} className="flex items-center gap-3 p-3 text-sm">
            <input type="checkbox" aria-label={`Access for ${user.username}`} checked={selected.has(user.id)}
              disabled={saving || !!user.automatic_access || (!user.is_active && !user.shared)}
              onChange={e => {
                const next = new Set(selected)
                if (e.target.checked) next.add(user.id)
                else next.delete(user.id)
                setSelection(next)
              }}/>
            <span className="min-w-0 flex-1"><span className="block font-medium break-all">{user.username}</span>
              {user.email && <span className="block text-xs text-slate-500 break-all">{user.email}</span>}</span>
            <span className="text-xs text-slate-500 shrink-0">
              {user.automatic_access === 'owner' ? 'Owner' : user.automatic_access === 'admin' ? 'Admin' : ''}
              {!user.is_active && ' · Inactive'}
            </span>
          </label>)}
        </div>
        <p className="text-xs text-slate-500">{editable.filter(u => selected.has(u.id)).length} people selected for shared access. Unchecking someone removes their explicit access when saved.</p>
      </>}
      {saving && <p role="status" className="text-sm text-slate-500">Saving document access…</p>}
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={pending || !data || !changed} className="btn-primary !px-3 !py-2">Save changes</button>
        <button type="button" disabled={saving} onClick={onCancel} className="border border-slate-300 rounded-lg px-3 py-2 text-sm">Cancel</button>
      </div>
    </form>
  </section>
}
