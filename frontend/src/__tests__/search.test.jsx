import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import SearchBar from '../components/SearchBar'

/**
 * Search behaviour, with the stale-result regression front and centre.
 *
 * The bug: suggestions are debounced, so pressing Enter immediately after
 * typing acted on results belonging to an EARLIER query. That selected the
 * wrong town, and made the box feel like it needed three or four presses
 * before it "took". These tests pin the fix - the first Enter is always
 * correct, whatever the debounce is doing.
 */

const KAKAMEGA = { slug: 'kakamega', name: 'Kakamega', county: 'Kakamega', kind: 'county', label: 'Kakamega' }
const MERU = { slug: 'meru', name: 'Meru', county: 'Meru', kind: 'county', label: 'Meru' }

/** A backend whose suggestion endpoint is deliberately slow. */
function stubSearch({ delay = 0, results = [MERU] } = {}) {
  return vi.fn(async (url) => {
    if (delay) await new Promise((r) => setTimeout(r, delay))
    return {
      ok: true,
      status: 200,
      json: async () => ({ query: String(url), count: results.length, results }),
    }
  })
}

afterEach(() => vi.restoreAllMocks())

describe('submitting a search', () => {
  it('acts on the FIRST Enter even while suggestions are still loading', async () => {
    // 400ms is far longer than the debounce, so at the moment Enter is pressed
    // no results for "Meru" can possibly have arrived.
    global.fetch = stubSearch({ delay: 400 })
    const onSelect = vi.fn()

    render(<SearchBar onSelect={onSelect} />)
    const input = screen.getByRole('textbox', { name: /search a town or county/i })

    await userEvent.type(input, 'Meru')
    await userEvent.keyboard('{Enter}')

    // Submits the typed text rather than a stale suggestion. The backend
    // normalises and resolves it.
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect).toHaveBeenCalledWith('Meru', 'Meru')
  })

  it('never selects a location left over from a previous query', async () => {
    // First query resolves to Kakamega; the second is still in flight.
    let call = 0
    global.fetch = vi.fn(async () => {
      call += 1
      const results = call === 1 ? [KAKAMEGA] : []
      if (call > 1) await new Promise((r) => setTimeout(r, 400))
      return { ok: true, status: 200, json: async () => ({ count: results.length, results }) }
    })
    const onSelect = vi.fn()

    render(<SearchBar onSelect={onSelect} />)
    const input = screen.getByRole('textbox', { name: /search a town or county/i })

    await userEvent.type(input, 'Kaka')
    await screen.findByRole('option', { name: /kakamega/i })

    // Now retype something else and submit before its results land.
    await userEvent.clear(input)
    await userEvent.type(input, 'Meru')
    await userEvent.keyboard('{Enter}')

    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect.mock.calls[0][0]).toBe('Meru')
    expect(onSelect.mock.calls[0][0]).not.toBe('kakamega')
  })

  it('uses the top suggestion once results match what is typed', async () => {
    global.fetch = stubSearch({ results: [MERU] })
    const onSelect = vi.fn()

    render(<SearchBar onSelect={onSelect} />)
    await userEvent.type(screen.getByRole('textbox', { name: /search a town or county/i }), 'Meru')
    await screen.findByRole('option', { name: /meru/i })
    await userEvent.keyboard('{Enter}')

    expect(onSelect).toHaveBeenCalledWith('meru', 'Meru')
  })

  it('a highlighted suggestion always wins', async () => {
    global.fetch = stubSearch({ results: [KAKAMEGA, MERU] })
    const onSelect = vi.fn()

    render(<SearchBar onSelect={onSelect} />)
    await userEvent.type(screen.getByRole('textbox', { name: /search a town or county/i }), 'a')
    await screen.findByRole('option', { name: /kakamega/i })

    await userEvent.keyboard('{ArrowDown}{ArrowDown}{Enter}')
    expect(onSelect).toHaveBeenCalledWith('meru', 'Meru')
  })
})

describe('the search button', () => {
  it('submits the same way Enter does', async () => {
    global.fetch = stubSearch({ delay: 400 })
    const onSelect = vi.fn()

    render(<SearchBar onSelect={onSelect} />)
    await userEvent.type(screen.getByRole('textbox', { name: /search a town or county/i }), 'Nyeri')
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(onSelect).toHaveBeenCalledWith('Nyeri', 'Nyeri')
  })

  it('is disabled while the box is empty', () => {
    global.fetch = stubSearch()
    render(<SearchBar onSelect={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Search' })).toBeDisabled()
  })
})

describe('the clear button', () => {
  it('appears only when there is text, and empties the field', async () => {
    global.fetch = stubSearch()
    render(<SearchBar onSelect={vi.fn()} />)
    const input = screen.getByRole('textbox', { name: /search a town or county/i })

    expect(screen.queryByRole('button', { name: /clear search/i })).not.toBeInTheDocument()

    await userEvent.type(input, 'Kisumu')
    await userEvent.click(screen.getByRole('button', { name: /clear search/i }))

    expect(input).toHaveValue('')
    expect(screen.queryByRole('button', { name: /clear search/i })).not.toBeInTheDocument()
  })
})

describe('suggestion feedback', () => {
  it('says it is searching rather than claiming no match', async () => {
    global.fetch = stubSearch({ delay: 400 })
    render(<SearchBar onSelect={vi.fn()} />)

    await userEvent.type(screen.getByRole('textbox', { name: /search a town or county/i }), 'Nak')

    // The old behaviour showed "No Kenyan location matches" while results were
    // still loading, which reads as a dead end.
    expect(await screen.findByText(/searching/i)).toBeInTheDocument()
    expect(screen.queryByText(/no kenyan location matches/i)).not.toBeInTheDocument()
  })

  it('reports a genuine miss once results have arrived', async () => {
    global.fetch = stubSearch({ results: [] })
    render(<SearchBar onSelect={vi.fn()} />)

    await userEvent.type(screen.getByRole('textbox', { name: /search a town or county/i }), 'zzzz')
    await waitFor(() =>
      expect(screen.getByText(/no kenyan location matches/i)).toBeInTheDocument(),
    )
  })
})
