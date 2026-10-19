import {useCallback, useEffect, useRef, useState, type FormEvent} from 'react'
import {api} from './api'
import PageFrame from './PageFrame'
import Pagination from './Pagination'
import {useAdminResource} from './useAdminResource'
import type {CreditOrder} from './types'

const terminal = new Set(['finished', 'failed', 'expired', 'refunded'])
const pendingPayment = (order: CreditOrder) => !terminal.has(order.status)
const statusLabels: Record<string, string> = {creating: 'Creating payment', waiting: 'Awaiting payment',
  confirming: 'Confirming', confirmed: 'Confirmed', sending: 'Settling', partially_paid: 'Partially paid',
  finished: 'Paid', failed: 'Failed', expired: 'Expired', refunded: 'Refunded', review: 'Needs review'}
const displayCredit = (value: string) => {
  const [whole, fraction = ''] = value.split('.')
  const decimals = fraction.replace(/0+$/, '')
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (decimals ? `.${decimals}` : '')
}

export function creditQuote(value: string) {
  if (!/^\d{1,4}(\.\d{0,2})?$/.test(value)) return null
  const [whole, fraction = ''] = value.split('.')
  const cents = Number(whole) * 100 + Number(fraction.padEnd(2, '0'))
  if (cents < 1000 || cents > 100000) return null
  const fee = Math.floor((cents * 55 + 500) / 1000)
  return {credits: (cents / 100).toFixed(2), fee: (fee / 100).toFixed(2), total: ((cents + fee) / 100).toFixed(2)}
}

export default function CreditsPanel({apiKey, onUnauthorized}: {apiKey: string; onUnauthorized: () => void}) {
  const [orderPage, setOrderPage] = useState(1)
  const [orderSize, setOrderSize] = useState(20)
  const [transactionPage, setTransactionPage] = useState(1)
  const [transactionSize, setTransactionSize] = useState(20)
  const [amount, setAmount] = useState('10.00')
  const [network, setNetwork] = useState('usdttrc20')
  const [notice, setNotice] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const checkout = useRef<{details: string; key: string} | null>(null)
  const loader = useCallback(async (signal?: AbortSignal) => {
    const [summary, orders, transactions] = await Promise.all([
      api.credits(apiKey, signal), api.creditOrders(apiKey, orderPage, orderSize, signal),
      api.creditTransactions(apiKey, transactionPage, transactionSize, signal),
    ])
    return {summary, orders, transactions}
  }, [apiKey, orderPage, orderSize, transactionPage, transactionSize])
  const {data, error, loading, pending, stale, refresh, refreshInBackground, save} =
    useAdminResource(loader, onUnauthorized, 'Access denied. You cannot view these credits.')
  const quote = creditQuote(amount)
  const hasPending = data?.orders.items.some(pendingPayment) ?? false
  useEffect(() => {
    if (!hasPending) return
    const poll = () => {
      if (document.visibilityState !== 'hidden' && navigator.onLine !== false) void refreshInBackground()
    }
    const interval = window.setInterval(poll, 5000)
    document.addEventListener('visibilitychange', poll)
    window.addEventListener('online', poll)
    return () => {
      window.clearInterval(interval)
      document.removeEventListener('visibilitychange', poll)
      window.removeEventListener('online', poll)
    }
  }, [hasPending, refreshInBackground])
  useEffect(() => {
    if (data && orderPage !== data.orders.page) setOrderPage(data.orders.page)
    if (data && transactionPage !== data.transactions.page) setTransactionPage(data.transactions.page)
  }, [data, orderPage, transactionPage])

  async function purchase(event: FormEvent) {
    event.preventDefault()
    if (!quote || pending || !data?.summary.payments_enabled) return
    const details = `${quote.credits}:${network}`
    if (!checkout.current || checkout.current.details !== details) {
      checkout.current = {details, key: crypto.randomUUID()}
    }
    const requestKey = checkout.current.key
    setNotice('')
    const ok = await save(async () => {
      await api.purchaseCredits(apiKey, quote.credits, network, requestKey)
      return loader()
    })
    if (ok) {
      checkout.current = null
      setOrderPage(1)
      setNotice('Payment order ready. Open its payment details below.')
    }
  }
  async function check(order: CreditOrder) {
    setNotice('')
    const ok = await save(async () => {await api.checkCreditOrder(apiKey, order.id); return loader()})
    if (ok) setNotice('Payment status checked.')
  }
  async function copy(value: string) {
    try {await navigator.clipboard.writeText(value); setNotice('Payment address copied.')}
    catch {setNotice('Select and copy the payment address below.')}
  }

  return <PageFrame title="Credits" subtitle="Add USDT funds to your personal balance and track credit usage."
    actions={<button type="button" className="btn-primary" disabled={pending} onClick={() => void refresh()}>Refresh credits</button>}>
    <div className="max-w-6xl mx-auto px-4 sm:px-8 py-7 space-y-6">
      {loading && <p role="status">{data ? 'Refreshing credits…' : 'Loading credits…'}</p>}
      {error && <p role="alert" className="notice-error">{error}{stale && ' Previously loaded balances may be out of date.'}</p>}
      {notice && <p role="status" className="notice-success">{notice}</p>}
      {data && <>
        {data.summary.mode === 'sandbox' && <p className="notice-error">Sandbox mode: no real payment is required. Test credits cannot pay for real AI usage.</p>}
        {!data.summary.payments_enabled && <p className="text-sm text-slate-600">USDT top-ups are not enabled. Your administrator must configure payments before you can add credits.</p>}
        {data.summary.mode === 'live' && !data.summary.usage_enforced && <p className="text-sm text-slate-600">Prepaid usage deductions are not enabled yet.</p>}
        <div className="grid sm:grid-cols-3 gap-4">
          {[['Available credits', data.summary.available], ['Reserved credits', data.summary.reserved], ['Total balance', data.summary.balance]].map(([label, value]) =>
            <div key={label} className="bg-white border border-slate-200 rounded-xl p-5"><p className="text-sm text-slate-500">{label}</p>
              <p className="text-2xl font-semibold mt-2">{data.summary.mode === 'disabled' ? '—' : displayCredit(value)}</p></div>)}
        </div>
        <p className="text-sm text-slate-500">Reserved credits cover requests in progress or awaiting reliable provider costs. Unreported costs stay reserved until reviewed.</p>
        <form onSubmit={event => void purchase(event)} className="bg-white border border-slate-200 rounded-xl p-5 space-y-4">
          <h2 className="font-semibold">Add credits with USDT</h2>
          <p className="text-sm text-slate-600">1 credit covers US$1 of reported provider cost. A 5.5% service fee applies once at purchase, rounded to the nearest cent.</p>
          <div className="flex flex-wrap gap-4">
            <label className="text-sm">Usable credits (USD)<input aria-label="Usable credits (USD)" inputMode="decimal" value={amount}
              disabled={pending} onChange={e => setAmount(e.target.value)} className="block border rounded-lg p-2 mt-1"/></label>
            <label className="text-sm">USDT network<select aria-label="USDT network" value={network} disabled={pending}
              onChange={e => setNetwork(e.target.value)} className="block border rounded-lg p-2 mt-1">
              {data.summary.networks.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
            </select></label>
          </div>
          {quote ? <div className="text-sm space-y-1"><p>Usable credit: <strong>US$ {quote.credits}</strong></p>
            <p>Service fee (5.5%): <strong>US$ {quote.fee}</strong></p><p>Total: <strong>US$ {quote.total}</strong>, quoted in USDT at checkout.</p></div>
            : <p className="text-sm text-rose-700">Enter between $10 and $1,000, with at most two decimal places.</p>}
          <p className="text-xs text-slate-500">Your wallet or exchange may charge a separate network fee. Use only the network shown on your payment order.</p>
          <button className="btn-primary" disabled={pending || !quote || !data.summary.payments_enabled}>
            {pending ? 'Please wait…' : data.summary.mode === 'sandbox' ? 'Create test payment' : 'Create USDT payment'}
          </button>
        </form>
        <section><h2 className="font-semibold mb-3">Payment history</h2>
          <div className="bg-white border rounded-xl overflow-x-auto"><table className="management-table" aria-label="Credit payments">
            <thead><tr>{['Date', 'Usable credits', 'Service fee', 'Total (USD)', 'Network', 'Status', 'Actions'].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead>
            <tbody>{data.orders.items.map(order => <tr key={order.id}>
              <td>{new Date(order.created_at).toLocaleString()}<div className="text-xs text-slate-500 break-all">{order.id}</div></td>
              <td>{order.credits}</td><td>{order.service_fee}</td><td>{order.total_usd}</td>
              <td>{data.summary.networks.find(option => option.id === order.network)?.label ?? order.network}</td>
              <td>{statusLabels[order.status] ?? order.status}{order.status === 'review' && <p className="text-xs max-w-48">This order needs review. Do not start another payment until its status is checked.</p>}</td>
              <td className="min-w-64"><button type="button" className="table-button" aria-label={`Payment details ${order.id}`}
                onClick={() => setExpanded(value => value === order.id ? null : order.id)}>Details</button>
                <button type="button" className="table-button ml-2" disabled={pending} onClick={() => void check(order)}>Check status</button>
                {expanded === order.id && <div className="mt-3 space-y-2 text-sm max-w-96">
                  {order.status === 'waiting' && order.pay_address && order.pay_amount &&
                    (!order.expires_at || Date.parse(order.expires_at) > Date.now()) ? <>
                    <p>{order.mode === 'sandbox' ? 'Test amount' : 'Send exactly'}: <strong>{order.pay_amount} USDT</strong></p>
                    <p className="font-semibold">{data.summary.networks.find(option => option.id === order.network)?.label ?? order.network} only</p>
                    <p className="break-all select-all">{order.pay_address}</p>
                    <button type="button" className="table-button" onClick={() => void copy(order.pay_address!)}>Copy address</button>
                    {order.expires_at && <p>Quote expires: {new Date(order.expires_at).toLocaleString()}</p>}
                    <p>Credit is added after full payment confirmation. Partial payments require review.</p>
                  </> : <p>{order.status === 'finished' ? 'Payment completed.' :
                    ['confirming', 'confirmed', 'sending'].includes(order.status) ? 'Payment detected. Awaiting settlement; do not send another payment.' :
                    'No active payment instructions. Check status or contact your administrator.'}</p>}
                </div>}
              </td></tr>)}</tbody></table>
            {data.orders.total === 0 && <p className="p-5 text-sm text-slate-500">No payments yet.</p>}</div>
          <Pagination page={data.orders.page} pageSize={orderSize} total={data.orders.total} disabled={pending}
            onPage={setOrderPage} onPageSize={size => {setOrderSize(size); setOrderPage(1)}}/>
        </section>
        <section><h2 className="font-semibold mb-3">Credit transactions</h2>
          <div className="bg-white border rounded-xl overflow-x-auto"><table className="management-table" aria-label="Credit transactions">
            <thead><tr><th scope="col">Date</th><th scope="col">Type</th><th scope="col">Credit change</th></tr></thead>
            <tbody>{data.transactions.items.map(transaction => <tr key={transaction.id}><td>{new Date(transaction.created_at).toLocaleString()}</td>
              <td>{transaction.kind}</td><td>{transaction.amount}</td></tr>)}</tbody></table>
            {data.transactions.total === 0 && <p className="p-5 text-sm text-slate-500">No credit transactions yet.</p>}</div>
          <Pagination page={data.transactions.page} pageSize={transactionSize} total={data.transactions.total} disabled={pending}
            onPage={setTransactionPage} onPageSize={size => {setTransactionSize(size); setTransactionPage(1)}}/>
        </section>
      </>}
    </div>
  </PageFrame>
}
