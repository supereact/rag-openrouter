import { useCallback, useEffect, useMemo, useState } from 'react'
import { BarChart3, RefreshCw } from 'lucide-react'
import { ApiError, api } from './api'
import type { AdminUsage, UsageUser } from './types'

function fmtCredits(value: string): string {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return number.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 10 })
}

function TotalCard({ title, value, subtitle }: { title: string; value: string; subtitle: string }) {
  return <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
    <p className="text-sm text-slate-500">{title}</p>
    <p className="text-2xl mt-2 font-semibold text-slate-900 tabular-nums">{fmtCredits(value)} <span className="text-sm font-normal text-slate-500">credits</span></p>
    <p className="mt-2 text-xs text-slate-500">{subtitle}</p>
  </div>
}

function UsageGraph({ data }: { data: AdminUsage['daily'] }) {
  const maximum = Math.max(0, ...data.map(d => Number(d.credits)))
  const columnWidth = 798 / Math.max(1, data.length)
  return <div>
    <svg viewBox="0 0 840 250" className="w-full h-auto" role="img" aria-label="Daily OpenRouter usage credits graph">
      {[0, .25, .5, .75, 1].map((pct) => {
        const y = 202 - pct * 170
        return <g key={pct}>
          <line x1="42" y1={y} x2="835" y2={y} stroke="#e2e8f0" strokeWidth="1" />
          <text x="36" y={y + 4} textAnchor="end" fontSize="10" fill="#64748b">{fmtCredits(String(maximum * pct))}</text>
        </g>
      })}
      {data.map((day, i) => {
        const amount = Number(day.credits)
        const h = maximum > 0 ? amount / maximum * 170 : 0
        const x = 45 + i * columnWidth
        const width = Math.max(3, columnWidth - (data.length > 7 ? 5 : 18))
        return <g key={day.date}>
          <rect x={x} y={202 - h} width={width} height={h} rx="2" fill="#4f46e5">
            <title>{day.date}: {day.credits} credits · {day.requests} requests</title>
          </rect>
          {(data.length <= 7 || i % 5 === 0 || i === data.length - 1) &&
            <text x={x + width / 2} y="220" textAnchor="middle" fontSize="10" fill="#64748b">{day.date.slice(5)}</text>}
        </g>
      })}
    </svg>
    <p className="text-xs text-slate-500">UTC calendar days. Days with no reported cost appear at zero; see coverage below.</p>
  </div>
}

export function UsageSection({ apiKey, onUnauthorized }: {apiKey: string; onUnauthorized: () => void}) {
  const [data, setData] = useState<AdminUsage | null>(null)
  const [days, setDays] = useState<7 | 30>(30)
  const [sort, setSort] = useState<'overall' | 'week'>('overall')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    setLoading(true); setError('')
    try { setData(await api.adminUsage(apiKey, days)) }
    catch (err) {
      if (err instanceof ApiError && err.status === 401) onUnauthorized()
      setError(err instanceof Error ? err.message : 'Could not load usage')
    } finally { setLoading(false) }
  }, [apiKey, days, onUnauthorized])

  useEffect(() => { void reload() }, [reload])

  const users = useMemo(() => [...(data?.users ?? [])].sort((a: UsageUser, b: UsageUser) =>
    Number(sort === 'overall' ? b.overall_credits : b.week_credits) -
    Number(sort === 'overall' ? a.overall_credits : a.week_credits) || a.username.localeCompare(b.username)),
  [data, sort])

  return <section className="space-y-4" aria-label="OpenRouter usage">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex gap-2 items-center"><BarChart3 size={20} className="text-indigo-600"/><h2 className="text-lg font-semibold">OpenRouter Usage</h2></div>
      <button type="button" aria-label="Refresh usage" onClick={() => void reload()} className="border border-slate-300 rounded-lg px-3 py-2 text-sm flex gap-1 items-center">
        <RefreshCw size={15}/> Refresh usage
      </button>
    </div>
    {loading && <p role="status" className="text-sm text-slate-500">Loading usage…</p>}
    {error && <p role="alert" className="notice-error">{error}</p>}
    {data && <>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <TotalCard title="Overall OpenRouter usage" value={data.overall_credits} subtitle="Total reported credits since usage tracking began" />
        <TotalCard title="This week" value={data.week_credits} subtitle={`Week starts Monday ${data.week_starts_utc} (UTC)`} />
      </div>
      <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-3">
        <div className="flex flex-wrap justify-between gap-2 items-center">
          <h3 className="font-semibold">Total OpenRouter usage by day</h3>
          <div className="flex gap-2" role="group" aria-label="Usage chart range">
            <button type="button" aria-pressed={days === 7} onClick={() => setDays(7)} className={`text-sm rounded-lg px-3 py-1.5 ${days === 7 ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-700'}`}>7 days</button>
            <button type="button" aria-pressed={days === 30} onClick={() => setDays(30)} className={`text-sm rounded-lg px-3 py-1.5 ${days === 30 ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-700'}`}>30 days</button>
          </div>
        </div>
        <UsageGraph data={data.daily}/>
      </div>
      <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-3">
        <div className="flex flex-wrap justify-between gap-2 items-center"><h3 className="font-semibold">Usage by user</h3>
          <label className="text-sm text-slate-600">Sort by <select aria-label="Sort usage" value={sort} onChange={e => setSort(e.target.value as 'overall'|'week')} className="border border-slate-300 rounded-md p-1.5 ml-2">
            <option value="overall">All time</option><option value="week">This week</option>
          </select></label>
        </div>
        <div className="overflow-x-auto"><table className="min-w-full text-sm">
          <thead><tr className="border-b text-left text-slate-600"><th className="py-3 px-2">User</th><th className="py-3 px-2 text-right">Overall (credits)</th><th className="py-3 px-2 text-right">This week (credits)</th><th className="py-3 px-2 text-right">Tracked calls</th></tr></thead>
          <tbody>{users.map(u => <tr key={u.user_id} className="border-b border-slate-100">
            <td className="py-3 px-2"><span className="font-semibold">{u.username}</span><span className="block text-xs text-slate-500">{u.email ?? 'API-key-only user'}{u.is_active ? '' : ' · Disabled'}</span></td>
            <td className="py-3 px-2 text-right tabular-nums">{fmtCredits(u.overall_credits)}</td>
            <td className="py-3 px-2 text-right tabular-nums">{fmtCredits(u.week_credits)}</td>
            <td className="py-3 px-2 text-right tabular-nums">{u.requests}</td>
          </tr>)}</tbody>
        </table></div>
        <p className="text-xs text-slate-500">Cost coverage: {data.cost_reported_requests} of {data.requests} recorded OpenRouter calls reported a cost. Unreported costs are excluded, so totals may be understated.</p>
      </div>
      <p className="text-xs text-slate-500">These figures track provider-reported usage for this app and tenant since the migration—not your complete OpenRouter account balance or prior historical spend. The graph and weekly totals use UTC.</p>
    </>}
  </section>
}
