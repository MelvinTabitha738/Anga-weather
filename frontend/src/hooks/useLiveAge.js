import { useEffect, useState } from 'react'

/** How often the displayed age is recomputed. */
const TICK_MS = 15000

/**
 * A data age that keeps counting while the page stays open.
 *
 * `meta.age_seconds` is a snapshot taken when the server built the response.
 * On its own it freezes: a tab left open for an hour still claims the reading
 * is "just now", which is precisely the kind of overstated freshness the rest
 * of this app goes out of its way to avoid.
 *
 * This adds locally elapsed time to that server figure.
 *
 * Elapsed time is measured from a local timestamp taken when the payload
 * arrived, NOT by comparing `now` against `meta.fetched_at`. Those are two
 * different clocks: a device whose time is wrong by ten minutes would
 * otherwise report a ten-minute error, or a negative age. Measuring only the
 * delta on one clock is immune to skew.
 *
 * The timer resets whenever a new payload arrives.
 */
export function useLiveAge(meta) {
  const baseAge = Number(meta?.age_seconds)
  const anchor = Number.isFinite(baseAge) && baseAge >= 0 ? baseAge : 0

  // Identifies one payload. `status` is included so a refresh that returns the
  // same fetched_at (a cache hit) still restarts the count honestly.
  const payloadKey = `${meta?.fetched_at ?? ''}|${meta?.status ?? ''}`

  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    setElapsed(0)
    const startedAt = Date.now()
    const id = setInterval(() => {
      setElapsed(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)))
    }, TICK_MS)
    return () => clearInterval(id)
  }, [payloadKey])

  return anchor + elapsed
}
