import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { FilePlus2, UploadCloud } from 'lucide-react'
import { api, ApiError } from './api'

type UploadStatus = 'waiting' | 'uploading' | 'queued' | 'failed' | 'invalid'
interface UploadItem { id: number; name: string; file: File | null; status: UploadStatus; error: string }
interface Props { apiKey: string; disabled: boolean; onUnauthorized: () => void; onQueued: () => void }

function validationError(file: File) {
  if (!/\.(txt|md|pdf)$/i.test(file.name)) return 'Only .txt, .md, and .pdf files are supported.'
  if (file.size === 0) return 'The file is empty.'
  if (file.size > 50 * 1024 * 1024) return 'Maximum file size is 50 MB.'
  return ''
}

export default function DocumentUploads(props: Props) {
  return <UploadQueue key={props.apiKey} {...props}/>
}

function UploadQueue({apiKey, disabled, onUnauthorized, onQueued}: Props) {
  const [items,setItems] = useState<UploadItem[]>([])
  const [busy,setBusy] = useState(false)
  const nextId = useRef(1)
  const scopeRef = useRef<{busy: boolean} | null>(null)
  const callbacks = useRef({onUnauthorized,onQueued})
  useLayoutEffect(() => {callbacks.current = {onUnauthorized,onQueued}},[onUnauthorized,onQueued])
  useEffect(() => {
    const scope = {busy:false}
    scopeRef.current = scope
    return () => {scopeRef.current = null}
  },[apiKey])

  async function run(batch: UploadItem[]) {
    const scope = scopeRef.current
    if (!scope || scope.busy || disabled || batch.length === 0) return
    scope.busy = true; setBusy(true)
    const ids = new Set(batch.map(item => item.id))
    setItems(previous => previous.map(item => ids.has(item.id) ? {...item,status:'waiting',error:''} : item))
    const current = () => scopeRef.current === scope
    const update = (id: number, values: Partial<UploadItem>) => {
      if (current()) setItems(previous => previous.map(item => item.id === id ? {...item,...values} : item))
    }
    try {
      // Separate bounded requests preserve per-file limits and let later files
      // proceed after an individual error without overwhelming the local API.
      for (const item of batch) {
        if (!current()) break
        if (!item.file) continue
        update(item.id,{status:'uploading',error:''})
        try {
          await api.uploadQueued(apiKey,item.file)
          if (!current()) break
          update(item.id,{status:'queued',file:null})
          callbacks.current.onQueued()
        } catch (err) {
          if (!current()) break
          const error = err instanceof Error ? err.message : 'Upload failed'
          update(item.id,{status:'failed',error: err instanceof ApiError && err.status === 0
            ? `${error} Check the library before retrying; the server may have received this file.` : error})
          if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
            if (err.status === 401) callbacks.current.onUnauthorized()
            if (current()) setItems(previous => previous.map(entry => entry.status === 'waiting'
              ? {...entry,status:'failed',error:'Uploads stopped because access was denied.'} : entry))
            break
          }
        }
      }
    } finally {
      if (current()) {scope.busy = false; setBusy(false)}
    }
  }
  function select(files: File[]) {
    if (disabled || scopeRef.current?.busy || files.length === 0) return
    const batch = files.map((file): UploadItem => {
      const error = validationError(file)
      return {id:nextId.current++,name:file.name,file:error ? null : file,
        status:error ? 'invalid' : 'waiting',error}
    })
    setItems(previous => [...previous,...batch])
    void run(batch.filter(item => item.status === 'waiting'))
  }
  const queued = items.filter(item => item.status === 'queued').length
  const failed = items.filter(item => item.status === 'failed').length
  const invalid = items.filter(item => item.status === 'invalid').length
  const finished = queued + failed + invalid
  const labels: Record<UploadStatus,string> = {waiting:'Waiting',uploading:'Uploading…',queued:'Queued for indexing',failed:'Upload failed',invalid:'Invalid file'}
  return <section aria-label="Document uploads" className="rounded-xl border border-indigo-200 bg-white p-5 space-y-4">
    <div className="flex flex-wrap justify-between gap-4 items-center">
      <div><h2 className="font-semibold flex gap-2"><UploadCloud size={19}/> Add knowledge</h2>
        <p className="text-sm text-slate-500 mt-1">Select multiple PDF, Markdown or text files · 50 MB per file · Private by default</p></div>
      <label className="btn-primary cursor-pointer">{busy ? 'Uploading documents…' : 'Upload documents'} <FilePlus2 size={16}/>
        <input aria-label="Select documents to upload" type="file" multiple accept=".txt,.md,.pdf" disabled={disabled || busy} className="sr-only"
          onChange={event => {select(Array.from(event.target.files ?? [])); event.target.value = ''}}/>
      </label>
    </div>
    {items.length > 0 && <>
      <p role="status" className="text-sm text-slate-600">{queued} queued · {failed} failed · {invalid} invalid · {items.length - finished} remaining</p>
      {busy && <><progress aria-label="Files uploaded or checked" max={items.length} value={finished} className="w-full accent-indigo-600"/>
        <p className="text-xs text-slate-500">Keep this page open until uploading finishes. Queued files continue indexing in the background.</p></>}
      <ul aria-label="Selected uploads" className="max-h-64 overflow-y-auto border rounded-lg divide-y divide-slate-100">
        {items.map(item => <li key={item.id} className="p-3 text-sm flex flex-wrap justify-between gap-2">
          <div className="min-w-0 flex-1"><p className="font-medium break-words">{item.name}</p>
            {item.error && <p className="text-xs text-rose-700 mt-1">{item.error}</p>}</div>
          <span className={item.status === 'failed' || item.status === 'invalid' ? 'text-rose-700' : 'text-slate-500'}>{labels[item.status]}</span>
        </li>)}
      </ul>
      <div className="flex gap-3 flex-wrap">
        {failed > 0 && <button type="button" className="table-button" disabled={disabled || busy}
          onClick={() => void run(items.filter(item => item.status === 'failed'))}>Retry failed uploads</button>}
        <button type="button" className="text-sm text-slate-500" disabled={busy} onClick={() => setItems([])}>Clear upload list</button>
      </div>
    </>}
  </section>
}
