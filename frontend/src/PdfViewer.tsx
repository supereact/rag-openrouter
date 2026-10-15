import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { api, ApiError } from './api'

interface Props {
  apiKey: string
  documentId: number
  title: string
  page: number
  onClose: () => void
  onUnauthorized: () => void
}

/** PDF bytes are fetched with Authorization, then viewed through a temporary blob URL.
 * Never put API keys into the iframe URL or expose /original-pdf as static content.
 */
export default function PdfViewer({ apiKey, documentId, title, page, onClose, onUnauthorized }: Props) {
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState('')
  const safePage = Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1

  useEffect(() => {
    let active = true
    let objectUrl: string | undefined
    setUrl(null)
    setError('')
    void api.pdf(apiKey, documentId).then(blob => {
      if (!active) return
      objectUrl = URL.createObjectURL(blob)
      setUrl(`${objectUrl}#page=${safePage}`)
    }).catch(err => {
      if (!active) return
      if (err instanceof ApiError && err.status === 401) onUnauthorized()
      else setError(err instanceof Error ? err.message : 'Could not open PDF')
    })
    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [apiKey, documentId, safePage, onUnauthorized])

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose])

  return createPortal(<div role="dialog" aria-modal="true" aria-label={`PDF viewer: ${title}`}
    className="fixed inset-0 z-[100] bg-slate-900/80 p-3 sm:p-6 flex flex-col">
    <div className="bg-white rounded-t-xl flex items-center justify-between gap-3 px-4 py-3">
      <div className="min-w-0"><p className="font-semibold text-slate-900 truncate">{title}</p>
        <p className="text-xs text-slate-500">Physical PDF page {safePage}</p></div>
      <button type="button" aria-label="Close PDF viewer" onClick={onClose} className="rounded-lg border px-3 py-2 text-sm hover:bg-slate-100 flex items-center gap-2"><X size={16}/> Close</button>
    </div>
    <div className="bg-white rounded-b-xl flex-1 min-h-0 overflow-hidden">
      {error ? <p role="alert" className="p-6 text-rose-700">{error}. An owner may need to reindex an older PDF, or your account may lack access.</p>
        : !url ? <p role="status" className="p-6 text-slate-600">Loading authorized PDF…</p>
        : <iframe title={`Original PDF: ${title}`} src={url} className="w-full h-full border-0"/>}
    </div>
  </div>, document.body)
}
