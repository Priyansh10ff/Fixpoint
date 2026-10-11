import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'

const HEALTH_INTERVAL_MS = 15000

/** Polls /api/health and loads /api/providers once (with manual refresh). */
export function useBackend() {
  const [health, setHealth] = useState({ state: 'loading' })
  const [providers, setProviders] = useState({ state: 'loading', list: [], defaultProvider: null })

  useEffect(() => {
    let cancelled = false
    let controller
    const tick = async () => {
      controller = new AbortController()
      try {
        const data = await api.health(controller.signal)
        if (!cancelled) setHealth({ state: 'ok', ...data })
      } catch (err) {
        if (!cancelled && err.name !== 'AbortError') setHealth({ state: 'offline', error: err.message })
      }
    }
    tick()
    const id = setInterval(tick, HEALTH_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
      controller?.abort()
    }
  }, [])

  const refreshProviders = useCallback(async () => {
    setProviders((p) => ({ ...p, state: 'loading' }))
    try {
      const data = await api.providers()
      setProviders({ state: 'ok', list: data.providers, defaultProvider: data.default_provider })
    } catch (err) {
      setProviders({ state: 'error', list: [], defaultProvider: null, error: err.message })
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
    refreshProviders()
  }, [refreshProviders])

  return { health, providers, refreshProviders }
}
