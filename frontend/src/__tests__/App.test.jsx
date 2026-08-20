import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../App'

/**
 * Behavioural tests for the states a user actually encounters. `fetch` is
 * stubbed at the boundary so these exercise the real hooks, components and
 * theme logic - only the network is fake.
 */

const LOCATION = { slug: 'nairobi', name: 'Nairobi', county: 'Nairobi', kind: 'county', label: 'Nairobi' }

const WEATHER = {
  temperature: 24.4,
  feels_like: 25.2,
  humidity: 62,
  wind_speed: 11,
  wind_direction: 'SE',
  precipitation: 0,
  precipitation_chance: 12,
  pressure: 1014,
  uv_index: 7,
  condition: 'Partly cloudy',
  condition_group: 'partly_cloudy',
  condition_intensity: 'none',
  is_day: true,
  observed_at: '2026-08-20T09:00:00Z',
  units: 'metric',
}

function meta(overrides = {}) {
  return {
    status: 'live',
    is_cached: false,
    is_stale: false,
    fetched_at: '2026-08-20T09:00:00Z',
    age_seconds: 0,
    expires_at: '2026-08-20T09:30:00Z',
    ttl_seconds: 1800,
    fallback_reason: null,
    retry_at: null,
    ...overrides,
  }
}

function weatherResponse(overrides = {}) {
  return {
    location: LOCATION,
    weather: { ...WEATHER, ...(overrides.weather || {}) },
    meta: meta(overrides.meta),
  }
}

const SUGGESTIONS = {
  query: '',
  count: 2,
  results: [
    LOCATION,
    { slug: 'mombasa', name: 'Mombasa', county: 'Mombasa', kind: 'county', label: 'Mombasa' },
  ],
}

/** Route stubbed fetch by URL, so tests only describe what they care about. */
function stubFetch({ weather, weatherError, locations = SUGGESTIONS } = {}) {
  return vi.fn(async (url) => {
    if (String(url).includes('/api/locations/')) {
      return { ok: true, status: 200, json: async () => locations }
    }
    if (weatherError) {
      return {
        ok: false,
        status: weatherError.status ?? 503,
        json: async () => ({ error: weatherError }),
      }
    }
    return { ok: true, status: 200, json: async () => weather ?? weatherResponse() }
  })
}

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('first run', () => {
  it('invites a search and offers starting points before any location is chosen', async () => {
    global.fetch = stubFetch()
    render(<App />)

    expect(screen.getByRole('heading', { name: /weather for kenya/i })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Nairobi' })).toBeInTheDocument()
  })

  it('never asks the weather endpoint until a location is selected', async () => {
    const fetchMock = stubFetch()
    global.fetch = fetchMock
    render(<App />)

    await screen.findByRole('button', { name: 'Nairobi' })
    const weatherCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes('/api/weather/'))
    expect(weatherCalls).toHaveLength(0)
  })
})

describe('loading', () => {
  it('shows a skeleton rather than a bare spinner', async () => {
    let release
    global.fetch = vi.fn(async (url) => {
      if (String(url).includes('/api/locations/')) {
        return { ok: true, status: 200, json: async () => SUGGESTIONS }
      }
      await new Promise((resolve) => {
        release = resolve
      })
      return { ok: true, status: 200, json: async () => weatherResponse() }
    })

    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Nairobi' }))

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent(/loading weather for nairobi/i)

    release()
    await screen.findByRole('heading', { name: /nairobi/i })
  })
})

describe('successful reading', () => {
  it('shows the temperature, condition and available details', async () => {
    global.fetch = stubFetch()
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Nairobi' }))

    expect(await screen.findByRole('heading', { name: /nairobi/i })).toBeInTheDocument()
    expect(screen.getByText('24°')).toBeInTheDocument()
    expect(screen.getByText('Partly cloudy')).toBeInTheDocument()
    expect(screen.getByText('62%')).toBeInTheDocument()
    expect(screen.getByText('11 km/h')).toBeInTheDocument()
    expect(screen.getByText(/live from weather-ai/i)).toBeInTheDocument()
  })

  it('omits details the API did not return instead of showing empty cells', async () => {
    global.fetch = stubFetch({
      weather: weatherResponse({
        weather: { uv_index: null, pressure: null, precipitation_chance: null },
      }),
    })
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Nairobi' }))
    await screen.findByRole('heading', { name: /nairobi/i })

    expect(screen.queryByText(/uv index/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/pressure/i)).not.toBeInTheDocument()
    // The fields that ARE present still render.
    expect(screen.getByText(/humidity/i)).toBeInTheDocument()
  })

  it('drives the backdrop from the reported condition', async () => {
    global.fetch = stubFetch({
      weather: weatherResponse({
        weather: { condition_group: 'rain', condition_intensity: 'heavy', is_day: false },
      }),
    })
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Nairobi' }))
    await screen.findByRole('heading', { name: /nairobi/i })

    const backdrop = screen.getByTestId('backdrop')
    expect(backdrop).toHaveAttribute('data-effect', 'rain')
    expect(backdrop).toHaveAttribute('data-intensity', 'heavy')
    expect(backdrop).toHaveClass('is-night')
  })
})

describe('freshness honesty', () => {
  it('labels a cached reading as cached', async () => {
    global.fetch = stubFetch({
      weather: weatherResponse({
        meta: { status: 'cached', is_cached: true, is_stale: false, age_seconds: 240 },
      }),
    })
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Nairobi' }))

    expect(await screen.findByText(/updated 4 minutes ago · cached/i)).toBeInTheDocument()
  })

  it('warns clearly when data is stale and explains why', async () => {
    global.fetch = stubFetch({
      weather: weatherResponse({
        meta: {
          status: 'stale',
          is_cached: true,
          is_stale: true,
          age_seconds: 840,
          fallback_reason: 'rate_limited',
        },
      }),
    })
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Nairobi' }))

    const notice = await screen.findByRole('status')
    expect(notice).toHaveTextContent(/live updates are paused/i)
    expect(notice).toHaveTextContent(/14 minutes ago/i)
    // And the reading itself is marked, not just the banner.
    expect(screen.getByText(/not current/i)).toBeInTheDocument()
  })

  it('does not describe stale data as current', async () => {
    global.fetch = stubFetch({
      weather: weatherResponse({
        meta: { status: 'stale', is_cached: true, is_stale: true, age_seconds: 900 },
      }),
    })
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Nairobi' }))
    await screen.findByRole('heading', { name: /nairobi/i })

    expect(screen.queryByText(/live from weather-ai/i)).not.toBeInTheDocument()
  })
})

describe('errors', () => {
  it('translates an upstream outage into human language with a retry', async () => {
    global.fetch = stubFetch({
      weatherError: { code: 'weather_unavailable', message: 'ignored backend prose' },
    })
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Nairobi' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/could not refresh the weather/i)
    expect(alert).not.toHaveTextContent(/ignored backend prose/i)
    expect(within(alert).getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  it('does not offer retry while rate limited, since retrying cannot help', async () => {
    global.fetch = stubFetch({
      weatherError: { code: 'rate_limited', message: 'x', retry_after: 600 },
    })
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Nairobi' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/weather service is busy/i)
    expect(within(alert).queryByRole('button', { name: /try again/i })).not.toBeInTheDocument()
  })

  it('explains an unknown location', async () => {
    global.fetch = stubFetch({
      weatherError: { code: 'unknown_location', message: 'x', status: 404 },
    })
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Nairobi' }))

    expect(await screen.findByText(/do not cover that place yet/i)).toBeInTheDocument()
  })

  it('recovers when a retry succeeds', async () => {
    let shouldFail = true
    global.fetch = vi.fn(async (url) => {
      if (String(url).includes('/api/locations/')) {
        return { ok: true, status: 200, json: async () => SUGGESTIONS }
      }
      if (shouldFail) {
        return {
          ok: false,
          status: 503,
          json: async () => ({ error: { code: 'weather_unavailable', message: 'x' } }),
        }
      }
      return { ok: true, status: 200, json: async () => weatherResponse() }
    })

    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Nairobi' }))
    await screen.findByRole('alert')

    shouldFail = false
    await userEvent.click(screen.getByRole('button', { name: /try again/i }))

    expect(await screen.findByText('24°')).toBeInTheDocument()
  })
})

describe('search', () => {
  it('suggests locations as the user types and loads the chosen one', async () => {
    const fetchMock = stubFetch()
    global.fetch = fetchMock
    render(<App />)

    const input = screen.getByRole('textbox', { name: /search for a kenyan/i })
    await userEvent.type(input, 'mom')

    const option = await screen.findByRole('option', { name: /mombasa/i })
    await userEvent.click(option)

    await waitFor(() => {
      const weatherCalls = fetchMock.mock.calls.filter(([url]) =>
        String(url).includes('/api/weather/'),
      )
      expect(weatherCalls.length).toBeGreaterThan(0)
      expect(String(weatherCalls.at(-1)[0])).toContain('location=mombasa')
    })
  })

  it('supports keyboard selection', async () => {
    const fetchMock = stubFetch()
    global.fetch = fetchMock
    render(<App />)

    const input = screen.getByRole('textbox', { name: /search for a kenyan/i })
    await userEvent.type(input, 'na')
    await screen.findByRole('option', { name: /nairobi/i })

    await userEvent.keyboard('{ArrowDown}{ArrowDown}{Enter}')

    await waitFor(() => {
      const weatherCalls = fetchMock.mock.calls.filter(([url]) =>
        String(url).includes('/api/weather/'),
      )
      expect(String(weatherCalls.at(-1)[0])).toContain('location=mombasa')
    })
  })

  it('searching does not itself trigger a weather request', async () => {
    const fetchMock = stubFetch()
    global.fetch = fetchMock
    render(<App />)

    await userEvent.type(screen.getByRole('textbox', { name: /search for a kenyan/i }), 'nak')
    await screen.findByRole('listbox')

    const weatherCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes('/api/weather/'))
    expect(weatherCalls).toHaveLength(0)
  })

  it('reports when nothing matches', async () => {
    global.fetch = stubFetch({ locations: { query: 'zz', count: 0, results: [] } })
    render(<App />)

    await userEvent.type(screen.getByRole('textbox', { name: /search for a kenyan/i }), 'zzzz')
    expect(await screen.findByText(/no kenyan location matches/i)).toBeInTheDocument()
  })
})
