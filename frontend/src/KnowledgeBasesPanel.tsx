import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { BookOpen, FolderPlus, Plus, Trash2, X } from 'lucide-react'
import { ApiError, api } from './api'
import PageFrame from './PageFrame'
import type { DocumentRecord, Identity, KnowledgeBase } from './types'

interface Props {
  session: { key: string; identity: Identity }
  onUnauthorized: () => void
}

export default function KnowledgeBasesPanel({ session, onUnauthorized }: Props) {
  const [bases, setBases] = useState<KnowledgeBase[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [members, setMembers] = useState<DocumentRecord[]>([])
  const [available, setAvailable] = useState<DocumentRecord[]>([])
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [documentToAdd, setDocumentToAdd] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)
  const [error, setError] = useState('')
  const editable = session.identity.role === 'admin' || session.identity.role === 'editor'
  const selected = bases.find(item => item.id === selectedId)
  const canManage = selected?.can_manage ?? false

  const handleError = useCallback((err: unknown) => {
    if (err instanceof ApiError && err.status === 401) onUnauthorized()
    else setError(err instanceof Error ? err.message : 'Request failed')
  }, [onUnauthorized])

  const refresh = useCallback(async () => {
    const [all, docs] = await Promise.all([
      api.knowledgeBases(session.key), api.documents(session.key),
    ])
    setBases(all)
    setAvailable(docs)
    setSelectedId(old => old !== null && all.some(item => item.id === old)
      ? old : (all[0]?.id ?? null))
    window.dispatchEvent(new Event('knowledge-bases-updated'))
  }, [session.key])

  useEffect(() => {
    let alive = true
    Promise.all([api.knowledgeBases(session.key), api.documents(session.key)])
      .then(([items, docs]) => {
        if (!alive) return
        setBases(items); setAvailable(docs)
        setSelectedId(items[0]?.id ?? null)
      })
      .catch(err => { if (alive) handleError(err) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [session.key, handleError])

  useEffect(() => {
    let alive = true
    if (selectedId === null) { setMembers([]); return }
    api.knowledgeBaseDocuments(session.key, selectedId)
      .then(items => { if (alive) setMembers(items) })
      .catch(err => { if (alive) handleError(err) })
    return () => { alive = false }
  }, [selectedId, session.key, handleError, revision])

  async function perform(operation: () => Promise<void>) {
    if (busy) return
    setError(''); setBusy(true)
    try {
      await operation()
      await refresh()
      setRevision(r => r + 1)
    } catch (err) { handleError(err) }
    finally { setBusy(false) }
  }

  function create(event: FormEvent) {
    event.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) return
    void perform(async () => {
      const created = await api.createKnowledgeBase(session.key, trimmed, description.trim())
      setName(''); setDescription('')
      setSelectedId(created.id)
      setMembers([])
    })
  }

  function rename() {
    if (!selected || !canManage) return
    const next = window.prompt('Knowledge base name', selected.name)?.trim()
    if (!next) return
    void perform(async () => { await api.renameKnowledgeBase(session.key, selected.id, next, selected.description) })
  }

  function remove() {
    if (!selected || !canManage || !window.confirm(`Delete collection “${selected.name}”? Documents will not be deleted.`)) return
    void perform(async () => {
      await api.deleteKnowledgeBase(session.key, selected.id)
      setSelectedId(null); setMembers([])
    })
  }

  function add(event: FormEvent) {
    event.preventDefault()
    if (!selected || !canManage || !documentToAdd) return
    const documentId = Number(documentToAdd)
    void perform(async () => {
      await api.addKnowledgeBaseDocument(session.key, selected.id, documentId)
      setDocumentToAdd('')
    })
  }

  function removeMember(documentId: number) {
    if (!selected || !canManage) return
    void perform(async () => {
      await api.removeKnowledgeBaseDocument(session.key, selected.id, documentId)
    })
  }

  const memberIds = new Set(members.map(item => item.id))
  const options = available.filter(doc => !memberIds.has(doc.id) &&
    (session.identity.role === 'admin' || doc.owner_user_id === session.identity.user_id))

  return <PageFrame title="Knowledge Bases" subtitle="Group documents and select a knowledge base in chat. Document permissions always apply.">
    <div className="max-w-5xl mx-auto min-w-0 space-y-6 px-5 sm:px-8 py-7">
      {error && <div role="alert" className="notice-error flex justify-between">{error}
        <button aria-label="Dismiss error" type="button" onClick={() => setError('')}><X size={17}/></button></div>}
      {editable && <form onSubmit={create} className="bg-white border border-slate-200 rounded-xl p-5 space-y-3">
        <h2 className="font-semibold">Create knowledge base</h2>
        <div className="flex flex-wrap gap-2">
          <input aria-label="Knowledge base name" placeholder="e.g. IT Support" maxLength={120} required value={name}
            onChange={e => setName(e.target.value)} className="border border-slate-300 rounded-lg px-3 py-2 flex-1 min-w-40"/>
          <input aria-label="Knowledge base description" placeholder="Optional description" maxLength={500} value={description}
            onChange={e => setDescription(e.target.value)} className="border border-slate-300 rounded-lg px-3 py-2 flex-1 min-w-40"/>
          <button className="btn-primary" type="submit" disabled={busy || !name.trim()}><FolderPlus size={16}/> Create</button>
        </div>
      </form>}
      <div className="grid min-w-0 grid-cols-1 lg:grid-cols-3 gap-5">
        <section className="min-w-0 border border-slate-200 bg-white rounded-xl p-4 space-y-2" aria-label="Available knowledge bases">
          <h2 className="font-semibold mb-3">Collections</h2>
          {loading && <p className="text-sm text-slate-500">Loading…</p>}
          {!loading && bases.length === 0 && <p className="text-sm text-slate-500">No knowledge bases available.</p>}
          {bases.map(base => <button key={base.id} type="button" onClick={() => setSelectedId(base.id)}
            aria-current={base.id === selectedId ? 'true' : undefined}
            className={`w-full text-left p-3 rounded-lg text-sm ${base.id === selectedId ? 'bg-indigo-50 text-indigo-800' : 'hover:bg-slate-50 text-slate-700'}`}>
            <span className="font-semibold block">{base.name}</span>
            <span className="text-xs text-slate-500">{base.document_count} accessible documents</span>
          </button>)}
        </section>
        <section className="min-w-0 lg:col-span-2 border border-slate-200 bg-white rounded-xl p-5 space-y-4" aria-label="Knowledge base documents">
          {selected ? <>
            <div className="flex min-w-0 flex-wrap justify-between items-start gap-3">
              <div className="min-w-0 flex-1"><h2 className="font-semibold text-lg break-words">{selected.name}</h2>
                <p className="text-sm text-slate-500 break-words">{selected.description || 'No description'}</p></div>
              {canManage && <div className="flex flex-none gap-2">
                <button type="button" disabled={busy} className="text-xs border rounded-lg px-3 py-2" onClick={rename}>Rename</button>
                <button type="button" disabled={busy} className="text-xs border rounded-lg px-3 py-2 text-rose-600" onClick={remove}><Trash2 size={13}/></button>
              </div>}
            </div>
            {canManage && <form onSubmit={add} className="grid min-w-0 w-full grid-cols-1 gap-2">
              <label htmlFor="kb-document-to-add" className="text-sm font-medium text-slate-700">Add an existing document</label>
              <select id="kb-document-to-add" aria-label="Document to add" value={documentToAdd} onChange={e => setDocumentToAdd(e.target.value)}
                className="block box-border w-full min-w-0 max-w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                disabled={busy}>
                <option value="">Choose a document you can manage</option>
                {options.map(doc => <option key={doc.id} value={doc.id}>{doc.title} (#{doc.id})</option>)}
              </select>
              <button type="submit" disabled={busy || !documentToAdd} className="btn-primary w-fit max-w-full"><Plus size={15}/> Add document</button>
            </form>}
            <div className="divide-y divide-slate-100">
              {members.length === 0 && <p className="text-sm text-slate-500 py-3">No accessible documents in this collection.</p>}
              {members.map(doc => <div key={doc.id} className="flex justify-between items-center gap-2 py-3 text-sm">
                <div className="flex items-center gap-2 min-w-0"><BookOpen size={16} className="text-indigo-500"/>
                  <span className="truncate">{doc.title}</span></div>
                {canManage && (session.identity.role === 'admin' || doc.owner_user_id === session.identity.user_id) &&
                  <button type="button" disabled={busy} className="text-rose-600 text-xs" onClick={() => removeMember(doc.id)}>Remove</button>}
              </div>)}
            </div>
          </> : <p className="text-sm text-slate-500">Select a knowledge base to view its documents.</p>}
        </section>
      </div>
    </div>
  </PageFrame>
}
