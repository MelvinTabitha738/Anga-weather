import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import Dashboard from '../components/Dashboard'

/**
 * The freshness line must keep counting while the page is open.
 *
 * `meta.age_seconds` is a snapshot from response-build time. Left alone it
 * freezes, so a tab open for an hour keeps claiming the reading is "just now" -
 * exactly the overstated freshness the whole design avoids elsewhere.
 */

const BASE = {
  location: { slug: 'nairobi', name: 'Nairobi', county: 'Nairobi', kind: 'county', label: 'Nairobi' },
  current: {
    temperature: 21.8, wind_speed: 5, wind_direction: 'SE',
    precipitation_this_hour: 0, condition: 'Partly cloudy',
    condition_group: 'partly_cloudy', condition_intensity: 'none',
    is_day: true, observed_at: '2026-08-20T15:30', units: 'metric',
  },
  hourly: [], daily: [], ai_summary: null,
}

function withMeta(overrides = {}) {
  return {
    ...BASE,
    meta: {
      status: 'live', is_cached: false, is_stale: false,
      fetched_at: '2026-08-20T12:30:00Z', age_seconds: 0,
      expires_at: '2026-08-20T13:00:00Z', ttl_seconds: 1800,
      fallback_reason: null, retry_at: null,
      ...overrides,
    },
  }
}

/** Advance both the interval timer and the wall clock they read from. */
async function advance(seconds) {
  await act(async () => {
    vi.advanceTimersByTime(seconds * 1000)
  })
}

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }))
afterEach(() => {
  vi.runOnlyPendingTimers()
  vi.useRealTimers()
})

describe('freshness ticks in real time', () => {
  it('starts at "just now" for a fresh live reading', () => {
    render(<Dashboard data={withMeta()} onBack={() => {}} />)
    expect(screen.getByText(/updated just now · live/i)).toBeInTheDocument()
  })

  it('reaches "3 minutes ago" after three minutes on screen', async () => {
    render(<Dashboard data={withMeta()} onBack={() => {}} />)
    await advance(180)
    expect(screen.getByText(/updated 3 minutes ago/i)).toBeInTheDocument()
    // No longer claiming it is brand new.
    expect(screen.queryByText(/just now/i)).not.toBeInTheDocument()
  })

  it('adds elapsed time on top of the age the server reported', async () => {
    // Server said the cached entry was already 4 minutes old.
    render(<Dashboard data={withMeta({ status: 'cached', is_cached: true, age_seconds: 240 })} onBack={() => {}} />)
    expect(screen.getByText(/updated 4 minutes ago · cached/i)).toBeInTheDocument()

    await advance(120)
    expect(screen.getByText(/updated 6 minutes ago · cached/i)).toBeInTheDocument()
  })

  it('keeps counting a stale reading too', async () => {
    render(
      <Dashboard
        data={withMeta({ status: 'stale', is_cached: true, is_stale: true, age_seconds: 840 })}
        onBack={() => {}}
      />,
    )
    expect(screen.getByText(/last updated 14 minutes ago · not current/i)).toBeInTheDocument()

    await advance(120)
    expect(screen.getByText(/last updated 16 minutes ago · not current/i)).toBeInTheDocument()
  })

  it('warns and offers a refresh once the reading outlives the cache TTL', async () => {
    const onRefresh = vi.fn()
    render(
      <Dashboard
        data={withMeta({ status: 'cached', is_cached: true, age_seconds: 1770, ttl_seconds: 1800 })}
        onBack={() => {}}
        onRefresh={onRefresh}
      />,
    )

    // Still inside the TTL: no warning yet.
    expect(screen.queryByRole('button', { name: /refresh/i })).not.toBeInTheDocument()

    // Cross the 30-minute TTL.
    await advance(60)

    expect(screen.getByText(/may be out of date/i)).toBeInTheDocument()
    const button = screen.getByRole('button', { name: /refresh/i })
    button.click()
    expect(onRefresh).toHaveBeenCalled()
  })

  it('restarts the count when a new payload arrives', async () => {
    const { rerender } = render(<Dashboard data={withMeta()} onBack={() => {}} />)
    await advance(300)
    expect(screen.getByText(/updated 5 minutes ago/i)).toBeInTheDocument()

    rerender(
      <Dashboard
        data={withMeta({ fetched_at: '2026-08-20T13:00:00Z', age_seconds: 0 })}
        onBack={() => {}}
      />,
    )
    expect(screen.getByText(/updated just now · live/i)).toBeInTheDocument()
  })

  it('is announced politely rather than interrupting', () => {
    const { container } = render(<Dashboard data={withMeta()} onBack={() => {}} />)
    expect(container.querySelector('.freshness')).toHaveAttribute('aria-live', 'polite')
  })
})
