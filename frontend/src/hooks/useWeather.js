import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchWeather } from '../api/client'

export const IDLE = 'idle'
export const LOADING = 'loading'
export const SUCCESS = 'success'
export const ERROR = 'error'

/**
 * Load weather for a location.
 *
 * Two behaviours worth noting:
 *
 * - Previous data is kept while a new request is in flight, so the backdrop
 *   does not flash back to neutral between locations. `isRefreshing` lets the
 *   UI show subtle progress instead of tearing the page down.
 * - Every request is abortable, and a superseded request is discarded rather
 *   than allowed to overwrite newer state.
 */
export function useWeather(location, { units = 'metric' } = {}) {
  const [state, setState] = useState({ status: IDLE, data: null, error: null })
  const [isRefreshing, setIsRefreshing] = useState(false)

  const controllerRef = useRef(null)
  // Guards against a slow earlier response landing after a newer one.
  const requestIdRef = useRef(0)

  const load = useCallback(
    async (targetLocation) => {
      if (!targetLocation) {
        setState({ status: IDLE, data: null, error: null })
        return
      }

      controllerRef.current?.abort()
      const controller = new AbortController()
      controllerRef.current = controller

      const requestId = ++requestIdRef.current

      setState((previous) => ({
        status: previous.data ? previous.status : LOADING,
        data: previous.data,
        error: null,
      }))
      setIsRefreshing(true)

      try {
        const data = await fetchWeather(targetLocation, { units, signal: controller.signal })
        if (requestId !== requestIdRef.current) return
        setState({ status: SUCCESS, data, error: null })
      } catch (error) {
        if (error?.name === 'AbortError') return
        if (requestId !== requestIdRef.current) return
        // On failure we drop stale data: showing an error banner over an
        // unrelated location's reading would be worse than a clean error.
        setState({ status: ERROR, data: null, error })
      } finally {
        if (requestId === requestIdRef.current) setIsRefreshing(false)
      }
    },
    [units],
  )

  useEffect(() => {
    load(location)
    return () => controllerRef.current?.abort()
  }, [location, load])

  const refresh = useCallback(() => load(location), [load, location])

  return { ...state, isRefreshing, refresh }
}
