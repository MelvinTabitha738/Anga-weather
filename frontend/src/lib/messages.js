/**
 * Backend error codes -> language a person can act on.
 *
 * The API returns machine codes precisely so the UI can own the wording. No
 * backend prose, status code or internal detail is ever shown to the user.
 */

const ERROR_MESSAGES = {
  invalid_location: {
    title: 'That location does not look right',
    body: 'Please choose a Kenyan county or town from the suggestions.',
  },
  unknown_location: {
    title: 'We do not cover that place yet',
    body: 'Anga currently covers Kenyan counties and major towns. Try Nairobi, Kisumu or Eldoret.',
  },
  rate_limited: {
    title: 'The weather service is busy',
    body: 'We have reached our limit with the weather provider for now. Recently cached weather is shown wherever we have it.',
  },
  weather_unavailable: {
    title: 'We could not refresh the weather',
    body: 'The weather service is temporarily unreachable and we have nothing recent saved for this location. Please try again shortly.',
  },
  too_many_requests: {
    title: 'Just a moment',
    body: 'That is a lot of searches very quickly. Give it a few seconds and try again.',
  },
  network_error: {
    title: 'No connection',
    body: 'We could not reach Anga. Check your internet connection and try again.',
  },
  invalid_units: {
    title: 'Unsupported units',
    body: 'Anga supports Celsius and Fahrenheit only.',
  },
}

const FALLBACK = {
  title: 'Something went wrong',
  body: 'We could not load the weather just now. Please try again shortly.',
}

export function messageForError(error) {
  return ERROR_MESSAGES[error?.code] || FALLBACK
}

/**
 * Human phrasing for data age, e.g. "just now", "14 minutes ago".
 * Used for the freshness line, which must never overstate how current the
 * reading is - so this always rounds DOWN to the completed unit.
 */
export function formatAge(seconds) {
  const value = Number(seconds)
  if (!Number.isFinite(value) || value < 0) return null
  if (value < 60) return 'just now'

  const minutes = Math.floor(value / 60)
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`

  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`

  const days = Math.floor(hours / 24)
  return `${days} day${days === 1 ? '' : 's'} ago`
}

/** The notice shown above the reading when data is not fresh. */
export function stalenessNotice(meta) {
  if (!meta?.is_stale) return null

  const age = formatAge(meta.age_seconds)
  const when = age ? ` from ${age}` : ''

  if (meta.fallback_reason === 'rate_limited' || meta.fallback_reason === 'quota_reserve') {
    return `Live updates are paused — showing the last reading we saved${when}.`
  }
  return `We could not refresh just now — showing the last reading we saved${when}.`
}
