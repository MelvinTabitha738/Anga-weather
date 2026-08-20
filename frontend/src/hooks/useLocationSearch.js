import { useEffect, useRef, useState } from 'react'

import { searchLocations } from '../api/client'

/** Short enough to feel instant, long enough not to fire on every keystroke. */
const DEBOUNCE_MS = 110

/**
 * Debounced Kenyan location autocomplete.
 *
 * Searching hits PostgreSQL on our backend and never Weather-AI, so typing
 * costs no upstream quota. The debounce spares our own API, not the provider's.
 *
 * `resultsQuery` is the important part of the contract: it records WHICH query
 * the current results belong to. Without it a caller cannot tell fresh results
 * from the previous query's, and pressing Enter mid-debounce would act on stale
 * matches - selecting the wrong town, or appearing to need several presses
 * before it "took". Callers compare `resultsQuery` against what is typed and
 * fall back to submitting the raw text when they differ.
 */
export function useLocationSearch(query) {
  const [state, setState] = useState({ results: [], resultsQuery: null })
  const [isSearching, setIsSearching] = useState(false)
  const controllerRef = useRef(null)

  useEffect(() => {
    const trimmed = query.trim()

    // An empty box has nothing to search for; resolve immediately so the
    // caller is never left waiting on a debounce that will not produce
    // anything.
    if (!trimmed) {
      controllerRef.current?.abort()
      setState({ results: [], resultsQuery: '' })
      setIsSearching(false)
      return undefined
    }

    setIsSearching(true)

    const timer = setTimeout(async () => {
      controllerRef.current?.abort()
      const controller = new AbortController()
      controllerRef.current = controller

      try {
        const data = await searchLocations(trimmed, { signal: controller.signal })
        setState({ results: data.results || [], resultsQuery: trimmed })
      } catch (error) {
        if (error?.name === 'AbortError') return
        // A failed suggestion lookup is not worth interrupting the user for -
        // they can still submit the name they typed, and the backend will
        // resolve or reject it.
        setState({ results: [], resultsQuery: trimmed })
      } finally {
        setIsSearching(false)
      }
    }, DEBOUNCE_MS)

    return () => {
      clearTimeout(timer)
      controllerRef.current?.abort()
    }
  }, [query])

  return { ...state, isSearching }
}
