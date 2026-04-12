/**
 * hooks/useApi.ts
 * Generic hook for calling any api.* function with loading/error state.
 * When VITE_USE_MOCKS=true, the mockFn is called instead of the apiFn.
 *
 * Usage:
 *   const { data, loading, error, reload } = useApi(
 *     () => api.thermal.zones(),
 *     () => mockThermalZones(),
 *   )
 */
import { useState, useEffect, useCallback } from 'react'
import { USE_MOCKS } from '../mocks'

export interface ApiState<T> {
  data: T | null
  loading: boolean
  error: string | null
  reload: () => void
}

export function useApi<T>(
  apiFn: () => Promise<T>,
  mockFn: () => T,
  deps: unknown[] = [],
): ApiState<T> {
  const [data, setData]       = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      if (USE_MOCKS) {
        // Simulate network delay in mock mode for realism
        await new Promise(r => setTimeout(r, 300))
        setData(mockFn())
      } else {
        setData(await apiFn())
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setLoading(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => { load() }, [load])

  return { data, loading, error, reload: load }
}

/** Polling variant — re-fetches every `intervalMs` milliseconds */
export function usePollingApi<T>(
  apiFn: () => Promise<T>,
  mockFn: () => T,
  intervalMs: number,
  deps: unknown[] = [],
): ApiState<T> {
  const state = useApi(apiFn, mockFn, deps)

  useEffect(() => {
    const id = setInterval(state.reload, intervalMs)
    return () => clearInterval(id)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs])

  return state
}
