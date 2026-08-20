import { useEffect, useId, useRef, useState } from 'react'

import { useLocationSearch } from '../hooks/useLocationSearch'

/**
 * Kenyan location search with keyboard-navigable suggestions.
 *
 * Built as an ARIA combobox rather than a styled text input: arrow keys move
 * through suggestions, Enter selects, Escape closes, and screen readers are
 * told what is happening.
 *
 * Suggestions come from our own gazetteer, so they cost no upstream quota -
 * which is why we can afford to search as the user types.
 */
export default function SearchBar({ onSelect, currentLabel }) {
  const [query, setQuery] = useState('')
  const [isOpen, setIsOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)

  const { results } = useLocationSearch(query)
  const containerRef = useRef(null)
  const inputRef = useRef(null)
  const listId = useId()

  // Close when focus or a click leaves the whole combobox.
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

  const choose = (location) => {
    if (!location) return
    onSelect(location.slug, location.label)
    setQuery('')
    setIsOpen(false)
    setActiveIndex(-1)
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
        // Wrap, so the list is fully reachable from either direction.
        if (next < 0) return results.length - 1
        if (next >= results.length) return 0
        return next
      })
      return
    }

    if (event.key === 'Enter') {
      event.preventDefault()
      if (activeIndex >= 0 && results[activeIndex]) {
        choose(results[activeIndex])
      } else if (results.length) {
        // Enter with nothing highlighted takes the best match, which is what
        // someone who typed the full name and hit Enter expects.
        choose(results[0])
      } else if (query.trim()) {
        // Let the backend judge an unrecognised name; it returns a specific
        // "we do not cover that place" message we can show.
        onSelect(query.trim(), query.trim())
        setQuery('')
        setIsOpen(false)
      }
    }
  }

  const showSuggestions = isOpen && query.trim().length > 0

  return (
    <div className="search" ref={containerRef}>
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
          placeholder={currentLabel ? `Search — showing ${currentLabel}` : 'Search a Kenyan town or county'}
          aria-label="Search for a Kenyan town or county"
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
        {query && (
          <button
            type="button"
            className="search__clear"
            onClick={() => {
              setQuery('')
              inputRef.current?.focus()
            }}
            aria-label="Clear search"
          >
            <CloseIcon />
          </button>
        )}
      </div>

      {showSuggestions && (
        <ul className="suggestions" id={listId} role="listbox" aria-label="Location suggestions">
          {results.length === 0 ? (
            <li className="suggestions__empty">No Kenyan location matches “{query.trim()}”.</li>
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
                  <span>{location.name}</span>
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

function SearchIcon() {
  return (
    <svg
      className="search__icon"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
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
      strokeWidth="1.6"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M3.5 3.5 10.5 10.5M10.5 3.5 3.5 10.5" />
    </svg>
  )
}
