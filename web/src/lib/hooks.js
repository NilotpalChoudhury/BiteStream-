import { useEffect, useState } from 'react'
import { request } from './api'

export function useResource(path, revision = 0, interval = 0) {
  const [state, setState] = useState({ key: '', data: null, error: null })
  const [attempt, setAttempt] = useState(0)
  const key = `${path}:${revision}:${attempt}`
  useEffect(() => {
    if (!path) return
    const controller = new AbortController()
    let loading = false
    async function load() {
      if (loading || controller.signal.aborted) return
      loading = true
      try { const data = await request(path, { signal: controller.signal }); if (!controller.signal.aborted) setState({ key, data, error: null }) }
      catch (error) { if (error.name !== 'AbortError' && !controller.signal.aborted) setState({ key, data: null, error }) }
      finally { loading = false }
    }
    load()
    const timer = interval ? setInterval(load, interval) : null
    return () => { controller.abort(); if (timer) clearInterval(timer) }
  }, [path, key, interval])
  return { data: state.key === key ? state.data : null, error: state.key === key ? state.error : null, loading: Boolean(path) && state.key !== key, reload: () => setAttempt((n) => n + 1) }
}
export function useDebounce(value, delay = 250) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => { const timer = setTimeout(() => setDebounced(value), delay); return () => clearTimeout(timer) }, [value, delay])
  return debounced
}
