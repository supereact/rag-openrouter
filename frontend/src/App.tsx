import { lazy, Suspense, useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import {
  ArrowRight, BookOpen, ChevronDown, ChevronRight, Copy,
  FolderOpen, KeyRound, Layers, LogOut, LockKeyhole,
  Menu, MessageSquareText, Send, ShieldCheck, Trash2,
  LayoutDashboard, UserCog, Plus, Pencil, ThumbsUp, ThumbsDown, Wallet,
} from 'lucide-react'
import { ApiError, api } from './api'
import type { ChatEntry, Identity, SearchHit, SavedConversation, KnowledgeBase, AnswerFeedback, FeedbackReason } from './types'
import MarkdownAnswer from './MarkdownAnswer'
import PdfViewer from './PdfViewer'
import { DashboardPanel, UserManagementPanel } from './AdminPanel'
import KnowledgeBasesPanel from './KnowledgeBasesPanel'
import DocumentsPanel from './DocumentsPanel'
import AuditLogPanel from './AuditLogPanel'
import CreditsPanel from './CreditsPanel'
import PageFrame from './PageFrame'
import Brand from './Brand'
import { creditsEnabled } from './features'
import { followLink, navigate, returnDestination, routes, useLocation } from './navigation'

const SupportPanel = lazy(() => import('./SupportPanel'))
const AccountPanel = lazy(() => import('./AccountPanel'))
const LandingPage = lazy(() => import('./LandingPage'))

interface Session { key: string; identity: Identity }
const commonQuestions = [
  'What are the phases of incident response?',
  'How do I troubleshoot VPN connection issues?',
  'What is the database backup procedure?',
]

function describeError(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.'
}

function SignIn({ onLogin, onBrowserLogin, initialMode }: {
  onLogin: (key: string) => Promise<void>; onBrowserLogin: (identity: Identity) => void
  initialMode: 'password' | 'register'
}) {
  const [mode, setMode] = useState<'key' | 'password' | 'register'>(initialMode)
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
        onBrowserLogin(await api.browserLogin(email, password))
      } else {
        if (password !== confirmPassword) throw new Error('Passwords do not match')
        onBrowserLogin(await api.browserRegister(invitation, email, username, password))
      }
    } catch (err) { setError(describeError(err)) }
    finally { setBusy(false) }
  }

  return <div className="h-dvh overflow-y-auto bg-[#080f1e] flex flex-col">
    <div className="p-7 sm:p-10"><a href="/" onClick={followLink} aria-label="KnowledgeBase home"><Brand /></a></div>
    <div className="flex-1 flex items-center justify-center p-5">
      <div className="w-full max-w-[460px] rounded-2xl border border-white/10 bg-white/[.045] p-7 sm:p-9 shadow-2xl">
        <div className="w-12 h-12 grid place-items-center rounded-xl bg-indigo-500/15 text-indigo-300 mb-5"><LockKeyhole size={22}/></div>
        <h1 className="text-[27px] text-white font-semibold tracking-tight">Welcome to KnowledgeBase</h1>
        <p className="mt-2 text-slate-400 text-sm leading-relaxed">Sign in to your workspace, or create your own private workspace.</p>
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
              <input id="invitation-code" value={invitation} onChange={e => setInvitation(e.target.value)} autoComplete="off" placeholder="Optional · join an existing workspace" aria-describedby="invitation-help" className="w-full rounded-lg border border-slate-600 bg-slate-900 p-3 text-white"/>
              <p id="invitation-help" className="text-xs text-slate-400">Leave blank to create a private workspace. Use an invitation to join your team.</p>
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
              <p className="text-xs text-slate-400">Use a unique password of at least 12 characters. New accounts receive a one-time $0.001 OpenRouter usage allowance.</p>
            </>}
          </>}
          {error && <p role="alert" className="text-rose-300 text-sm">{error}</p>}
          <button disabled={busy || (mode === 'key' ? !key.trim() : !email.trim() || !password.trim())} className="btn-primary w-full justify-center" type="submit">
            {busy ? 'Authenticating…' : mode === 'register' ? 'Create account' : mode === 'password' ? 'Sign in' : 'Connect to workspace'} <ArrowRight size={17}/>
          </button>
        </form>
        <div className="mt-7 pt-5 border-t border-white/10 flex gap-3 items-start text-slate-400 text-xs leading-5">
          <ShieldCheck size={18} className="shrink-0 text-teal-300"/>
          Password sign-in uses a private browser cookie and survives refresh until the session expires or is revoked. API keys stay in this tab's memory.
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
    <PageFrame title="Knowledge Assistant" subtitle="Ask questions grounded in your accessible documents."
      actions={<div className="flex flex-wrap gap-2 items-center min-w-0">
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
      </label></div>}
      footer={<div className="shrink-0 border-t border-slate-200 bg-white px-4 sm:px-8 py-4">
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
    </div>}>
    <div className="px-4 sm:px-8 py-7">
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
    {pdfView && <PdfViewer apiKey={session.key} documentId={pdfView.documentId}
      title={pdfView.title} page={pdfView.page} onClose={closePdf}
      onUnauthorized={onUnauthorized}/>}
    </PageFrame>
  </div>
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null)
  const [restoring, setRestoring] = useState(true)
  const [restoreError, setRestoreError] = useState('')
  const [restoreAttempt, setRestoreAttempt] = useState(0)
  const location = useLocation()
  const path = location.split('?')[0]
  const signInMode = new URLSearchParams(location.split('?')[1]).get('mode') === 'register' ? 'register' : 'password'
  const known = routes.some(route => route === path)
  const adminRoute = path === '/dashboard' || path === '/users' || path === '/audit-log'
  const [navOpen, setNavOpen] = useState(false)
  const [authMessage, setAuthMessage] = useState('')

  useEffect(() => {
    let active = true
    setRestoring(true); setRestoreError('')
    api.browserSession().then(identity => {
      if (active) setSession({key: '', identity})
    }).catch(err => {
      if (active && !(err instanceof ApiError && err.status === 401)) setRestoreError(describeError(err))
    }).finally(() => { if (active) setRestoring(false) })
    return () => { active = false }
  }, [restoreAttempt])

  function browserLogin(identity: Identity) {
    setSession({key: '', identity}); setAuthMessage('')
    navigate(returnDestination(new URLSearchParams(window.location.search).get('returnTo')), true)
  }

  async function login(key: string) {
    const identity = await api.me(key)
    setSession({ key, identity }); setAuthMessage('')
    navigate(returnDestination(new URLSearchParams(window.location.search).get('returnTo')), true)
  }
  const logout = useCallback(async () => {
    // Confirm server revocation before showing sign-in: otherwise a failed
    // logout would silently sign the same cookie back in on the next refresh.
    try {
      if (session?.key === '') await api.browserLogout()
      else if (session?.key.startsWith('rags_')) await api.logout(session.key)
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 401)) { setAuthMessage(`Sign out failed. ${describeError(err)}`); return }
    }
    setSession(null); setNavOpen(false)
    navigate('/login', true)
  }, [session])
  const onUnauthorized = useCallback(() => {
    const destination = returnDestination(window.location.pathname + window.location.search)
    setSession(null); setNavOpen(false)
    navigate(`/login?${new URLSearchParams({returnTo: destination})}`, true)
    setAuthMessage('Your session expired or access was revoked. Please sign in again.')
  }, [])
  const onAccountSignedOut = useCallback((message: string) => {
    setSession(null); setNavOpen(false)
    navigate('/login?returnTo=%2Faccount', true)
    setAuthMessage(message)
  }, [])

  useEffect(() => {
    setNavOpen(false)
    if (restoring || restoreError) return
    if (!session && known) navigate(`/login?${new URLSearchParams({returnTo: location})}`, true)
    else if (session && path === '/login') navigate(returnDestination(new URLSearchParams(location.split('?')[1]).get('returnTo')), true)
  }, [location, path, known, session, restoring, restoreError])

  // The public page remains available while session restoration is pending or fails.
  // Its showcase uses fictional local content, never authenticated chat/PDF APIs.
  if (path === '/') return <Suspense fallback={<div className="h-dvh overflow-auto bg-[#080d1b] p-8 text-slate-200"><p role="status">Loading KnowledgeBase…</p></div>}>
    <LandingPage signedIn={session !== null}/>
  </Suspense>

  if (restoring || restoreError) return <div className="h-dvh overflow-auto bg-slate-50 p-8">
    {restoring ? <p role="status">Restoring your session…</p> : <><p role="alert">Could not check your session. {restoreError}</p>
      <button type="button" className="btn-primary mt-4" onClick={() => setRestoreAttempt(value => value + 1)}>Retry session check</button></>}
  </div>

  if (!session && !known && path !== '/' && path !== '/login') return <div className="h-dvh overflow-auto p-8"><h1>Page not found</h1><a href="/login" onClick={followLink}>Sign in</a></div>
  if (!session) return <><SignIn key={signInMode} initialMode={signInMode} onLogin={login} onBrowserLogin={browserLogin}/>{authMessage && <div role="alert" className="fixed bottom-5 right-5 rounded-lg bg-rose-100 p-3 text-rose-800 text-sm shadow-lg">{authMessage}</div>}</>

  return <div className="flex h-dvh overflow-hidden bg-[#f6f8fc]">
    {navOpen && <button type="button" aria-label="Close navigation" onClick={() => setNavOpen(false)} className="fixed inset-0 z-20 bg-slate-950/40 md:hidden"/>}
    <aside className={`sidebar ${navOpen ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0`}>
      <div className="p-6"><Brand/></div>
      <nav className="mt-4 px-3 space-y-1 flex-1 min-h-0 overflow-y-auto" aria-label="Main navigation">
        {([
          ...(session.identity.role === 'admin' ? [
            { key: 'dashboard' as const, title: 'Dashboard', icon: LayoutDashboard },
            { key: 'users' as const, title: 'User Management', icon: UserCog },
            { key: 'audit-log' as const, title: 'Audit Log', icon: ShieldCheck },
          ] : []),
          { key: 'assistant' as const, title: 'Assistant', icon: MessageSquareText },
          { key: 'documents' as const, title: 'Documents', icon: FolderOpen },
          { key: 'knowledge-bases' as const, title: 'Knowledge Bases', icon: BookOpen },
          ...(creditsEnabled() ? [{ key: 'credits' as const, title: 'Credits', icon: Wallet }] : []),
          { key: 'support' as const, title: 'Support', icon: MessageSquareText },
          { key: 'account' as const, title: 'Account', icon: LockKeyhole },
        ]).map(item => {
          const Icon = item.icon
          return <a key={item.key} href={`/${item.key}`} onClick={event => {
            followLink(event)
            if (event.defaultPrevented) setNavOpen(false)
          }} aria-current={path === `/${item.key}` ? 'page' : undefined}
            className={`nav-link ${path === `/${item.key}` ? 'nav-link-active' : ''}`}><Icon size={18}/>{item.title}</a>
        })}
      </nav>
      <div className="mt-auto px-5 pb-6 space-y-4">
        <div className="rounded-xl bg-white/[.05] border border-white/10 p-3.5 text-xs text-slate-300 leading-relaxed flex gap-2"><ShieldCheck size={17} className="text-teal-300 shrink-0"/>Documents are restricted by your account's server-side permissions.</div>
        <div className="border-t border-white/10 pt-4 flex gap-3 items-center">
          <div className="w-9 h-9 grid place-items-center bg-indigo-500/20 text-indigo-200 rounded-full font-bold">{session.identity.username.charAt(0).toUpperCase()}</div>
          <div className="flex-1 min-w-0"><div className="text-slate-100 text-sm font-semibold truncate">{session.identity.username}</div><div className="text-xs text-slate-400 capitalize">{session.identity.role} · tenant #{session.identity.tenant_id}</div></div>
          <button aria-label="Sign out" type="button" title="Sign out" onClick={() => void logout()} className="text-slate-400 hover:text-white"><LogOut size={19}/></button>
        </div>
      </div>
    </aside>
    {authMessage && <p role="alert" className="fixed bottom-5 right-5 z-50 notice-error">{authMessage}</p>}
    <main className="flex-1 min-w-0 min-h-0 overflow-hidden flex flex-col">
      <div className="md:hidden h-14 shrink-0 border-b bg-white flex items-center px-4 gap-3"><button type="button" aria-label="Open navigation" onClick={() => setNavOpen(true)}><Menu size={22}/></button><span className="font-semibold">KnowledgeBase</span></div>
      <div className={path === '/assistant' ? 'flex-1 min-h-0' : 'hidden'}>
        <ChatPanel session={session} onUnauthorized={onUnauthorized}/>
      </div>
      {path === '/documents' && <DocumentsPanel session={session} onUnauthorized={onUnauthorized}/>}
      {path === '/knowledge-bases' && <KnowledgeBasesPanel session={session} onUnauthorized={onUnauthorized}/> }
      {path === '/credits' && creditsEnabled() && <CreditsPanel key={`${session.identity.tenant_id}:${session.identity.user_id}:${session.key}`}
        apiKey={session.key} onUnauthorized={onUnauthorized}/>}
      {path === '/credits' && !creditsEnabled() && <PageFrame title="Credits unavailable" subtitle="Credit purchases are currently disabled.">
        <p className="p-6">Contact your administrator about your usage allowance.</p>
      </PageFrame>}
      {path === '/support' && <Suspense fallback={<PageFrame title="Support" subtitle="Private chat with the support team."><p className="p-6" role="status">Loading support…</p></PageFrame>}>
        <SupportPanel key={`${session.identity.tenant_id}:${session.identity.user_id}:${session.key}`}
          apiKey={session.key} onUnauthorized={onUnauthorized}/>
      </Suspense>}
      {path === '/account' && <Suspense fallback={<PageFrame title="Account security" subtitle="Manage your password and active sign-ins."><p className="p-6" role="status">Loading account security…</p></PageFrame>}>
        <AccountPanel key={`${session.identity.tenant_id}:${session.identity.user_id}:${session.key}`}
          apiKey={session.key} onUnauthorized={onUnauthorized} onSignedOut={onAccountSignedOut}/>
      </Suspense>}
      {path === '/dashboard' && session.identity.role === 'admin' && <DashboardPanel apiKey={session.key} onUnauthorized={onUnauthorized}/>}
      {path === '/users' && session.identity.role === 'admin' && <UserManagementPanel apiKey={session.key} onUnauthorized={onUnauthorized} selfUserId={session.identity.user_id}/>}
      {path === '/audit-log' && session.identity.role === 'admin' && <AuditLogPanel apiKey={session.key} onUnauthorized={onUnauthorized}/>}
      {adminRoute && session.identity.role !== 'admin' && <PageFrame title="Access denied" subtitle="Administrator access is required."><p className="p-6">Choose an available page from navigation.</p></PageFrame>}
      {!known && path !== '/' && path !== '/login' && <PageFrame title="Page not found" subtitle="This page does not exist."><a href="/assistant" onClick={followLink} className="block p-6 text-indigo-700">Return to Assistant</a></PageFrame>}
    </main>
  </div>
}
