import { useState } from 'react'
import { request } from '../lib/api'
import { amountProblem } from '../lib/contracts'
import { money } from '../lib/format'
import { Notice, Panel } from './ui'

export default function WalletTopUp({ actorId, balance, update }) {
  const [amount, setAmount] = useState('500'), [busy, setBusy] = useState(false)
  const [error, setError] = useState(''), [result, setResult] = useState(null)
  const problem = amountProblem(amount, { balance })
  async function submit(event) {
    event.preventDefault()
    if (problem) return
    setBusy(true); setError(''); setResult(null)
    try {
      const data = await request(`/users/${actorId}/topup`, { method: 'POST', body: { amount: Number(amount) } })
      setResult(data); update('Wallet topped up. A credit entry was recorded.')
    } catch (error) { setError(error.message) } finally { setBusy(false) }
  }
  return <Panel title="Top up this wallet" description="Add funds to the selected customer’s wallet.">
    <form className="topup-form" onSubmit={submit}>
      <label className="form-field"><span>Top-up amount (INR)</span><input aria-label="Top-up amount" type="number" min="0.01" max="99999999.99" step="0.01" required value={amount} onChange={(event) => setAmount(event.target.value)}/></label>
      {problem && amount !== '' && <small className="field-error" role="alert">{problem}</small>}
      <button className="button secondary" disabled={busy || Boolean(problem)}>{busy ? 'Adding funds…' : 'Add funds'}</button>
      {error && <Notice type="error">{error}</Notice>}
      {result && <Notice type="success">Wallet balance: {money(result.user.wallet_balance)}. Credit recorded: {money(result.audit_entry.amount_changed)}.</Notice>}
    </form>
  </Panel>
}
