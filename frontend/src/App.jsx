import { useEffect, useMemo, useState } from 'react'

import Backdrop from './components/backdrop/Backdrop'
import Dashboard from './components/Dashboard'
import EmptyState from './components/EmptyState'
import ErrorState from './components/ErrorState'
import LoadingState from './components/LoadingState'
import SearchBar from './components/SearchBar'
import { searchLocations } from './api/client'
import { ERROR, LOADING, SUCCESS, useWeather } from './hooks/useWeather'
import { IDLE_THEME, resolveTheme } from './lib/weatherTheme'

const LAST_LOCATION_KEY = 'anga:last-location'

/**
 * Anga.
 *
 * Composition only: the backdrop reacts to the current weather state, and one
 * of four views renders above it. All caching that matters happens on the
 * server - the single localStorage value here just remembers which place the
 * user last opened.
 */
export default function App() {
  const [selection, setSelection] = useState(() => readLastLocation())
  const [starters, setStarters] = useState([])

  const { status, data, error, isRefreshing, refresh } = useWeather(selection?.slug)

  // A handful of prominent places for the first-run state. Comes from our own
  // gazetteer, so it costs nothing upstream.
  useEffect(() => {
    let cancelled = false
    searchLocations('', { limit: 6 })
      .then((response) => {
        if (!cancelled) setStarters(response.results || [])
      })
      .catch(() => {
        // Non-essential: the search box still works without these.
      })
    return () => {
      cancelled = true
    }
  }, [])

  const choose = (slug, label) => {
    const next = { slug, label }
    setSelection(next)
    writeLastLocation(next)
  }

  const clearSelection = () => {
    setSelection(null)
    writeLastLocation(null)
  }

  // The backdrop follows the last successful reading, so it does not fall back
  // to a neutral sky while a new location loads.
  const theme = useMemo(() => (data ? resolveTheme(data.current) : IDLE_THEME), [data])

  const showDashboard = selection && status === SUCCESS && data

  return (
    <div className="app">
      <Backdrop theme={theme} />

      <div className="shell">
        <header className="masthead">
          <button type="button" className="brand" onClick={clearSelection}>
            <span className="brand__mark">Anga</span>
            <span className="brand__tag">Weather for Kenya</span>
          </button>
          <SearchBar onSelect={choose} currentLabel={data?.location?.name} />
        </header>

        <main aria-busy={isRefreshing}>
          {!selection && <EmptyState suggestions={starters} onSelect={choose} />}

          {selection && status === LOADING && <LoadingState label={selection.label} />}

          {selection && status === ERROR && (
            <ErrorState error={error} onRetry={refresh} onBack={clearSelection} />
          )}

          {showDashboard && (
            <Dashboard data={data} onBack={clearSelection} onRefresh={refresh} />
          )}
        </main>

        <footer className="colophon">
          <span>
            Weather data from{' '}
            <a href="https://weather-ai.co/docs" target="_blank" rel="noreferrer noopener">
              Weather-AI
            </a>
            , served through a caching backend.
          </span>
          <span>Cached server-side to stay fast and within the provider&rsquo;s limits.</span>
        </footer>
      </div>
    </div>
  )
}

function readLastLocation() {
  try {
    const raw = window.localStorage.getItem(LAST_LOCATION_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    return parsed?.slug ? parsed : null
  } catch {
    // Private browsing, disabled storage, or corrupt JSON - none of which
    // should stop the app loading.
    return null
  }
}

function writeLastLocation(selection) {
  try {
    if (selection) {
      window.localStorage.setItem(LAST_LOCATION_KEY, JSON.stringify(selection))
    } else {
      window.localStorage.removeItem(LAST_LOCATION_KEY)
    }
  } catch {
    /* Not important enough to surface. */
  }
}
