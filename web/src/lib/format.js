export const money = (value, compact = false) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: compact ? 1 : 2, minimumFractionDigits: compact ? 0 : 2, ...(compact ? { notation: 'compact' } : {}) }).format(Number(value) || 0)
export const number = (value) => new Intl.NumberFormat('en-IN').format(Number(value) || 0)
export const shortId = (value) => value ? `#${value.slice(-8).toUpperCase()}` : '—'
export const dateTime = (value) => value && !Number.isNaN(new Date(value).getTime()) ? new Date(value).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata' }) : 'Not available'
export const date = (value) => value ? new Date(value).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' }) : '—'
export const initials = (name = '') => name.replace(/\([^)]*\)/g, '').split(' ').filter(Boolean).slice(0, 2).map((p) => p[0]).join('')
