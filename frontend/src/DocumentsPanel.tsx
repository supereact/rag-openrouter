import { Fragment, useCallback, useEffect, useState } from 'react'
import { RefreshCw, Trash2 } from 'lucide-react'
import { api } from './api'
import type { Identity, LibraryRow } from './types'
import { navigate, useLocation } from './navigation'
import { useAdminResource } from './useAdminResource'
import PageFrame from './PageFrame'
import Pagination from './Pagination'
import DocumentAccessPanel from './DocumentAccessPanel'
import PdfViewer from './PdfViewer'
import DocumentUploads from './DocumentUploads'

export default function DocumentsPanel({ session, onUnauthorized }: {
  session: { key: string; identity: Identity }; onUnauthorized: () => void
}) {
  const location = useLocation()
  const params = new URLSearchParams(location.split('?')[1])
  const q = (params.get('q') ?? '').slice(0, 200)
  const status = ['indexed', 'queued', 'processing', 'failed'].includes(params.get('status') ?? '') ? params.get('status')! : ''
  const fileType = ['pdf', 'md', 'txt'].includes(params.get('file_type') ?? '') ? params.get('file_type')! : ''
  const page = Math.max(1, Math.min(2147483647, Math.floor(Number(params.get('page')) || 1)))
  const pageSize = [20, 50, 100].includes(Number(params.get('page_size'))) ? Number(params.get('page_size')) : 20
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (q) query.set('q', q)
  if (status) query.set('status', status)
  if (fileType) query.set('file_type', fileType)
  const queryString = query.toString()
  const loader = useCallback((signal?: AbortSignal) => api.library(session.key, new URLSearchParams(queryString), signal), [session.key, queryString])
  const { data, error, loading, pending, stale, refresh, refreshInBackground, save } = useAdminResource(loader, onUnauthorized, 'Access denied. You cannot view this library.')
  const [notice, setNotice] = useState('')
  const [inputError, setInputError] = useState('')
  const [sharingId, setSharingId] = useState<string | null>(null)
  const [pdf, setPdf] = useState<LibraryRow | null>(null)
  const closePdf = useCallback(() => setPdf(null), [])
  const writable = session.identity.role !== 'reader'

  useEffect(() => {
    const poll = () => {
      if (document.visibilityState !== 'hidden' && navigator.onLine !== false) void refreshInBackground()
    }
    const interval = window.setInterval(poll, 3500)
    document.addEventListener('visibilitychange', poll)
    window.addEventListener('online', poll)
    return () => {
      window.clearInterval(interval)
      document.removeEventListener('visibilitychange', poll)
      window.removeEventListener('online', poll)
    }
  }, [refreshInBackground])
  useEffect(() => { setSharingId(null) }, [queryString])
  useEffect(() => {
    if (data && data.page !== page) {
      const next = new URLSearchParams(queryString)
      next.set('page', String(data.page))
      navigate(`/documents?${next}`, true)
    }
  }, [data, page, queryString])

  function update(values: Record<string, string>, reset = true) {
    const next = new URLSearchParams(queryString)
    for (const [key, value] of Object.entries(values)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    if (reset) next.set('page', '1')
    navigate(`/documents?${next}`)
  }
  async function remove(row: LibraryRow) {
    if (pending || !row.can_manage) return
    const question = row.kind === 'document'
      ? `Delete "${row.title}" and its indexed chunks? This cannot be undone.`
      : `Remove failed upload "${row.title}" and its staged input? This will not delete indexed documents.`
    if (!window.confirm(question)) return
    setNotice('')
    const ok = await save(async () => {
      if (row.kind === 'document') await api.remove(session.key, Number(row.id))
      else await api.removeJob(session.key, row.id)
      return loader()
    })
    if (ok) setNotice(`Removed ${row.title}.`)
  }
  async function reindex(row: LibraryRow, file: File | undefined) {
    if (!file || pending) return
    setInputError('')
    if (file.name !== row.title) { setInputError('The PDF filename must match the existing document title exactly.'); return }
    const ok = await save(async () => { await api.reindex(session.key, Number(row.id), file); return loader() })
    if (ok) setNotice(`Reindexed ${row.title}.`)
  }
  return <PageFrame title="Documents" subtitle="Only documents and uploads authorized for your account appear here."
    actions={<button type="button" disabled={pending} onClick={() => void refresh()} className="btn-primary"><RefreshCw size={15}/> Refresh documents</button>}>
    <div className="max-w-6xl px-4 sm:px-8 py-7 mx-auto space-y-5">
      {writable && <DocumentUploads key={`${session.key}:${session.identity.user_id}`} apiKey={session.key} disabled={pending}
        onUnauthorized={onUnauthorized} onQueued={() => {void refreshInBackground()}}/>}
      {(error || inputError) && <p role="alert" className="notice-error">{inputError || error}{stale && ' Previously loaded documents may be out of date.'}</p>}
      {notice && <p role="status" className="notice-success">{notice}</p>}
      <div className="flex flex-wrap gap-3">
        <label className="text-sm flex-1 min-w-40">Search documents<input aria-label="Filter documents" maxLength={200} type="search" value={q} onChange={e => update({q: e.target.value})}
          className="block w-full border rounded-lg p-2 mt-1" placeholder="Title or filename…"/></label>
        <label className="text-sm">Status<select aria-label="Document status" value={status} onChange={e => update({status: e.target.value})} className="block border rounded-lg p-2 mt-1">
          <option value="">All statuses</option>{['indexed', 'queued', 'processing', 'failed'].map(s => <option key={s} value={s}>{s}</option>)}
        </select></label>
        <label className="text-sm">File type<select aria-label="File type" value={fileType} onChange={e => update({file_type: e.target.value})} className="block border rounded-lg p-2 mt-1">
          <option value="">All types</option>{['pdf', 'md', 'txt'].map(s => <option key={s} value={s}>{s.toUpperCase()}</option>)}
        </select></label>
      </div>
      <p role="status" className="min-h-6 text-sm text-slate-500">
        {pending ? loading ? data ? 'Refreshing documents…' : 'Loading documents…' : 'Updating library…' : 'Documents update automatically.'}
      </p>
      <div className="border border-slate-200 rounded-xl bg-white overflow-x-auto">
        <table className="management-table" aria-label="Document library"><thead><tr>{['Title', 'Date', 'Status', 'Assigned', 'Remove'].map(title => <th key={title} scope="col">{title}</th>)}</tr></thead>
          <tbody>{data?.items.map(row => <Fragment key={`${row.kind}:${row.id}`}><tr>
            <td className="min-w-52 max-w-96"><span className="font-semibold break-words">{row.title}</span>
              {row.kind === 'document' && row.title.toLowerCase().endsWith('.pdf') && <div className="mt-2 space-y-2">
                <button type="button" aria-label={`View PDF ${row.title}`} className="block text-xs text-indigo-700" onClick={() => setPdf(row)}>View original PDF</button>
                {row.can_manage && <label className="block text-xs text-indigo-700 cursor-pointer">Replace PDF / reindex<input aria-label={`Reindex ${row.title}`} type="file" accept=".pdf" className="sr-only" disabled={pending}
                  onChange={e => { void reindex(row, e.target.files?.[0]); e.target.value = '' }}/></label>}
              </div>}
            </td><td className="whitespace-nowrap">{new Date(row.created_at).toLocaleDateString()}</td>
            <td><span aria-label={`${row.title}: ${row.status}`}>{row.status}</span>{row.error && <p className="text-xs text-rose-700 mt-1 max-w-64">{row.error}</p>}</td>
            <td className="min-w-44">{row.kind === 'upload' ? <span className="text-slate-500">Available after indexing</span> : row.assigned_users === null ? 'Authorized access' : <>
              <p className="break-words">{row.assigned_users.map(u => u.username).join(', ') || 'Private'}</p>
              {row.can_manage && <button type="button" className="text-xs text-indigo-700 mt-2" aria-label={`Manage access for ${row.title}`} onClick={() => setSharingId(v => v === row.id ? null : row.id)}>Manage access</button>}
            </>}</td><td>{row.can_manage && <button type="button" className="table-button text-rose-700" aria-label={row.kind === 'document' ? `Delete ${row.title}` : `Remove failed upload ${row.title}`}
              disabled={pending || (row.kind === 'upload' && row.status !== 'failed')} onClick={() => void remove(row)}><Trash2 size={16}/></button>}</td>
          </tr>{row.kind === 'document' && row.can_manage && sharingId === row.id && <tr><td colSpan={5}>
            <DocumentAccessPanel apiKey={session.key} documentId={Number(row.id)} title={row.title} onUnauthorized={onUnauthorized}
              onCancel={() => setSharingId(null)} onSaved={() => { setSharingId(null); setNotice(`Updated access for ${row.title}.`); void refresh() }}/>
          </td></tr>}</Fragment>)}</tbody>
        </table>
        {data?.items.length === 0 && <p className="p-8 text-sm text-slate-500">No visible documents match your search.</p>}
      </div>
      {data && <Pagination page={data.page} pageSize={pageSize} total={data.total} disabled={pending}
        onPage={next => update({page: String(next)}, false)} onPageSize={next => update({page_size: String(next)})}/>}
    </div>
    {pdf && <PdfViewer apiKey={session.key} documentId={Number(pdf.id)} title={pdf.title} page={1} onClose={closePdf} onUnauthorized={onUnauthorized}/>}
  </PageFrame>
}
