import { useEffect, useRef, useState } from 'react'

import { searchLocations } from '../api/client'

const DEBOUNCE_MS = 180

/**
 * Debounced Kenyan location autocomplete.
 *
 * Searching hits PostgreSQL on our backend and never Weather-AI, so typing
 * costs no upstream quota. The debounce is here to spare our own API, not the
 * provider's.
 */
export function useLocationSearch(query) {
  const [results, setResults] = useState([])
  const [isSearching, setIsSearching] = useState(false)
  const controllerRef = useRef(null)

  useEffect(() => {
    const timer = setTimeout(async () => {
      controllerRef.current?.abort()
      const controller = new AbortController()
      controllerRef.current = controller

      setIsSearching(true)
      try {
        const data = await searchLocations(query, { signal: controller.signal })
        setResults(data.results || [])
      } catch (error) {
        if (error?.name === 'AbortError') return
        // A failed suggestion lookup is not worth interrupting the user for -
        // they can still submit the name they typed.
        setResults([])
      } finally {
        setIsSearching(false)
      }
    }, DEBOUNCE_MS)

    return () => {
      clearTimeout(timer)
      controllerRef.current?.abort()
    }
  }, [query])

  return { results, isSearching }
}
