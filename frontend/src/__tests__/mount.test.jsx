import { StrictMode } from 'react'
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../App'

/**
 * Mount tests that mirror main.jsx as closely as possible.
 *
 * The rest of the suite renders <App /> bare; the real entry point wraps it in
 * StrictMode, which double-invokes effects in React 18. These guard the actual
 * production mount path, including the states the browser hits on a cold load:
 * a backend that is down, and a stale location left in localStorage.
 */

beforeEach(() => window.localStorage.clear())
afterEach(() => vi.restoreAllMocks())

describe('production mount path', () => {
  it('renders inside StrictMode', async () => {
    global.fetch = vi.fn(async () => ({
      ok: true, status: 200,
      json: async () => ({ query: '', count: 0, results: [] }),
    }))

    const { container } = render(
      <StrictMode>
        <App />
      </StrictMode>,
    )

    expect(container.innerHTML.length).toBeGreaterThan(0)
    expect(await screen.findByRole('heading', { name: /weather for kenya/i })).toBeInTheDocument()
  })

  it('still renders when the backend is completely unreachable', async () => {
    // What a browser sees when Django is not running: fetch rejects.
    global.fetch = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    })

    render(
      <StrictMode>
        <App />
      </StrictMode>,
    )

    expect(screen.getByRole('heading', { name: /weather for kenya/i })).toBeInTheDocument()
    expect(screen.getByText('Anga')).toBeInTheDocument()
  })

  it('still renders when a stale location is in localStorage and the backend is down', async () => {
    window.localStorage.setItem(
      'anga:last-location',
      JSON.stringify({ slug: 'nairobi', label: 'Nairobi' }),
    )
    global.fetch = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    })

    render(
      <StrictMode>
        <App />
      </StrictMode>,
    )

    // Must show a real error, never a blank page.
    expect(await screen.findByRole('alert')).toHaveTextContent(/no connection/i)
  })

  it('survives corrupt localStorage', async () => {
    window.localStorage.setItem('anga:last-location', '{not json')
    global.fetch = vi.fn(async () => ({
      ok: true, status: 200,
      json: async () => ({ query: '', count: 0, results: [] }),
    }))

    render(
      <StrictMode>
        <App />
      </StrictMode>,
    )
    expect(screen.getByRole('heading', { name: /weather for kenya/i })).toBeInTheDocument()
  })
})
