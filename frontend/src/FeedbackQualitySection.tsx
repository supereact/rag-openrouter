import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, ThumbsUp, ThumbsDown } from 'lucide-react'
import { api, ApiError } from './api'
import type { AdminFeedback } from './types'

export default function FeedbackQualitySection({apiKey,onUnauthorized}: {
  apiKey: string; onUnauthorized: () => void
}) {
  const [days,setDays] = useState<7|30>(30)
  const [data,setData] = useState<AdminFeedback|null>(null)
  const [loading,setLoading] = useState(true)
  const [error,setError] = useState('')
  const reload = useCallback(async () => {
    setLoading(true); setError('')
    try { setData(await api.adminFeedback(apiKey,days)) }
    catch (err) {
      if (err instanceof ApiError && err.status===401) onUnauthorized()
      else setError(err instanceof Error ? err.message : 'Could not load feedback')
    } finally { setLoading(false) }
  },[apiKey,days,onUnauthorized])
  useEffect(() => { void reload() },[reload])
  const highest = Math.max(1,...(data?.daily ?? []).map(d=>d.up+d.down))
  return <section className="bg-white rounded-xl border border-slate-200 p-5 space-y-4" aria-label="Answer quality analytics">
    <div className="flex flex-wrap gap-3 items-center justify-between">
      <div><h2 className="font-semibold text-slate-900">Answer Feedback & Quality Signals</h2>
        <p className="text-xs text-slate-500 mt-1">Ratings reflect user sentiment, not independently verified correctness.</p></div>
      <div className="flex gap-2">
        <select aria-label="Feedback reporting period" value={days} onChange={e=>setDays(Number(e.target.value) as 7|30)} className="rounded-lg border border-slate-200 p-2 text-sm">
          <option value={7}>7 days</option><option value={30}>30 days</option>
        </select>
        <button type="button" onClick={()=>void reload()} className="border rounded-lg p-2 text-sm flex gap-1 items-center"><RefreshCw size={14}/> Refresh</button>
      </div>
    </div>
    {loading && <p role="status" className="text-sm text-slate-500">Loading feedback…</p>}
    {error && <p role="alert" className="notice-error">{error}</p>}
    {data && <>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          ['All-time ratings',data.all_time.total],
          ['Positive in period',data.period.up],
          ['Negative in period',data.period.down],
          ['Positive share',data.positive_rate===null?'N/A':`${(data.positive_rate*100).toFixed(1)}%`],
        ].map(([label,value])=><div key={String(label)} className="rounded-xl bg-slate-50 p-3 border border-slate-100"><p className="text-xs text-slate-500">{label}</p><p className="font-semibold text-xl mt-1">{value}</p></div>)}
      </div>
      <div>
        <h3 className="font-medium text-sm mb-3">Daily ratings (UTC)</h3>
        <div className="flex items-end gap-1 h-28" role="img" aria-label="Daily positive and negative feedback bars">
          {data.daily.map(day=><div key={day.date} className="flex-1 min-w-0 h-full flex flex-col justify-end" title={`${day.date}: ${day.up} positive, ${day.down} negative`}>
            <div className="bg-emerald-500" style={{height:`${day.up/highest*100}%`}}/>
            <div className="bg-rose-400" style={{height:`${day.down/highest*100}%`}}/>
          </div>)}
        </div>
        <div className="flex gap-4 text-xs text-slate-500 mt-2"><span className="flex gap-1 items-center"><ThumbsUp size={13}/> Positive</span><span className="flex gap-1 items-center"><ThumbsDown size={13}/> Negative</span></div>
      </div>
      <div className="grid md:grid-cols-2 gap-4">
        <div><h3 className="font-medium text-sm mb-2">Negative feedback reasons</h3>
          {data.downvote_reasons.length === 0 ? <p className="text-xs text-slate-500">No negative ratings in this period.</p> :
            <div className="space-y-2">{data.downvote_reasons.map(item=><div className="flex justify-between text-sm" key={item.reason}><span className="capitalize">{item.reason}</span><span className="font-medium">{item.count}</span></div>)}</div>}
        </div>
        <div><h3 className="font-medium text-sm mb-2">Recent negative ratings</h3>
          {data.recent_downvotes.length===0 ? <p className="text-xs text-slate-500">None recorded.</p> :
            <div className="space-y-2">{data.recent_downvotes.map((item,i)=><div key={`${item.username}-${i}`} className="text-sm flex justify-between gap-2"><span>{item.username} · {item.reason || 'No reason'}</span><span className="text-xs text-slate-500">{new Date(item.created_at).toLocaleDateString()}</span></div>)}</div>}
        </div>
      </div>
      <p className="text-xs text-slate-500">Private questions, answers and source passages are never included in this report. All-time totals begin when this feature is installed.</p>
    </>}
  </section>
}
