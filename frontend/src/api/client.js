/**
 * Client for the Anga backend.
 *
 * The browser talks only to our Django API - never to Weather-AI. There is no
 * upstream key in this bundle, and no code path that could add one.
 */

const BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(
  /\/+$/,
  '',
)

export class ApiError extends Error {
  constructor(code, message, { status = 0, retryAfter = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.retryAfter = retryAfter
  }
}

async function request(path, { signal } = {}) {
  let response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      signal,
      headers: { Accept: 'application/json' },
    })
  } catch (error) {
    // AbortError is a normal consequence of the user typing again; let the
    // caller distinguish it from a genuine network failure.
    if (error?.name === 'AbortError') throw error
    throw new ApiError('network_error', 'Network request failed.')
  }

  let body = null
  try {
    body = await response.json()
  } catch {
    body = null
  }

  if (!response.ok) {
    const error = body?.error || {}
    throw new ApiError(error.code || 'request_error', error.message || 'Request failed.', {
      status: response.status,
      retryAfter: error.retry_after ?? null,
    })
  }

  return body
}

export function fetchWeather(location, { units = 'metric', signal } = {}) {
  const params = new URLSearchParams({ location, units })
  return request(`/api/weather/?${params}`, { signal })
}

export function searchLocations(query, { limit = 8, signal } = {}) {
  const params = new URLSearchParams({ q: query ?? '', limit: String(limit) })
  return request(`/api/locations/?${params}`, { signal })
}
