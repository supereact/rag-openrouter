import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import {
  ArrowRight, BookOpen, Check, ChevronDown, ChevronRight, Copy,
  FilePlus2, FileText, FolderOpen, KeyRound, Layers, LogOut, LockKeyhole,
  Menu, MessageSquareText, Search, Send, ShieldCheck, Trash2, UploadCloud,
  Users, X, LayoutDashboard, UserCog, Plus, Pencil, ThumbsUp, ThumbsDown,
} from 'lucide-react'
import { ApiError, api } from './api'
import type { ChatEntry, DocumentRecord, Identity, IngestionJob, SearchHit, SavedConversation, KnowledgeBase, AnswerFeedback, FeedbackReason } from './types'
import MarkdownAnswer from './MarkdownAnswer'
import PdfViewer from './PdfViewer'
import { DashboardPanel, UserManagementPanel } from './AdminPanel'
import KnowledgeBasesPanel from './KnowledgeBasesPanel'

interface Session { key: string; identity: Identity }
type Tab = 'chat' | 'documents' | 'dashboard' | 'users' | 'knowledge-bases'
const commonQuestions = [
  'What are the phases of incident response?',
  'How do I troubleshoot VPN connection issues?',
  'What is the database backup procedure?',
]

function describeError(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.'
}

function Brand({ compact = false }: { compact?: boolean }) {
  return <div className="flex items-center gap-3">
    <div className="brand-mark"><Layers size={19} strokeWidth={2.3} /></div>
    {!compact && <div><div className="font-bold tracking-tight text-white leading-tight">KnowledgeBase</div>
      <div className="text-[11px] tracking-[.14em] uppercase text-slate-400 mt-0.5">Enterprise RAG</div></div>}
  </div>
}

function SignIn({ onLogin }: { onLogin: (key: string) => Promise<void> }) {
  const [mode, setMode] = useState<'key' | 'password' | 'register'>('password')
  const [key, setKey] = useState('')
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [invitation, setInvitation] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    setBusy(true); setError('')
    try {
      if (mode === 'key') await onLogin(key.trim())
      else if (mode === 'password') {
        const result = await api.loginPassword(email, password)
        await onLogin(result.access_token)
      } else {
        if (password !== confirmPassword) throw new Error('Passwords do not match')
        const result = await api.register(invitation, email, username, password)
        await onLogin(result.access_token)
      }
    } catch (err) { setError(describeError(err)) }
    finally { setBusy(false) }
  }

  return <div className="min-h-screen bg-[#080f1e] flex flex-col">
    <div className="p-7 sm:p-10"><Brand /></div>
    <div className="flex-1 flex items-center justify-center p-5">
      <div className="w-full max-w-[460px] rounded-2xl border border-white/10 bg-white/[.045] p-7 sm:p-9 shadow-2xl">
        <div className="w-12 h-12 grid place-items-center rounded-xl bg-indigo-500/15 text-indigo-300 mb-5"><LockKeyhole size={22}/></div>
        <h1 className="text-[27px] text-white font-semibold tracking-tight">Welcome to KnowledgeBase</h1>
        <p className="mt-2 text-slate-400 text-sm leading-relaxed">Sign in to your authorized workspace, or register with an invitation.</p>
        <div className="flex flex-wrap gap-2 mt-5" role="group" aria-label="Authentication method">
          <button type="button" className={`text-xs px-3 py-2 rounded-lg ${mode === 'password' ? 'bg-indigo-600 text-white' : 'bg-slate-800 text-slate-300'}`} onClick={() => {setMode('password');setError('')}}>Email sign in</button>
          <button type="button" className={`text-xs px-3 py-2 rounded-lg ${mode === 'register' ? 'bg-indigo-600 text-white' : 'bg-slate-800 text-slate-300'}`} onClick={() => {setMode('register');setError('')}}>Sign up</button>
          <button type="button" className={`text-xs px-3 py-2 rounded-lg ${mode === 'key' ? 'bg-indigo-600 text-white' : 'bg-slate-800 text-slate-300'}`} onClick={() => {setMode('key');setError('')}}>API key</button>
        </div>
        <form onSubmit={submit} className="mt-6 space-y-4">
          {mode === 'key' ? <>
            <label className="block text-sm font-medium text-slate-200" htmlFor="api-key">API key</label>
            <div className="relative">
              <KeyRound size={17} className="absolute left-3.5 top-3.5 text-slate-400"/>
              <input id="api-key" autoComplete="off" spellCheck={false} type={showKey ? 'text' : 'password'} required
                value={key} onChange={event => setKey(event.target.value)} placeholder="rag_••••••••••••••••••"
                className="w-full rounded-xl border border-slate-600/80 bg-slate-900 px-11 py-3 text-white placeholder:text-slate-600 focus:outline-none focus:border-indigo-400" />
              <button className="absolute right-3 top-3 text-xs text-indigo-300 hover:text-indigo-200" type="button" onClick={() => setShowKey(v => !v)}>{showKey ? 'Hide' : 'Show'}</button>
            </div>
          </> : <>
            {mode === 'register' && <><label className="block text-sm text-slate-200" htmlFor="invitation-code">Invitation code</label>
              <input id="invitation-code" value={invitation} onChange={e => setInvitation(e.target.value)} required autoComplete="off" placeholder="invite_…" className="w-full rounded-lg border border-slate-600 bg-slate-900 p-3 text-white"/>
              <label className="block text-sm text-slate-200" htmlFor="signup-username">Username</label>
              <input id="signup-username" value={username} onChange={e => setUsername(e.target.value)} required minLength={2} maxLength={80} className="w-full rounded-lg border border-slate-600 bg-slate-900 p-3 text-white"/>
            </>}
            <label className="block text-sm text-slate-200" htmlFor="account-email">Email address</label>
            <input id="account-email" type="email" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} required className="w-full rounded-lg border border-slate-600 bg-slate-900 p-3 text-white"/>
            <label className="block text-sm text-slate-200" htmlFor="account-password">Password</label>
            <input id="account-password" type="password" autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
              value={password} onChange={e => setPassword(e.target.value)} required minLength={mode === 'register' ? 12 : 1}
              className="w-full rounded-lg border border-slate-600 bg-slate-900 p-3 text-white"/>
            {mode === 'register' && <>
              <label className="block text-sm text-slate-200" htmlFor="confirm-password">Confirm password</label>
              <input id="confirm-password" type="password" autoComplete="new-password" value={confirmPassword}
                onChange={e => setConfirmPassword(e.target.value)} required minLength={12}
                className="w-full rounded-lg border border-slate-600 bg-slate-900 p-3 text-white"/>
              <p className="text-xs text-slate-400">Use a unique password of at least 12 characters. Your administrator supplies the invitation code.</p>
            </>}
          </>}
          {error && <p role="alert" className="text-rose-300 text-sm">{error}</p>}
          <button disabled={busy || (mode === 'key' ? !key.trim() : !email.trim() || !password.trim())} className="btn-primary w-full justify-center" type="submit">
            {busy ? 'Authenticating…' : mode === 'register' ? 'Create account' : mode === 'password' ? 'Sign in' : 'Connect to workspace'} <ArrowRight size={17}/>
          </button>
        </form>
        <div className="mt-7 pt-5 border-t border-white/10 flex gap-3 items-start text-slate-400 text-xs leading-5">
          <ShieldCheck size={18} className="shrink-0 text-teal-300"/>
          Credentials are sent to your local FastAPI service. Access tokens are kept in this tab's memory and cleared on refresh or sign out.
        </div>
      </div>
    </div>
  </div>
}

function SourceList({ sources, entryId, onOpenPdf }: {
  sources: SearchHit[]; entryId: number; onOpenPdf: (source: SearchHit) => void
}) {
  const [expanded, setExpanded] = useState<number | null>(null)
  if (!sources.length) return <p className="text-sm text-amber-700">No accessible source documents were retrieved.</p>
  return <div className="mt-5 border-t border-slate-200 pt-4">
    <p className="text-[11px] uppercase tracking-widest text-slate-500 font-bold mb-3">Retrieved sources · {sources.length}</p>
    <div className="grid gap-2 sm:grid-cols-2">
      {sources.map(source => <div key={source.source_number} tabIndex={-1} id={`source-${entryId}-${source.source_number}`}
        className="rounded-xl border border-slate-200 bg-white scroll-mt-20 focus:outline focus:outline-2 focus:outline-indigo-400">
        <button type="button" className="w-full text-left p-3 flex gap-2.5 items-start" aria-expanded={expanded === source.source_number}
          onClick={() => setExpanded(v => v === source.source_number ? null : source.source_number)}>
          <div className="w-7 h-7 shrink-0 bg-indigo-50 text-indigo-600 rounded-lg grid place-items-center text-xs font-bold">{source.source_number}</div>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-slate-800 truncate" title={source.title}>{source.title}</p>
            <p className="text-[11px] text-slate-500 mt-1">{source.page_number != null ? `PDF page ${source.page_number} · ` : ''}Chunk {source.chunk_index} · {(source.similarity * 100).toFixed(0)}% cosine</p>
          </div>
          {expanded === source.source_number ? <ChevronDown size={15} className="text-slate-500"/> : <ChevronRight size={15} className="text-slate-500"/>}
        </button>
        {source.title.toLowerCase().endsWith('.pdf') && <button type="button" onClick={() => onOpenPdf(source)}
          aria-label={`Open PDF ${source.title} page ${source.page_number ?? 1}`}
          className="text-xs text-indigo-700 hover:underline px-3 pb-2">Open original PDF · page {source.page_number ?? 1}</button>}
        {expanded === source.source_number && <div className="border-t border-slate-100 px-3 py-3 text-xs leading-relaxed text-slate-700 whitespace-pre-wrap max-h-48 overflow-y-auto">{source.content}</div>}
      </div>)}
    </div>
    <p className="mt-2 text-[11px] text-slate-500">PDF page numbers use the physical file order. Previously indexed PDFs may require reindexing before viewing.</p>
  </div>
}

function ChatPanel({ session, onUnauthorized }: { session: Session; onUnauthorized: () => void }) {
  const [question, setQuestion] = useState('')
  const [topK, setTopK] = useState(5)
  const [bases, setBases] = useState<KnowledgeBase[]>([])
  const [knowledgeBaseId, setKnowledgeBaseId] = useState<number | null>(null)
  const [history, setHistory] = useState<ChatEntry[]>([])
  const [ratings, setRatings] = useState<Record<number,AnswerFeedback>>({})
  const [ratingBusy, setRatingBusy] = useState<number | null>(null)
  const [conversations, setConversations] = useState<SavedConversation[]>([])
  const [activeId, setActiveId] = useState<number | null>(null)
  const [loadingConversation, setLoadingConversation] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [pdfView, setPdfView] = useState<{ documentId: number; title: string; page: number } | null>(null)
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    let active = true
    const load = () => {
      void api.knowledgeBases(session.key).then(items => {
        if (!active) return
        setBases(items)
        setKnowledgeBaseId(current => current !== null && items.some(x => x.id === current) ? current : null)
      }).catch(err => {
        if (active && err instanceof ApiError && err.status === 401) onUnauthorized()
      })
    }
    load()
    window.addEventListener('knowledge-bases-updated', load)
    return () => { active = false; window.removeEventListener('knowledge-bases-updated', load) }
  }, [session.key, onUnauthorized])
  // Conversation messages have stable database IDs, used by citation anchor links.
  useEffect(() => {
    let alive = true
    api.conversations(session.key).then(items => {
      if (alive) setConversations(items)
    }).catch(err => {
      if (alive) {
        if (err instanceof ApiError && err.status === 401) onUnauthorized()
        else setError(describeError(err))
      }
    })
    return () => { alive = false }
  }, [session.key, onUnauthorized])

  async function openConversation(id: number) {
    if (busy || loadingConversation) return
    setLoadingConversation(true); setError('')
    try {
      const item = await api.conversation(session.key, id)
      const voteItems = await api.conversationFeedback(session.key, id)
      setRatings(Object.fromEntries(voteItems.map(v => [v.message_id, v])))
      setHistory(item.messages.map(message => ({
        id: message.id, question: message.question, answer: message.answer,
        sources: message.sources, redacted: message.redacted, createdAt: new Date(message.created_at),
      })))
      setActiveId(id)
      setQuestion('')
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onUnauthorized()
      else setError(describeError(err))
    } finally { setLoadingConversation(false) }
  }

  function clearChat() {
    setActiveId(null); setHistory([]); setRatings({}); setQuestion(''); setError('')
  }

  async function newConversation() {
    if (busy || loadingConversation) return
    setLoadingConversation(true); setError('')
    try {
      // Create the record immediately so clicking New chat has a visible,
      // persistent result even before the first question is sent.
      const created = await api.createConversation(session.key, 'New chat')
      clearChat()
      setActiveId(created.id)
      setConversations(previous => [created, ...previous.filter(c => c.id !== created.id)])
    } catch (err) {
      // Keep the previous conversation intact when creation fails.
      if (err instanceof ApiError && err.status === 401) onUnauthorized()
      else setError(describeError(err))
    } finally { setLoadingConversation(false) }
  }

  async function renameSaved(item: SavedConversation) {
    if (busy) return
    const title = window.prompt('Rename conversation', item.title)?.trim()
    if (!title || title === item.title || title.length > 120) return
    try {
      const updated = await api.renameConversation(session.key, item.id, title)
      setConversations(old => old.map(c => c.id === updated.id ? updated : c))
    } catch (err) { setError(describeError(err)) }
  }

  async function deleteSaved(item: SavedConversation) {
    if (busy || !window.confirm(`Delete conversation “${item.title}”?`)) return
    try {
      await api.deleteConversation(session.key, item.id)
      setConversations(old => old.filter(c => c.id !== item.id))
      if (activeId === item.id) clearChat()
    } catch (err) { setError(describeError(err)) }
  }
  async function saveRating(messageId: number, rating: 'up' | 'down', reason: FeedbackReason | null = null) {
    if (activeId === null || ratingBusy !== null || busy || loadingConversation) return
    setRatingBusy(messageId); setError('')
    try {
      const old = ratings[messageId]
      if (old?.rating === rating) {
        await api.deleteAnswerFeedback(session.key, activeId, messageId)
        setRatings(prev => { const next = {...prev}; delete next[messageId]; return next })
      } else {
        const updated = await api.setAnswerFeedback(session.key, activeId, messageId, rating, reason)
        setRatings(prev => ({...prev, [messageId]: updated}))
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onUnauthorized()
      else setError(describeError(err))
    } finally { setRatingBusy(null) }
  }

  async function setDownvoteReason(messageId: number, reason: FeedbackReason | null) {
    if (activeId === null || ratingBusy !== null) return
    setRatingBusy(messageId); setError('')
    try {
      const result = await api.setAnswerFeedback(session.key, activeId, messageId, 'down', reason)
      setRatings(prev => ({...prev,[messageId]:result}))
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onUnauthorized()
      else setError(describeError(err))
    } finally { setRatingBusy(null) }
  }

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [history.length, busy])

  const closePdf = useCallback(() => setPdfView(null), [])
  const openPdf = useCallback((source: SearchHit) => {
    if (!source.title.toLowerCase().endsWith('.pdf')) return
    setPdfView({ documentId: source.document_id, title: source.title, page: source.page_number ?? 1 })
  }, [])

  async function send(override?: string) {
    const text = (override ?? question).trim()
    if (busy || loadingConversation || text.length < 3) return
    setBusy(true); setError(''); setQuestion('')
    try {
      let id = activeId
      if (id === null) {
        const created = await api.createConversation(session.key, text.slice(0, 80))
        id = created.id
        setActiveId(id)
        setConversations(previous => [created, ...previous])
      }
      const result = await api.askConversation(session.key, id, text, topK, knowledgeBaseId)
      setHistory(previous => [...previous, {
        id: result.message_id, question: text, answer: result.answer,
        sources: result.sources, createdAt: new Date(),
      }])
      if (activeId !== null && conversations.some(c => c.id === id && c.title === 'New chat')) {
        // Give a newly created chat a useful title after its first answer.
        // Renaming is best-effort and must never turn a successful answer
        // into a failed send or consume additional model credits.
        void api.renameConversation(session.key, id, text.slice(0, 80))
          .then(updated => setConversations(previous => [updated, ...previous.filter(c => c.id !== id)]))
          .catch(() => {})
      } else {
        void api.conversations(session.key).then(setConversations).catch(() => {})
      }
    } catch (err) {
      setQuestion(text)
      if (err instanceof ApiError && err.status === 401) onUnauthorized()
      else setError(describeError(err))
    } finally { setBusy(false) }
  }

  return <div className="flex h-full min-h-0">
    <aside className="hidden md:flex w-56 lg:w-64 border-r border-slate-200 bg-white shrink-0 flex-col" aria-label="Saved conversations">
      <div className="p-3 border-b border-slate-200">
        <button type="button" disabled={busy || loadingConversation} onClick={() => void newConversation()}
          className="btn-primary w-full justify-center"><Plus size={16}/> New chat</button>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {conversations.length === 0 && <p className="px-3 py-4 text-xs text-slate-500">Your saved chats appear here.</p>}
        {conversations.map(item => <div key={item.id} className={`flex items-center rounded-lg ${activeId === item.id ? 'bg-indigo-50' : 'hover:bg-slate-50'}`}>
          <button type="button" disabled={busy || loadingConversation} onClick={() => void openConversation(item.id)}
            aria-label={`Open conversation ${item.title}`}
            className="flex-1 min-w-0 text-left p-2.5 text-xs text-slate-700 truncate" title={item.title}>{item.title}</button>
          <button type="button" aria-label={`Rename conversation ${item.title}`} onClick={() => void renameSaved(item)} className="text-slate-500 p-1 hover:text-indigo-600"><Pencil size={13}/></button>
          <button type="button" aria-label={`Delete conversation ${item.title}`} onClick={() => void deleteSaved(item)} className="text-slate-500 p-1 mr-1 hover:text-rose-600"><Trash2 size={13}/></button>
        </div>)}
      </div>
    </aside>
    <div className="flex flex-col flex-1 min-w-0 min-h-0">
    <header className="workspace-header">
      <div><h1 className="text-xl sm:text-2xl font-semibold tracking-tight text-slate-900">Knowledge Assistant</h1>
        <p className="text-sm mt-1 text-slate-500">Ask questions grounded in your accessible documents.</p></div>
      <div className="flex gap-2 items-center">
        <button type="button" onClick={() => void newConversation()} disabled={busy || loadingConversation}
          className="md:hidden text-xs rounded-lg border border-slate-200 bg-white px-2 py-2">New chat</button>
        <select className="md:hidden max-w-28 text-xs border border-slate-200 rounded-lg p-2" aria-label="Saved conversation"
          value={activeId ?? ''} onChange={e => { if (e.target.value) void openConversation(Number(e.target.value)); else void newConversation() }}>
          <option value="">New chat</option>
          {conversations.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}
        </select>
      <label className="text-xs text-slate-500 flex items-center gap-2">Knowledge base
        <select aria-label="Knowledge base" value={knowledgeBaseId ?? ''}
          onChange={event => setKnowledgeBaseId(event.target.value ? Number(event.target.value) : null)}
          disabled={busy || loadingConversation}
          className="rounded-lg border border-slate-200 bg-white px-2 py-2 text-slate-800 max-w-36">
          <option value="">All accessible documents</option>
          {bases.map(base => <option key={base.id} value={base.id}>{base.name}</option>)}
        </select>
      </label>
      <label className="text-xs text-slate-500 flex items-center gap-2 whitespace-nowrap">Sources
        <select aria-label="Number of sources" value={topK} onChange={event => setTopK(Number(event.target.value))} className="rounded-lg border border-slate-200 px-2 py-2 bg-white text-slate-800">
          {[3, 5, 8, 10].map(k => <option value={k} key={k}>{k}</option>)}
        </select>
      </label></div>
    </header>
    <div className="flex-1 overflow-auto px-4 sm:px-8 py-7">
      <div className="max-w-3xl mx-auto space-y-7">
        {history.length === 0 && <div className="pt-12 sm:pt-20 text-center">
          <div className="w-16 h-16 rounded-2xl bg-indigo-100 text-indigo-600 grid place-items-center mx-auto mb-5"><BookOpen size={29}/></div>
          <h2 className="text-2xl font-semibold tracking-tight text-slate-900">What would you like to know?</h2>
          <p className="text-sm text-slate-500 mt-2 max-w-sm mx-auto leading-relaxed">Explore policies, procedures and technical documentation with source-backed answers.</p>
          <div className="grid gap-2 mt-8 max-w-lg mx-auto">
            {commonQuestions.map(q => <button key={q} disabled={busy} type="button" onClick={() => void send(q)} className="text-left bg-white border border-slate-200 hover:border-indigo-300 hover:shadow-sm rounded-xl px-4 py-3 text-sm text-slate-700 flex items-center justify-between gap-2">{q}<ArrowRight size={15} className="shrink-0 text-indigo-400"/></button>)}
          </div>
        </div>}
        {history.map(entry => <article key={entry.id} className="space-y-4">
          <div className="flex justify-end"><div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-indigo-600 px-5 py-3.5 text-white text-sm leading-6">{entry.question}</div></div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5 sm:p-6 shadow-sm">
            <div className="flex items-center gap-2 mb-4"><div className="w-7 h-7 rounded-lg bg-indigo-100 grid place-items-center text-indigo-600"><Layers size={15}/></div><span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Assistant</span><span className="text-[11px] text-slate-400 ml-auto">{entry.createdAt.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}</span></div>
            <div className="text-sm text-slate-800"><MarkdownAnswer text={entry.answer} sources={entry.sources} entryId={entry.id} onCitationClick={openPdf}/></div>
            <SourceList entryId={entry.id} sources={entry.sources} onOpenPdf={openPdf}/>
            {!entry.redacted && activeId !== null && <div className="mt-4 flex flex-wrap items-center gap-2 text-xs border-t border-slate-200 pt-3" aria-label={`Feedback for answer ${entry.id}`}>
              <span className="text-slate-500 mr-1">Was this answer useful?</span>
              <button type="button" aria-label={`Helpful answer ${entry.id}`} aria-pressed={ratings[entry.id]?.rating === 'up'}
                disabled={ratingBusy === entry.id || busy || loadingConversation}
                onClick={() => void saveRating(entry.id, 'up')}
                className={`rounded-lg border px-2 py-1.5 flex gap-1 items-center ${ratings[entry.id]?.rating === 'up' ? 'border-emerald-400 bg-emerald-50 text-emerald-700' : 'border-slate-200 text-slate-600'}`}><ThumbsUp size={14}/> Helpful</button>
              <button type="button" aria-label={`Not helpful answer ${entry.id}`} aria-pressed={ratings[entry.id]?.rating === 'down'}
                disabled={ratingBusy === entry.id || busy || loadingConversation}
                onClick={() => void saveRating(entry.id, 'down')}
                className={`rounded-lg border px-2 py-1.5 flex gap-1 items-center ${ratings[entry.id]?.rating === 'down' ? 'border-rose-400 bg-rose-50 text-rose-700' : 'border-slate-200 text-slate-600'}`}><ThumbsDown size={14}/> Not helpful</button>
              {ratings[entry.id]?.rating === 'down' && <select aria-label={`Downvote reason for answer ${entry.id}`}
                disabled={ratingBusy === entry.id} value={ratings[entry.id]?.reason ?? ''}
                onChange={e => void setDownvoteReason(entry.id, (e.target.value || null) as FeedbackReason | null)}
                className="max-w-48 min-w-0 rounded-lg border border-slate-200 bg-white p-1.5 text-slate-700">
                <option value="">Choose reason (optional)</option>
                <option value="incorrect">Incorrect</option><option value="incomplete">Incomplete</option>
                <option value="irrelevant">Irrelevant</option><option value="outdated">Outdated</option>
                <option value="other">Other</option>
              </select>}
            </div>}
            <button className="text-xs text-slate-500 hover:text-indigo-600 mt-4 flex gap-1.5 items-center" type="button" onClick={() => void navigator.clipboard.writeText(entry.answer)}><Copy size={13}/> Copy answer</button>
          </div>
        </article>)}
        {loadingConversation && <div role="status" className="text-xs text-slate-500">Loading saved conversation…</div>}
        {busy && <div role="status" className="text-sm text-slate-500 flex items-center gap-3"><span className="spinner"/> Retrieving documents and generating answer…</div>}
        <div ref={endRef}/>
      </div>
    </div>
    <div className="border-t border-slate-200 bg-white px-4 sm:px-8 py-4">
      <form className="max-w-3xl mx-auto" onSubmit={event => { event.preventDefault(); void send() }}>
        <div className="border border-slate-300 focus-within:border-indigo-500 focus-within:ring-2 focus-within:ring-indigo-100 rounded-2xl p-2 flex gap-2 items-end">
          <textarea aria-label="Ask a question" rows={2} maxLength={2000} value={question} onChange={event => setQuestion(event.target.value)}
            onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send() } }}
            placeholder="Ask anything about your documents…" className="resize-none flex-1 min-w-0 py-2 px-3 outline-none text-sm text-slate-800 placeholder:text-slate-400"/>
          <button type="submit" aria-label="Send question" disabled={busy || loadingConversation || question.trim().length < 3} className="btn-primary h-10 w-10 !p-0 justify-center"><Send size={17}/></button>
        </div>
        {error && <p role="alert" className="text-rose-600 mt-2 text-xs">{error}</p>}
        <p className="text-center text-[11px] mt-2 text-slate-400">Answers can be incorrect. Verify important claims against retrieved sources. Enter to send · Shift+Enter for new line.</p>
      </form>
    </div>
    {pdfView && <PdfViewer apiKey={session.key} documentId={pdfView.documentId}
      title={pdfView.title} page={pdfView.page} onClose={closePdf}
      onUnauthorized={onUnauthorized}/>}
    </div>
  </div>
}

function DocumentsPanel({ session, onUnauthorized }: { session: Session; onUnauthorized: () => void }) {
  const [documents, setDocuments] = useState<DocumentRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [jobs, setJobs] = useState<IngestionJob[]>([])
  const seenCompletedJobs = useRef(new Set<string>())
  const [busyId, setBusyId] = useState<number | null>(null)
  const [pdfView, setPdfView] = useState<{ documentId: number; title: string; page: number } | null>(null)
  const closePdf = useCallback(() => setPdfView(null), [])
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [sharingId, setSharingId] = useState<number | null>(null)
  const [shareTo, setShareTo] = useState('')
  const writable = session.identity.role !== 'reader'
  const refresh = useCallback(async () => {
    return api.documents(session.key).then(setDocuments)
  }, [session.key])

  function report(err: unknown) {
    if (err instanceof ApiError && err.status === 401) onUnauthorized()
    else setError(describeError(err))
  }

  useEffect(() => {
    let active = true
    api.documents(session.key).then(items => { if (active) setDocuments(items) })
      .catch(err => { if (active) report(err) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  // Only fetch on key changes; the auth callback is stable within a session.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.key])

  useEffect(() => {
    let active = true
    const poll = async () => {
      try {
        const items = await api.jobs(session.key)
        if (!active) return
        setJobs(items)
        const newlyComplete = items.some(job => {
          if (job.status !== 'completed' || seenCompletedJobs.current.has(job.id)) return false
          seenCompletedJobs.current.add(job.id)
          return true
        })
        if (newlyComplete) await refresh()
      } catch (err) {
        if (active && err instanceof ApiError && err.status === 401) onUnauthorized()
      }
    }
    void poll()
    const interval = window.setInterval(() => void poll(), 3500)
    return () => { active = false; window.clearInterval(interval) }
  }, [session.key, refresh, onUnauthorized])

  async function upload(file: File | undefined) {
    if (!file || uploading) return
    setError(''); setNotice('')
    if (!/\.(txt|md|pdf)$/i.test(file.name)) { setError('Only .txt, .md, and .pdf files are supported.'); return }
    if (file.size > 50 * 1024 * 1024) { setError('Maximum file size is 50 MB.'); return }
    setUploading(true)
    try {
      const job = await api.uploadQueued(session.key, file)
      setNotice(`${job.filename} queued for background indexing (job ${job.id.slice(0, 8)}).`)
      setJobs(await api.jobs(session.key))
    } catch (err) { report(err) }
    finally { setUploading(false) }
  }

  async function share(id: number) {
    if (!shareTo.trim()) return
    setBusyId(id); setError(''); setNotice('')
    try {
      await api.share(session.key, id, shareTo.trim())
      setNotice(`Document ${id} shared with ${shareTo.trim()} in your tenant.`)
      setSharingId(null); setShareTo('')
    } catch (err) { report(err) }
    finally { setBusyId(null) }
  }

  async function remove(doc: DocumentRecord) {
    if (!window.confirm(`Delete "${doc.title}" and its indexed chunks? This cannot be undone.`)) return
    setBusyId(doc.id); setError(''); setNotice('')
    try { await api.remove(session.key, doc.id); await refresh(); setNotice(`Deleted document ${doc.id}.`) }
    catch (err) { report(err) }
    finally { setBusyId(null) }
  }

  async function reindex(doc: DocumentRecord, file: File | undefined) {
    if (!file) return
    if (file.name !== doc.title) { setError('The PDF filename must match the existing document title exactly.'); return }
    setBusyId(doc.id); setError(''); setNotice('')
    try {
      const result = await api.reindex(session.key, doc.id, file)
      setNotice(`Reindexed ${doc.title} (${result.chunk_count} chunks).`)
    } catch (err) { report(err) }
    finally { setBusyId(null) }
  }

  const filtered = documents.filter(doc => doc.title.toLowerCase().includes(search.toLowerCase()))
  return <div className="min-h-0 h-full overflow-y-auto">
    <header className="workspace-header"><div><h1 className="text-xl sm:text-2xl font-semibold tracking-tight text-slate-900">Documents</h1>
      <p className="text-sm mt-1 text-slate-500">Only documents authorized for your account appear here.</p></div>
      <div className="rounded-full text-xs bg-indigo-50 text-indigo-700 font-semibold px-3 py-2">{documents.length} visible</div>
    </header>
    <div className="max-w-5xl px-4 sm:px-8 py-7 mx-auto">
      {writable && <section className="rounded-2xl border border-indigo-200 bg-gradient-to-r from-indigo-50 to-white p-5 sm:p-6 mb-7">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div><h2 className="font-semibold text-slate-900 flex items-center gap-2"><UploadCloud size={19} className="text-indigo-600"/> Add knowledge</h2>
            <p className="text-sm text-slate-500 mt-1">Upload PDF, Markdown or text files. A separate background worker indexes them.</p></div>
          <label className="btn-primary cursor-pointer justify-center">{uploading ? 'Uploading…' : 'Upload document'} <FilePlus2 size={16}/>
            <input aria-label="Select document to upload" type="file" accept=".txt,.md,.pdf" disabled={uploading} className="sr-only" onChange={event => { void upload(event.target.files?.[0]); event.target.value = '' }}/>
          </label>
        </div>
        <p className="text-xs text-slate-400 mt-4">Limit: 50 MB per file · Local developer environment only · Private by default</p>
      </section>}
      {error && <div role="alert" className="notice-error mb-4">{error}<button aria-label="Dismiss error" type="button" onClick={() => setError('')}><X size={16}/></button></div>}
      {notice && <div role="status" className="notice-success mb-4"><Check size={16}/>{notice}<button aria-label="Dismiss notification" type="button" onClick={() => setNotice('')}><X size={16}/></button></div>}
      {writable && jobs.length > 0 && <section aria-label="Ingestion jobs" className="mb-7 border border-slate-200 bg-white rounded-xl p-4 sm:p-5">
        <h2 className="font-semibold text-slate-900 mb-3">Recent uploads</h2>
        <div className="space-y-2">{jobs.map(job => <div key={job.id} className="flex gap-3 justify-between items-start text-sm border-t border-slate-100 pt-2">
          <div className="min-w-0"><p className="font-medium text-slate-700 truncate" title={job.filename}>{job.filename}</p>
            <p className="text-xs text-slate-500">{job.id.slice(0, 8)}{job.document_id ? ` · Document #${job.document_id}` : ''}{job.chunk_count != null ? ` · ${job.chunk_count} chunks` : ''}</p>
            {job.status === 'failed' && <p role="alert" className="text-xs text-rose-600 mt-1">{job.error || 'Processing failed'}</p>}
          </div>
          <span aria-label={`Upload ${job.filename}: ${job.status}`} className={`text-xs font-semibold px-2.5 py-1 rounded-full ${job.status === 'completed' ? 'bg-green-100 text-green-800' : job.status === 'failed' ? 'bg-rose-100 text-rose-700' : 'bg-indigo-100 text-indigo-700'}`}>{job.status}</span>
        </div>)}</div>
      </section>}
      <div className="flex items-center justify-between gap-3 mb-4">
        <h2 className="font-semibold text-slate-900">Your knowledge library</h2>
        <div className="relative"><Search size={15} className="absolute top-2.5 left-3 text-slate-400"/><input aria-label="Filter documents" placeholder="Filter documents…" value={search} onChange={event => setSearch(event.target.value)} className="rounded-lg border border-slate-200 py-2 pl-9 pr-3 text-sm w-44 sm:w-60 outline-none focus:border-indigo-400"/></div>
      </div>
      {loading && <div role="status" className="flex gap-2 items-center text-sm text-slate-500"><span className="spinner"/> Loading documents…</div>}
      {!loading && filtered.length === 0 && <div className="border border-dashed border-slate-300 p-12 rounded-2xl text-center text-slate-500"><FolderOpen size={33} className="mx-auto mb-3 text-slate-400"/><p className="text-sm">No visible documents match your search.</p></div>}
      <div className="space-y-3">{filtered.map(doc => <section key={doc.id} className="rounded-xl border border-slate-200 bg-white p-4 sm:p-5 shadow-sm">
        <div className="flex items-start gap-3">
          <div className="shrink-0 w-10 h-10 rounded-lg bg-slate-100 text-slate-500 grid place-items-center"><FileText size={21}/></div>
          <div className="flex-1 min-w-0"><h3 className="font-semibold text-slate-800 truncate" title={doc.title}>{doc.title}</h3>
            <p className="text-xs text-slate-500 mt-1">ID {doc.id} · Owner #{doc.owner_user_id} · {new Date(doc.created_at).toLocaleDateString()}</p></div>
          {writable && <div className="flex shrink-0 items-center gap-1">
            <button aria-label={`Share ${doc.title}`} title="Share" type="button" className="icon-action" disabled={busyId === doc.id} onClick={() => { setSharingId(v => v === doc.id ? null : doc.id); setShareTo('') }}><Users size={17}/></button>
            <button aria-label={`Delete ${doc.title}`} title="Delete" type="button" className="icon-action text-rose-500 hover:bg-rose-50" disabled={busyId === doc.id} onClick={() => void remove(doc)}><Trash2 size={17}/></button>
          </div>}
        </div>
        {doc.title.toLowerCase().endsWith('.pdf') && <button type="button" aria-label={`View PDF ${doc.title}`}
          className="mt-3 inline-block text-xs text-indigo-700 hover:underline"
          onClick={() => setPdfView({ documentId: doc.id, title: doc.title, page: 1 })}>View original PDF</button>}
        {writable && doc.title.toLowerCase().endsWith('.pdf') && <label className="inline-flex cursor-pointer mt-3 text-xs text-indigo-600 hover:text-indigo-700 font-medium gap-1.5 items-center"><UploadCloud size={14}/> Replace PDF / reindex
          <input className="sr-only" aria-label={`Reindex ${doc.title}`} disabled={busyId === doc.id} type="file" accept=".pdf" onChange={event => { void reindex(doc, event.target.files?.[0]); event.target.value = '' }}/></label>}
        {sharingId === doc.id && <form onSubmit={event => { event.preventDefault(); void share(doc.id) }} className="mt-4 border-t border-slate-100 pt-4 flex flex-wrap gap-2 items-center">
          <input aria-label="Username to share with" value={shareTo} onChange={event => setShareTo(event.target.value)} placeholder="Same-tenant username" maxLength={80} className="border border-slate-300 rounded-lg px-3 py-2 text-sm flex-1 min-w-44 outline-none focus:border-indigo-400"/>
          <button disabled={busyId === doc.id || !shareTo.trim()} type="submit" className="btn-primary !px-3 !py-2">Grant access</button>
        </form>}
      </section>)}</div>
      {writable && <p className="text-xs text-slate-400 mt-6">Document owners and tenant admins can manage documents. The backend enforces permissions, so some editor actions may be denied.</p>}
      {pdfView && <PdfViewer apiKey={session.key} documentId={pdfView.documentId}
        title={pdfView.title} page={pdfView.page} onClose={closePdf}
        onUnauthorized={onUnauthorized}/>}
    </div>
  </div>
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null)
  const [tab, setTab] = useState<Tab>('chat')
  const [navOpen, setNavOpen] = useState(false)
  const [authMessage, setAuthMessage] = useState('')

  async function login(key: string) {
    const identity = await api.me(key)
    setSession({ key, identity }); setAuthMessage(''); setTab('chat')
  }
  const logout = useCallback(() => {
    if (session?.key.startsWith('rags_')) void api.logout(session.key).catch(() => {})
    setSession(null); setTab('chat'); setNavOpen(false)
  }, [session])
  const onUnauthorized = useCallback(() => { logout(); setAuthMessage('Key is invalid or revoked. Please sign in again.') }, [logout])

  if (!session) return <><SignIn onLogin={login}/>{authMessage && <div role="alert" className="fixed bottom-5 right-5 rounded-lg bg-rose-100 p-3 text-rose-800 text-sm shadow-lg">{authMessage}</div>}</>

  return <div className="flex h-screen overflow-hidden bg-[#f6f8fc]">
    {navOpen && <button type="button" aria-label="Close navigation" onClick={() => setNavOpen(false)} className="fixed inset-0 z-20 bg-slate-950/40 md:hidden"/>}
    <aside className={`sidebar ${navOpen ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0`}>
      <div className="p-6"><Brand/></div>
      <nav className="mt-4 px-3 space-y-1" aria-label="Main navigation">
        {([
          ...(session.identity.role === 'admin' ? [
            { key: 'dashboard' as const, title: 'Dashboard', icon: LayoutDashboard },
            { key: 'users' as const, title: 'User Management', icon: UserCog },
          ] : []),
          { key: 'chat' as const, title: 'Assistant', icon: MessageSquareText },
          { key: 'documents' as const, title: 'Documents', icon: FolderOpen },
          { key: 'knowledge-bases' as const, title: 'Knowledge Bases', icon: BookOpen },
        ]).map(item => {
          const Icon = item.icon
          return <button key={item.key} onClick={() => { setTab(item.key); setNavOpen(false) }} aria-current={tab === item.key ? 'page' : undefined}
            className={`nav-link ${tab === item.key ? 'nav-link-active' : ''}`} type="button"><Icon size={18}/>{item.title}</button>
        })}
      </nav>
      <div className="mt-auto px-5 pb-6 space-y-4">
        <div className="rounded-xl bg-white/[.05] border border-white/10 p-3.5 text-xs text-slate-300 leading-relaxed flex gap-2"><ShieldCheck size={17} className="text-teal-300 shrink-0"/>Documents are restricted by your account's server-side permissions.</div>
        <div className="border-t border-white/10 pt-4 flex gap-3 items-center">
          <div className="w-9 h-9 grid place-items-center bg-indigo-500/20 text-indigo-200 rounded-full font-bold">{session.identity.username.charAt(0).toUpperCase()}</div>
          <div className="flex-1 min-w-0"><div className="text-slate-100 text-sm font-semibold truncate">{session.identity.username}</div><div className="text-xs text-slate-400 capitalize">{session.identity.role} · tenant #{session.identity.tenant_id}</div></div>
          <button aria-label="Sign out" type="button" title="Sign out" onClick={logout} className="text-slate-400 hover:text-white"><LogOut size={19}/></button>
        </div>
      </div>
    </aside>
    <main className="flex-1 min-w-0 flex flex-col">
      <div className="md:hidden h-14 border-b bg-white flex items-center px-4 gap-3"><button type="button" aria-label="Open navigation" onClick={() => setNavOpen(true)}><Menu size={22}/></button><span className="font-semibold">KnowledgeBase</span></div>
      <div className={tab === 'chat' ? 'flex-1 min-h-0' : 'hidden'}>
        <ChatPanel session={session} onUnauthorized={onUnauthorized}/>
      </div>
      {tab === 'documents' && <DocumentsPanel session={session} onUnauthorized={onUnauthorized}/>}
      {tab === 'knowledge-bases' && <KnowledgeBasesPanel session={session} onUnauthorized={onUnauthorized}/> }
      {tab === 'dashboard' && session.identity.role === 'admin' && <DashboardPanel apiKey={session.key} onUnauthorized={onUnauthorized}/>}
      {tab === 'users' && session.identity.role === 'admin' && <UserManagementPanel apiKey={session.key} onUnauthorized={onUnauthorized} selfUserId={session.identity.user_id}/>}
    </main>
  </div>
}
