import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { money, number } from '../lib/format'

const paths = {
  chevron: 'm9 5 7 7-7 7',
  down: 'm6 9 6 6 6-6',
  close: 'm6 6 12 12 M6 18 18 6',
  menu: 'M4 6h16 M4 12h16 M4 18h16',
}
export function Icon({ name, size = 20, ...props }) { return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}><path d={paths[name]} /></svg> }
export function Brand() { return <div className="brand">BiteStream</div> }
export function Badge({ status, children }) { return <span className={`badge ${String(status || '').toLowerCase()}`}>{children || { PREPARING: 'Preparing', DELIVERING: 'Delivering', DELIVERED: 'Delivered', DEBIT: 'Debit', CREDIT: 'Credit' }[status] || status}</span> }
export function PageHeader({ title, description, actions }) { return <header className="page-header"><div><h1>{title}</h1><p>{description}</p></div>{actions && <div className="page-actions">{actions}</div>}</header> }
export function Stat({ label, value, note, accent }) { return <div className={`stat-card ${accent ? 'accent' : ''}`}><div className="stat-top"><span>{label}</span></div><strong>{value}</strong><div className="stat-note">{note}</div></div> }
export function Panel({ title, description, action, children, className = '' }) { return <section className={`panel ${className}`}><div className="panel-heading"><div><h2>{title}</h2>{description && <p>{description}</p>}</div>{action}</div>{children}</section> }
export function ResourceState({ resource, empty, emptyTitle = 'Nothing here yet', emptyText = 'Try changing your search or filters.' }) {
  if (resource.loading) return <div className="resource-state" role="status"><span className="spinner"/><h3>Loading…</h3><p>Fetching the latest data.</p></div>
  if (resource.error) return <div className="resource-state error" role="alert"><h3>We couldn’t load this</h3><p>{resource.error.message}</p><button className="button secondary" onClick={resource.reload}>Try again</button></div>
  if (empty) return <div className="resource-state"><h3>{emptyTitle}</h3><p>{emptyText}</p></div>
  return null
}
export function Pagination({ page, total, limit = 8, onChange }) {
  const pages = Math.max(1, Math.ceil(total / limit))
  return <div className="pagination"><span>Showing <b>{total ? (page - 1) * limit + 1 : 0}–{Math.min(page * limit, total)}</b> of <b>{number(total)}</b> results</span><div><button aria-label="Previous page" disabled={page <= 1} onClick={() => onChange(page - 1)}><Icon name="chevron" className="rotate" size={15}/></button>{Array.from(new Set([1, page - 1, page, page + 1, pages].filter((p) => p > 0 && p <= pages))).map((p, i, a) => <span key={p}>{i > 0 && p - a[i - 1] > 1 && <span className="pagination-gap">…</span>}<button className={page === p ? 'current' : ''} aria-label={`Page ${p}`} aria-current={page === p ? 'page' : undefined} onClick={() => onChange(p)}>{p}</button></span>)}<button aria-label="Next page" disabled={page >= pages} onClick={() => onChange(page + 1)}><Icon name="chevron" size={15}/></button></div></div>
}
export function Modal({ title, onClose, children }) {
  const dialog = useRef(null)
  useEffect(() => {
    const previous = document.activeElement
    const oldOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    dialog.current?.focus()
    const keydown = (event) => {
      if (event.key === 'Escape') onClose()
      if (event.key === 'Tab') {
        const elements = dialog.current?.querySelectorAll('button, a[href], input, select, textarea, [tabindex="0"]')
        if (!elements?.length) return
        if (event.shiftKey && document.activeElement === elements[0]) { event.preventDefault(); elements[elements.length - 1].focus() }
        else if (!event.shiftKey && document.activeElement === elements[elements.length - 1]) { event.preventDefault(); elements[0].focus() }
      }
    }
    document.addEventListener('keydown', keydown)
    return () => { document.body.style.overflow = oldOverflow; document.removeEventListener('keydown', keydown); previous?.focus() }
  }, [onClose])
  return createPortal(<div className="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}><div className="modal" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={dialog}><div className="modal-heading"><h2>{title}</h2><button className="icon-button" aria-label="Close details" onClick={onClose}><Icon name="close"/></button></div>{children}</div></div>, document.body)
}
export function Notice({ children, type = 'info' }) { return <div className={`notice ${type}`} role={type === 'error' ? 'alert' : 'status'}><div>{children}</div></div> }
export function BalanceCard({ user }) { return <div className="balance-card"><div><span>Available wallet balance</span></div><strong>{money(user?.wallet_balance)}</strong><span>{user?.name || 'Select a customer'}</span></div> }
