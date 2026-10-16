import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { CreditCard, RefreshCw } from 'lucide-react'
import { api, ApiError } from './api'
import type { AdminBudgets } from './types'

interface Props { apiKey: string; onUnauthorized: () => void }

function decimalLimit(value: string): string | null {
  const input = value.trim()
  if (!input) return null // blank means unlimited
  if (!/^(?:\d+)(?:\.\d{1,12})?$/.test(input) || Number(input) > 1_000_000) {
    throw new Error('Use a nonnegative credit amount (up to 12 decimal places), or leave blank for unlimited')
  }
  return input
}

function friendlyError(err: unknown): string {
  return err instanceof Error ? err.message : 'Could not update budget'
}

function CreditLabel({value}: {value: string | null}) {
  return <span className="tabular-nums">{value === null ? 'Unlimited' : `${value} credits`}</span>
}

export function BudgetSection({apiKey, onUnauthorized}: Props) {
  const [data, setData] = useState<AdminBudgets | null>(null)
  const [tenantLimit, setTenantLimit] = useState('')
  const [reserve, setReserve] = useState('0.01')
  const [paused, setPaused] = useState(false)
  const [editingUser, setEditingUser] = useState<number | null>(null)
  const [userLimit, setUserLimit] = useState('')
  const [userPaused, setUserPaused] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setError('')
    try {
      const next = await api.adminBudgets(apiKey)
      setData(next)
      setTenantLimit(next.tenant.monthly_limit_credits ?? '')
      setReserve(next.tenant.reservation_credits)
      setPaused(next.tenant.paused)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onUnauthorized()
      setError(friendlyError(err))
    }
  }, [apiKey, onUnauthorized])

  useEffect(() => { void load() }, [load])

  async function saveTenant(e: FormEvent) {
    e.preventDefault(); setBusy(true); setNotice(''); setError('')
    try {
      const limit = decimalLimit(tenantLimit)
      if (decimalLimit(reserve) === null || Number(reserve) <= 0) throw new Error('Reservation must be positive')
      await api.setTenantBudget(apiKey, {monthly_limit_credits: limit, paused, reservation_credits:reserve.trim()})
      setNotice('Tenant budget saved'); await load()
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onUnauthorized()
      setError(friendlyError(err))
    } finally { setBusy(false) }
  }

  async function saveUser(e: FormEvent) {
    e.preventDefault(); if (editingUser === null) return
    setBusy(true); setNotice(''); setError('')
    try {
      await api.setUserBudget(apiKey, editingUser,
        {monthly_limit_credits: decimalLimit(userLimit), paused:userPaused})
      setEditingUser(null); setNotice('User budget saved'); await load()
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onUnauthorized()
      setError(friendlyError(err))
    } finally { setBusy(false) }
  }

  return <section aria-label="Credit budgets" className="bg-white rounded-xl border border-slate-200 p-5 space-y-4">
    <div className="flex items-center justify-between gap-2">
      <h2 className="font-semibold text-lg flex items-center gap-2"><CreditCard size={20}/> Monthly credit budgets</h2>
      <button type="button" className="text-sm border rounded-lg px-3 py-2 flex gap-2" onClick={() => void load()}><RefreshCw size={16}/> Refresh</button>
    </div>
    <p className="text-xs text-slate-600">Calendar month in UTC. New budgets are unlimited until configured. Credits shown are application-observed, not the provider account balance.</p>
    {error && <p role="alert" className="notice-error">{error}</p>}
    {notice && <p role="status" className="notice-success">{notice}</p>}
    {data && <>
      {data.tenant.monthly_limit_credits !== null &&
       (Number(data.tenant.spent_credits) + Number(data.tenant.reserved_credits)) / Math.max(Number(data.tenant.monthly_limit_credits), 0.000000000001) >= 0.8 &&
       <p role="status" className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-900">
         Tenant has used or reserved at least 80% of its monthly allowance. New requests will be blocked when the remaining allowance cannot cover one reservation.
       </p>}
      <div className="bg-slate-50 rounded-xl p-4 grid grid-cols-2 lg:grid-cols-4 gap-3 text-sm">
        <div>Spent this month<strong className="block text-lg">{data.tenant.spent_credits}</strong></div>
        <div>Reserved / unknown<strong className="block text-lg">{data.tenant.reserved_credits}</strong></div>
        <div>Remaining<strong className="block text-lg"><CreditLabel value={data.tenant.remaining_credits}/></strong></div>
        <div>Unknown-cost calls<strong className="block text-lg">{data.tenant.unknown_cost_requests}</strong></div>
      </div>
      <form onSubmit={e => void saveTenant(e)} className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
        <label className="text-sm">Tenant monthly limit (credits)
          <input aria-label="Tenant monthly limit" type="text" inputMode="decimal" placeholder="Unlimited" value={tenantLimit} onChange={e=>setTenantLimit(e.target.value)} className="block w-full p-2 mt-1 rounded-md border" />
        </label>
        <label className="text-sm">Per-request reservation (credits)
          <input aria-label="Per-request reservation" type="text" inputMode="decimal" value={reserve} onChange={e=>setReserve(e.target.value)} className="block w-full p-2 mt-1 rounded-md border" />
        </label>
        <label className="text-sm flex items-center gap-2 pb-2"><input type="checkbox" checked={paused} onChange={e=>setPaused(e.target.checked)}/> Pause OpenRouter for tenant</label>
        <button disabled={busy} type="submit" className="btn-primary">Save tenant budget</button>
      </form>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead><tr className="border-b text-left"><th className="py-2">User</th><th>Monthly limit</th><th>Used</th><th>Reserved</th><th>Status</th><th>Action</th></tr></thead>
          <tbody>{data.users.map(user=><tr key={user.user_id} className="border-b border-slate-100">
            <td className="py-3">{user.username}<span className="block text-xs text-slate-500">{user.email}</span></td>
            <td><CreditLabel value={user.monthly_limit_credits}/></td>
            <td>{user.spent_credits}</td><td>{user.reserved_credits}</td>
            <td>{user.paused ? 'Paused' : user.unknown_cost_requests ? 'Unreported costs' : user.monthly_limit_credits !== null && (Number(user.spent_credits)+Number(user.reserved_credits)) / Math.max(Number(user.monthly_limit_credits), 0.000000000001) >= .8 ? '80%+ used' : 'Active'}</td>
            <td><button type="button" className="text-indigo-700 underline" onClick={()=>{
              setEditingUser(user.user_id); setUserLimit(user.monthly_limit_credits ?? ''); setUserPaused(user.paused)
            }}>Edit</button></td>
          </tr>)}</tbody>
        </table>
      </div>
      {editingUser !== null && <form onSubmit={e=>void saveUser(e)} className="border rounded-lg p-4 space-y-3">
        <h3 className="font-semibold">Edit user #{editingUser}</h3>
        <label className="text-sm block">Monthly user limit (credits)
          <input aria-label="User monthly limit" value={userLimit} onChange={e=>setUserLimit(e.target.value)} placeholder="Unlimited" className="block border rounded-lg p-2 mt-1 w-full"/>
        </label>
        <label className="flex gap-2 items-center text-sm"><input type="checkbox" checked={userPaused} onChange={e=>setUserPaused(e.target.checked)}/> Pause this user's OpenRouter requests</label>
        <div className="flex gap-2"><button disabled={busy} type="submit" className="btn-primary">Save user budget</button><button type="button" onClick={()=>setEditingUser(null)} className="border rounded-lg px-3 py-2">Cancel</button></div>
      </form>}
      <p className="text-xs text-amber-800">These are pre-request guardrails, not a hard provider billing cap. A request may cost more than its reservation. A missing provider cost retains its reservation. Configure OpenRouter key-level limits as a second layer.</p>
    </>}
  </section>
}
