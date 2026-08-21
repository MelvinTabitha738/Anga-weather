import { useEffect, useId, useRef, useState } from 'react'

import { useLocationSearch } from '../hooks/useLocationSearch'

/**
 * Kenyan location search.
 *
 * Built as an ARIA combobox rather than a styled text input: arrow keys move
 * through suggestions, Enter selects, Escape closes, and screen readers are
 * told what is happening.
 *
 * THE STALE-RESULT RULE
 * ---------------------
 * Suggestions are debounced, so at the moment Enter is pressed the visible
 * results may still belong to an earlier query. Acting on them selects the
 * wrong town and makes the box feel like it needs several presses before it
 * "takes". So Enter only trusts the suggestion list when `resultsQuery`
 * matches what is actually typed; otherwise it submits the raw text and lets
 * the backend resolve it - which it can, because normalisation and alias
 * lookup happen server-side. The first Enter is always correct.
 *
 * Suggestions come from our own gazetteer, so they cost no upstream quota -
 * which is why we can afford to search as the user types.
 */
export default function SearchBar({ onSelect, currentLabel, variant = 'compact', placeholder }) {
  const [query, setQuery] = useState('')
  const [isOpen, setIsOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)

  const { results, resultsQuery, isSearching } = useLocationSearch(query)
  const containerRef = useRef(null)
  const inputRef = useRef(null)
  const listId = useId()

  const trimmed = query.trim()
  // Are the visible suggestions actually for what is typed right now?
  const resultsAreCurrent = resultsQuery === trimmed

  useEffect(() => {
    const onPointerDown = (event) => {
      if (!containerRef.current?.contains(event.target)) setIsOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [])

  useEffect(() => {
    setActiveIndex(-1)
  }, [results])

  const reset = () => {
    setQuery('')
    setIsOpen(false)
    setActiveIndex(-1)
  }

  const choose = (location) => {
    if (!location) return
    onSelect(location.slug, location.label)
    reset()
    inputRef.current?.blur()
  }

  /** Enter, or the Search button. Never acts on stale suggestions. */
  const submit = () => {
    if (!trimmed) return

    if (activeIndex >= 0 && results[activeIndex]) {
      choose(results[activeIndex])
      return
    }

    if (resultsAreCurrent && results.length) {
      choose(results[0])
      return
    }

    // Results are still in flight, or there are none. Send what was typed:
    // the backend normalises it, resolves aliases, and returns a specific
    // "we don't cover that place" message if it genuinely is not a Kenyan
    // location. Waiting for the debounce here is what caused the multi-press.
    onSelect(trimmed, trimmed)
    reset()
    inputRef.current?.blur()
  }

  const onKeyDown = (event) => {
    if (event.key === 'Escape') {
      setIsOpen(false)
      setActiveIndex(-1)
      return
    }

    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (!results.length) return
      event.preventDefault()
      setIsOpen(true)
      setActiveIndex((index) => {
        const next = event.key === 'ArrowDown' ? index + 1 : index - 1
        if (next < 0) return results.length - 1
        if (next >= results.length) return 0
        return next
      })
      return
    }

    if (event.key === 'Enter') {
      event.preventDefault()
      submit()
    }
  }

  const showSuggestions = isOpen && trimmed.length > 0

  // The landing renders two of these - one in the masthead, one in the hero -
  // so their accessible names must differ, or a screen reader announces two
  // identical comboboxes with no way to tell them apart. The name also mirrors
  // the visible placeholder, which is what a sighted user is reading.
  const fieldLabel =
    variant === 'hero' ? 'Search a town, county or region' : 'Search a town or county' 

  return (
    <div className={`search search--${variant}`} ref={containerRef}>
      <div
        className="search__field"
        role="combobox"
        aria-expanded={showSuggestions}
        aria-owns={listId}
        aria-haspopup="listbox"
      >
        <SearchIcon />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            setIsOpen(true)
          }}
          onFocus={() => setIsOpen(true)}
          onKeyDown={onKeyDown}
          placeholder={
            placeholder ||
            (currentLabel ? `Search — showing ${currentLabel}` : fieldLabel)
          }
          aria-label={fieldLabel}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={
            activeIndex >= 0 && results[activeIndex]
              ? `${listId}-${results[activeIndex].slug}`
              : undefined
          }
          autoComplete="off"
          spellCheck="false"
          enterKeyHint="search"
        />

        {/* Only offered when there is something to clear. */}
        {query && (
          <button
            type="button"
            className="search__clear"
            onClick={() => {
              reset()
              inputRef.current?.focus()
            }}
            aria-label="Clear search"
            title="Clear"
          >
            <CloseIcon />
          </button>
        )}

        <button
          type="button"
          className="search__go"
          onClick={submit}
          disabled={!trimmed}
          aria-label="Search"
        >
          {isSearching && trimmed ? (
            <Spinner />
          ) : (
            <>
              {/* The word is hidden on narrow screens (see index.css) where a
                  five-character label eats most of the field. The icon keeps
                  the affordance without the width. */}
              <SearchIcon className="search__go-icon" />
              <span className="search__go-text">Search</span>
            </>
          )}
        </button>
      </div>

      {showSuggestions && (
        <ul
          className="suggestions"
          id={listId}
          role="listbox"
          aria-label={`Location suggestions for ${fieldLabel}`}
        >
          {!resultsAreCurrent ? (
            <li className="suggestions__empty">Searching…</li>
          ) : results.length === 0 ? (
            <li className="suggestions__empty">No Kenyan location matches “{trimmed}”.</li>
          ) : (
            results.map((location, index) => (
              <li key={location.slug} role="none">
                <button
                  type="button"
                  id={`${listId}-${location.slug}`}
                  role="option"
                  aria-selected={index === activeIndex}
                  className="suggestions__item"
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => choose(location)}
                >
                  <span className="suggestions__name">{location.name}</span>
                  <span className="suggestions__meta">
                    {location.kind === 'county' ? 'County' : location.county}
                  </span>
                </button>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  )
}

function SearchIcon({ className = 'search__icon' }) {
  return (
    <svg
      className={className}
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      aria-hidden="true"
    >
      <circle cx="7" cy="7" r="4.5" />
      <path d="M10.5 10.5 14 14" strokeLinecap="round" />
    </svg>
  )
}

function CloseIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 14 14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M3.5 3.5 10.5 10.5M10.5 3.5 3.5 10.5" />
    </svg>
  )
}

function Spinner() {
  return (
    <svg className="spinner" width="15" height="15" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="2" opacity="0.25" />
      <path
        d="M8 2a6 6 0 0 1 6 6"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  )
}
