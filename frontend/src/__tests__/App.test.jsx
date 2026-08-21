import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../App'

/**
 * Behavioural tests for the states a user actually encounters. `fetch` is
 * stubbed at the boundary so these exercise the real hooks, components and
 * theme logic - only the network is fake.
 *
 * The payloads mirror the VERIFIED Weather-AI response: no humidity,
 * feels-like, pressure or visibility, because the provider does not return
 * them.
 */

const LOCATION = {
  slug: 'kakamega', name: 'Kakamega', county: 'Kakamega',
  kind: 'county', label: 'Kakamega',
}

const CURRENT = {
  temperature: 26,
  wind_speed: 5.2,
  wind_direction: 'WNW',
  wind_direction_degrees: 292,
  precipitation_this_hour: 0.1,
  weather_code: 51,
  condition: 'Light drizzle',
  condition_group: 'drizzle',
  condition_intensity: 'light',
  is_day: true,
  observed_at: '2026-08-20T15:30',
  units: 'metric',
}

const HOURLY = [
  { time: '2026-08-20T15:00', temperature: 26.1, precipitation: 0.1, weather_code: 51,
    condition: 'Light drizzle', condition_group: 'drizzle', condition_intensity: 'light' },
  { time: '2026-08-20T16:00', temperature: 25.8, precipitation: 0.2, weather_code: 51,
    condition: 'Light drizzle', condition_group: 'drizzle', condition_intensity: 'light' },
  { time: '2026-08-20T17:00', temperature: 24.8, precipitation: 0, weather_code: 1,
    condition: 'Mainly clear', condition_group: 'clear', condition_intensity: 'none' },
]

const DAILY = [
  { date: '2026-08-20', temp_max: 26.3, temp_min: 15, precipitation: 2.2, weather_code: 51,
    condition: 'Light drizzle', condition_group: 'drizzle', condition_intensity: 'light' },
  { date: '2026-08-21', temp_max: 28.4, temp_min: 14.1, precipitation: 0.4, weather_code: 2,
    condition: 'Partly cloudy', condition_group: 'partly_cloudy', condition_intensity: 'none' },
  { date: '2026-08-25', temp_max: 28.6, temp_min: 14.3, precipitation: 12.6, weather_code: 95,
    condition: 'Thunderstorm', condition_group: 'thunderstorm', condition_intensity: 'heavy' },
]

function meta(overrides = {}) {
  return {
    status: 'live', is_cached: false, is_stale: false,
    fetched_at: '2026-08-20T12:30:00Z', age_seconds: 0,
    expires_at: '2026-08-20T13:00:00Z', ttl_seconds: 1800,
    fallback_reason: null, retry_at: null,
    ...overrides,
  }
}

function weatherResponse(overrides = {}) {
  return {
    location: LOCATION,
    current: { ...CURRENT, ...(overrides.current || {}) },
    hourly: overrides.hourly ?? HOURLY,
    daily: overrides.daily ?? DAILY,
    ai_summary: overrides.ai_summary ?? null,
    meta: meta(overrides.meta),
  }
}

const SUGGESTIONS = {
  query: '', count: 2,
  results: [
    LOCATION,
    { slug: 'mombasa', name: 'Mombasa', county: 'Mombasa', kind: 'county', label: 'Mombasa' },
  ],
}

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

/** Select the first suggested location and wait for the dashboard. */
async function openDashboard() {
  await userEvent.click(await screen.findByRole('button', { name: 'Kakamega' }))
  return screen.findByRole('heading', { level: 1, name: /kakamega/i })
}

beforeEach(() => window.localStorage.clear())
afterEach(() => vi.restoreAllMocks())

describe('first run', () => {
  it('invites a search and offers starting points', async () => {
    global.fetch = stubFetch()
    render(<App />)
    expect(screen.getByRole('heading', { level: 1, name: /read the kenyan sky/i })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Kakamega' })).toBeInTheDocument()
  })

  it('never asks the weather endpoint until a location is selected', async () => {
    const fetchMock = stubFetch()
    global.fetch = fetchMock
    render(<App />)
    await screen.findByRole('button', { name: 'Kakamega' })
    expect(
      fetchMock.mock.calls.filter(([u]) => String(u).includes('/api/weather/')),
    ).toHaveLength(0)
  })
})

describe('the landing design', () => {
  it('uses the photographic sky, and switches to the reactive one after a search', async () => {
    global.fetch = stubFetch()
    render(<App />)

    // Before a location: the photograph.
    expect(await screen.findByTestId('backdrop')).toHaveAttribute('data-effect', 'photo')

    await openDashboard()

    // After: the weather drives the sky again.
    expect(screen.getByTestId('backdrop')).not.toHaveAttribute('data-effect', 'photo')
  })

  it('asks what the weather is, not what to wear', async () => {
    global.fetch = stubFetch()
    render(<App />)

    expect(await screen.findByText(/what is the weather today/i)).toBeInTheDocument()
    expect(screen.queryByText(/what should i wear/i)).not.toBeInTheDocument()
  })

  it('shows the display headline and the eyebrow', async () => {
    global.fetch = stubFetch()
    render(<App />)

    expect(screen.getByRole('heading', { level: 1, name: /read the kenyan sky/i })).toBeInTheDocument()
    expect(screen.getByText(/swahili for sky/i)).toBeInTheDocument()
  })

  it('shows no weather reading before anything is searched', async () => {
    // The design's "right now over Nairobi" card is deliberately omitted: it
    // would mean an upstream call on every landing view.
    const fetchMock = stubFetch()
    global.fetch = fetchMock
    render(<App />)
    await screen.findByRole('button', { name: 'Kakamega' })

    expect(screen.queryByText(/right now over/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: /current conditions/i })).not.toBeInTheDocument()
    expect(
      fetchMock.mock.calls.filter(([u]) => String(u).includes('/api/weather/')),
    ).toHaveLength(0)
  })

  it('offers the three feature panels', async () => {
    global.fetch = stubFetch()
    render(<App />)

    for (const title of [
      '24 hours, then 7 days',
      'The page becomes the weather',
      'Never guesses how fresh it is',
    ]) {
      expect(screen.getByRole('heading', { name: title })).toBeInTheDocument()
    }
  })

  it('describes the forecast length the app actually renders', async () => {
    // The earlier copy said "a twelve-hour ribbon" while the adapter caps
    // HOURLY_WINDOW at 24. Marketing copy is still a claim about behaviour.
    global.fetch = stubFetch()
    render(<App />)
    expect(screen.getByRole('heading', { name: /24 hours, then 7 days/i })).toBeInTheDocument()
    expect(screen.queryByText(/twelve-hour/i)).not.toBeInTheDocument()
  })

  it('gives the two search fields distinct accessible names', async () => {
    // The landing renders one in the masthead and one in the hero; identical
    // names would leave a screen reader announcing two indistinguishable
    // comboboxes.
    global.fetch = stubFetch()
    render(<App />)

    expect(screen.getByRole('textbox', { name: /town, county or region/i })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: /^search a town or county$/i })).toBeInTheDocument()
  })
})

describe('loading', () => {
  it('shows a skeleton rather than a bare spinner', async () => {
    let release
    global.fetch = vi.fn(async (url) => {
      if (String(url).includes('/api/locations/')) {
        return { ok: true, status: 200, json: async () => SUGGESTIONS }
      }
      await new Promise((resolve) => { release = resolve })
      return { ok: true, status: 200, json: async () => weatherResponse() }
    })

    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Kakamega' }))

    expect(await screen.findByRole('status')).toHaveTextContent(/loading weather for kakamega/i)
    release()
    await screen.findByRole('heading', { level: 1, name: /kakamega/i })
  })
})

describe('dashboard', () => {
  it('shows the current temperature and condition', async () => {
    global.fetch = stubFetch()
    render(<App />)
    await openDashboard()

    // Scoped to the hero: "26" also legitimately appears as today's high in
    // the forecast, so an unscoped query would be ambiguous.
    const current = screen.getByRole('region', { name: /current conditions/i })
    expect(within(current).getByText('26°')).toBeInTheDocument()
    expect(within(current).getByText('Light drizzle')).toBeInTheDocument()
    expect(screen.getByText(/thursday, 20 august/i)).toBeInTheDocument()
  })

  it('shows only metrics the API actually returns', async () => {
    global.fetch = stubFetch()
    render(<App />)
    await openDashboard()

    // Wind IS returned.
    const metrics = screen.getByRole('list', { name: /current measurements/i })
    expect(within(metrics).getByText('Wind')).toBeInTheDocument()
    expect(within(metrics).getByText('5 km/h')).toBeInTheDocument()
    // These are NOT in the Weather-AI response and must never be shown.
    expect(screen.queryByText(/humidity/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/feels like/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/pressure/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/visibility/i)).not.toBeInTheDocument()
  })

  it('derives today rainfall and high/low from the daily series', async () => {
    global.fetch = stubFetch()
    render(<App />)
    await openDashboard()

    // Today's rainfall appears both as a metric card and in the daily row,
    // so scope to the metric list.
    const metrics = screen.getByRole('list', { name: /current measurements/i })
    expect(within(metrics).getByText('Rain today')).toBeInTheDocument()
    expect(within(metrics).getByText('2.2 mm')).toBeInTheDocument()
    expect(within(metrics).getByText('High / Low')).toBeInTheDocument()
    expect(within(metrics).getByText('26° / 15°')).toBeInTheDocument()
  })

  it('renders the hourly outlook with Now first', async () => {
    global.fetch = stubFetch()
    render(<App />)
    await openDashboard()

    const hourly = screen.getByRole('list', { name: /hourly forecast/i })
    const items = within(hourly).getAllByRole('listitem')
    expect(items).toHaveLength(3)
    expect(within(items[0]).getByText('Now')).toBeInTheDocument()
    expect(within(items[1]).getByText('4 PM')).toBeInTheDocument()
    expect(within(items[2]).getByText('5 PM')).toBeInTheDocument()
  })

  it('renders the multi-day forecast with relative day names', async () => {
    global.fetch = stubFetch()
    render(<App />)
    await openDashboard()

    expect(screen.getByRole('heading', { name: /next 3 days/i })).toBeInTheDocument()
    expect(screen.getByText('Today')).toBeInTheDocument()
    expect(screen.getByText('Tomorrow')).toBeInTheDocument()
    expect(screen.getByText('28°')).toBeInTheDocument()
  })

  it('omits the forecast panels entirely when the API returns none', async () => {
    global.fetch = stubFetch({ weather: weatherResponse({ hourly: [], daily: [] }) })
    render(<App />)
    await openDashboard()

    expect(screen.queryByRole('heading', { name: /outlook/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /next .* days/i })).not.toBeInTheDocument()
  })

  it('can return to search', async () => {
    global.fetch = stubFetch()
    render(<App />)
    await openDashboard()

    await userEvent.click(screen.getByRole('button', { name: /search locations/i }))
    expect(await screen.findByRole('heading', { level: 1, name: /read the kenyan sky/i })).toBeInTheDocument()
  })
})

describe('rainfall column', () => {
  // Mirrors real Meru data: 4 of 7 days are dry, which is exactly the case
  // that previously rendered blank and looked like missing information.
  const MERU_WEEK = [
    { date: '2026-08-20', temp_max: 23.7, temp_min: 11.7, precipitation: 0.0,
      condition: 'Overcast', condition_group: 'cloudy', condition_intensity: 'none' },
    { date: '2026-08-21', temp_max: 23.6, temp_min: 12.2, precipitation: 0.0,
      condition: 'Overcast', condition_group: 'cloudy', condition_intensity: 'none' },
    { date: '2026-08-22', temp_max: 24.8, temp_min: 14.3, precipitation: 0.1,
      condition: 'Light drizzle', condition_group: 'drizzle', condition_intensity: 'light' },
    { date: '2026-08-23', temp_max: 24.1, temp_min: 15.0, precipitation: 1.3,
      condition: 'Light drizzle', condition_group: 'drizzle', condition_intensity: 'light' },
    { date: '2026-08-24', temp_max: 23.3, temp_min: 15.2, precipitation: 1.8,
      condition: 'Light drizzle', condition_group: 'drizzle', condition_intensity: 'light' },
    { date: '2026-08-25', temp_max: 24.1, temp_min: 12.9, precipitation: 0.0,
      condition: 'Mainly clear', condition_group: 'clear', condition_intensity: 'none' },
    { date: '2026-08-26', temp_max: 23.3, temp_min: 12.7, precipitation: 0.0,
      condition: 'Partly cloudy', condition_group: 'partly_cloudy', condition_intensity: 'none' },
  ]

  async function openMeru() {
    global.fetch = stubFetch({ weather: weatherResponse({ daily: MERU_WEEK }) })
    render(<App />)
    return openDashboard()
  }

  it('gives EVERY day a rainfall value, never a blank cell', async () => {
    await openMeru()

    const rows = within(screen.getByRole('heading', { name: /next 7 days/i })
      .closest('section')).getAllByRole('listitem')
    expect(rows).toHaveLength(7)

    // The regression: dry days used to render an empty cell.
    for (const row of rows) {
      expect(row.textContent).toMatch(/\d|—/)
    }
  })

  it('says "no rain expected" on dry days rather than showing nothing', async () => {
    await openMeru()
    // Scoped to the daily panel: the hourly strip has dry hours of its own.
    const daily = screen.getByRole('heading', { name: /next 7 days/i }).closest('section')
    expect(within(daily).getAllByText('No rain expected')).toHaveLength(4)
    // ...and the other three days carry a real figure.
    expect(within(daily).getAllByText(/millimetres of rain$/)).toHaveLength(3)
  })

  it('states the unit once, in a column legend', async () => {
    await openMeru()
    const daily = screen.getByRole('heading', { name: /next 7 days/i }).closest('section')
    expect(within(daily).getByText(/rainfall \(mm\)/i)).toBeInTheDocument()
  })

  it('does not repeat the unit on every row', async () => {
    await openMeru()
    const daily = screen.getByRole('heading', { name: /next 7 days/i }).closest('section')
    // "mm" appears once (the legend), not once per rainy row.
    expect(within(daily).queryAllByText(/^\d+(\.\d)? mm$/)).toHaveLength(0)
  })

  it('announces amounts fully to screen readers', async () => {
    await openMeru()
    expect(screen.getByText('1.3 millimetres of rain')).toBeInTheDocument()
    expect(screen.getByText('1.8 millimetres of rain')).toBeInTheDocument()
  })

  it('switches the legend unit for imperial', async () => {
    global.fetch = stubFetch({
      weather: weatherResponse({
        current: { units: 'imperial' },
        daily: MERU_WEEK,
      }),
    })
    render(<App />)
    await openDashboard()

    const daily = screen.getByRole('heading', { name: /next 7 days/i }).closest('section')
    expect(within(daily).getByText(/rainfall \(in\)/i)).toBeInTheDocument()
  })

  it('gives every hourly column a rainfall slot so the strip cannot jitter', async () => {
    global.fetch = stubFetch()
    render(<App />)
    await openDashboard()

    const hourly = screen.getByRole('list', { name: /hourly forecast/i })
    const items = within(hourly).getAllByRole('listitem')
    // HOURLY has one dry hour (17:00, precipitation 0) among three.
    expect(items).toHaveLength(3)
    for (const item of items) {
      expect(item.textContent).toMatch(/rain|—|\d/i)
    }
    expect(within(hourly).getAllByText('No rain expected')).toHaveLength(1)
  })
})

describe('AI insight', () => {
  it('is hidden when the provider returns null, rather than showing filler', async () => {
    global.fetch = stubFetch()
    render(<App />)
    await openDashboard()
    expect(screen.queryByRole('heading', { name: /weather insight/i })).not.toBeInTheDocument()
  })

  it('appears when the provider actually returns a summary', async () => {
    global.fetch = stubFetch({
      weather: weatherResponse({
        ai_summary: 'A warm but cloudy afternoon is expected in Kakamega.',
      }),
    })
    render(<App />)
    await openDashboard()

    expect(screen.getByRole('heading', { name: /weather insight/i })).toBeInTheDocument()
    expect(screen.getByText(/warm but cloudy afternoon/i)).toBeInTheDocument()
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
    await openDashboard()
    expect(screen.getByText(/updated 4 minutes ago/i)).toBeInTheDocument()
  })

  it('warns clearly when data is stale and explains why', async () => {
    global.fetch = stubFetch({
      weather: weatherResponse({
        meta: {
          status: 'stale', is_cached: true, is_stale: true,
          age_seconds: 840, fallback_reason: 'rate_limited',
        },
      }),
    })
    render(<App />)
    await openDashboard()

    const notice = screen.getByRole('status')
    expect(notice).toHaveTextContent(/live updates are paused/i)
    expect(notice).toHaveTextContent(/14 minutes ago/i)
    expect(screen.getByText(/not current/i)).toBeInTheDocument()
  })

  it('never shows implementation vocabulary to the reader', async () => {
    // "cached" answers a question nobody asked. The age is the whole message;
    // provenance is our concern, and lives in /api/meta/stats/ instead.
    global.fetch = stubFetch({
      weather: weatherResponse({
        meta: { status: 'cached', is_cached: true, age_seconds: 240 },
      }),
    })
    const { container } = render(<App />)
    await openDashboard()

    expect(screen.getByText(/updated 4 minutes ago/i)).toBeInTheDocument()

    // Scoped to the freshness line. The footer explains the caching in prose,
    // which is a fair place for it; the reading's own label is not.
    const freshness = container.querySelector('.freshness')
    expect(freshness.textContent).toMatch(/updated 4 minutes ago/i)
    expect(freshness.textContent).not.toMatch(/cache/i)
    expect(freshness.textContent).not.toMatch(/live/i)
    expect(freshness.textContent).not.toMatch(/redis|upstream|stale/i)
  })

  it('still spends words where they change what to believe', async () => {
    global.fetch = stubFetch({
      weather: weatherResponse({
        meta: {
          status: 'stale', is_cached: true, is_stale: true,
          age_seconds: 900, fallback_reason: 'upstream_unavailable',
        },
      }),
    })
    render(<App />)
    await openDashboard()
    expect(screen.getByText(/not current/i)).toBeInTheDocument()
  })
})

describe('weather drives the visuals', () => {
  it('selects the rain backdrop and scales it to intensity', async () => {
    global.fetch = stubFetch({
      weather: weatherResponse({
        current: { condition_group: 'rain', condition_intensity: 'heavy', is_day: false },
      }),
    })
    render(<App />)
    await openDashboard()

    const backdrop = screen.getByTestId('backdrop')
    expect(backdrop).toHaveAttribute('data-effect', 'rain')
    expect(backdrop).toHaveAttribute('data-intensity', 'heavy')
    expect(backdrop).toHaveClass('is-night')
  })

  it('selects a storm backdrop for thunderstorms', async () => {
    global.fetch = stubFetch({
      weather: weatherResponse({
        current: { condition_group: 'thunderstorm', condition_intensity: 'heavy' },
      }),
    })
    render(<App />)
    await openDashboard()
    expect(screen.getByTestId('backdrop')).toHaveAttribute('data-effect', 'storm')
  })

  it('selects a sunny backdrop for clear daytime conditions', async () => {
    global.fetch = stubFetch({
      weather: weatherResponse({
        current: { condition_group: 'clear', condition_intensity: 'none', is_day: true },
      }),
    })
    render(<App />)
    await openDashboard()
    expect(screen.getByTestId('backdrop')).toHaveAttribute('data-effect', 'sun')
  })
})

describe('errors', () => {
  it('translates an upstream outage into human language with a retry', async () => {
    global.fetch = stubFetch({
      weatherError: { code: 'weather_unavailable', message: 'ignored backend prose' },
    })
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Kakamega' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/could not refresh the weather/i)
    expect(alert).not.toHaveTextContent(/ignored backend prose/i)
    expect(within(alert).getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  it('does not offer retry while rate limited, since retrying cannot help', async () => {
    global.fetch = stubFetch({ weatherError: { code: 'rate_limited', message: 'x' } })
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Kakamega' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/weather service is busy/i)
    expect(within(alert).queryByRole('button', { name: /try again/i })).not.toBeInTheDocument()
  })

  it('recovers when a retry succeeds', async () => {
    let shouldFail = true
    global.fetch = vi.fn(async (url) => {
      if (String(url).includes('/api/locations/')) {
        return { ok: true, status: 200, json: async () => SUGGESTIONS }
      }
      if (shouldFail) {
        return { ok: false, status: 503,
          json: async () => ({ error: { code: 'weather_unavailable', message: 'x' } }) }
      }
      return { ok: true, status: 200, json: async () => weatherResponse() }
    })

    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Kakamega' }))
    await screen.findByRole('alert')

    shouldFail = false
    await userEvent.click(screen.getByRole('button', { name: /try again/i }))

    const current = await screen.findByRole('region', { name: /current conditions/i })
    expect(within(current).getByText('26°')).toBeInTheDocument()
  })
})

describe('search', () => {
  it('suggests locations as the user types and loads the chosen one', async () => {
    const fetchMock = stubFetch()
    global.fetch = fetchMock
    render(<App />)

    await userEvent.type(
      screen.getByRole('textbox', { name: /town, county or region/i }), 'mom',
    )
    await userEvent.click(await screen.findByRole('option', { name: /mombasa/i }))

    await waitFor(() => {
      const calls = fetchMock.mock.calls.filter(([u]) => String(u).includes('/api/weather/'))
      expect(calls.length).toBeGreaterThan(0)
      expect(String(calls.at(-1)[0])).toContain('location=mombasa')
    })
  })

  it('supports keyboard selection', async () => {
    const fetchMock = stubFetch()
    global.fetch = fetchMock
    render(<App />)

    await userEvent.type(screen.getByRole('textbox', { name: /town, county or region/i }), 'ka')
    await screen.findByRole('option', { name: /kakamega/i })
    await userEvent.keyboard('{ArrowDown}{ArrowDown}{Enter}')

    await waitFor(() => {
      const calls = fetchMock.mock.calls.filter(([u]) => String(u).includes('/api/weather/'))
      expect(String(calls.at(-1)[0])).toContain('location=mombasa')
    })
  })

  it('searching does not itself trigger a weather request', async () => {
    const fetchMock = stubFetch()
    global.fetch = fetchMock
    render(<App />)

    await userEvent.type(screen.getByRole('textbox', { name: /town, county or region/i }), 'nak')
    await screen.findByRole('listbox')

    expect(
      fetchMock.mock.calls.filter(([u]) => String(u).includes('/api/weather/')),
    ).toHaveLength(0)
  })

  it('reports when nothing matches', async () => {
    global.fetch = stubFetch({ locations: { query: 'zz', count: 0, results: [] } })
    render(<App />)
    await userEvent.type(screen.getByRole('textbox', { name: /town, county or region/i }), 'zzzz')
    expect(await screen.findByText(/no kenyan location matches/i)).toBeInTheDocument()
  })
})
