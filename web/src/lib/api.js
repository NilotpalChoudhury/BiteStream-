import { apiError, normalizeResponse } from './contracts.js'

const env = import.meta.env || {}
export const query = (values = {}) => new URLSearchParams(Object.entries(values).filter(([, value]) => value !== '' && value != null)).toString()
export async function request(path, { method = 'GET', body, signal } = {}) {
  const base = (env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')
  let response
  try { response = await fetch(`${base}${path}`, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined, signal }) }
  catch (error) { if (error.name === 'AbortError') throw error; throw new Error('Unable to reach the BiteStream API. Check the server connection and try again.', { cause: error }) }
  let data
  try { data = await response.json() } catch { throw new Error('The server returned an unreadable response. Please try again.') }
  if (!response.ok) throw apiError(data)
  return normalizeResponse(path, data)
}
export const itemsOf = (data) => Array.isArray(data) ? data : data?.items || []
