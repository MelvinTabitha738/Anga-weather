import { formatHour, formatTemperature, rainfallCell, rainfallUnit } from '../lib/format'
import { RainDropIcon } from './MetricIcon'
import WeatherIcon from './WeatherIcon'

/**
 * Today's hour-by-hour outlook.
 *
 * Comes from the `hourly` series already present in the cached upstream
 * response, so rendering it costs no additional Weather-AI quota.
 *
 * The rainfall line is always rendered, even when dry. Conditionally rendering
 * it made columns with rain taller than columns without, so the strip visibly
 * jittered out of alignment - and, as in the daily list, an absent value read
 * as "unknown" when the API had explicitly said zero.
 *
 * Horizontally scrollable rather than wrapped: a single timeline reads as time
 * passing. The container scrolls, never the page.
 */
export default function HourlyStrip({ hours, units = 'metric' }) {
  if (!hours?.length) return null

  return (
    <section className="panel" aria-labelledby="hourly-heading">
      <div className="panel__head">
        <h2 className="panel__title" id="hourly-heading">
          Today&rsquo;s outlook
        </h2>
        <p className="panel__legend">
          <RainDropIcon className="panel__legend-icon" />
          Rainfall ({rainfallUnit(units)})
        </p>
      </div>

      <ol className="hourly" tabIndex={0} aria-label="Hourly forecast">
        {hours.map((hour, index) => {
          const rain = rainfallCell(hour.precipitation, units)
          return (
            <li className="hourly__item" key={hour.time || index}>
              <span className="hourly__time">
                {index === 0 ? 'Now' : formatHour(hour.time)}
              </span>
              <WeatherIcon
                group={hour.condition_group}
                intensity={hour.condition_intensity}
                // The hourly series carries no is_day flag, so hours are drawn
                // in their daytime form; the icon still conveys the condition.
                isDay
                size={26}
                className="hourly__icon"
              />
              <span className="hourly__temp">
                {formatTemperature(hour.temperature) ?? '—'}
              </span>
              <span
                className={`hourly__rain${rain.dry ? ' hourly__rain--dry' : ''}`}
                title={rain.label}
              >
                <span aria-hidden="true">{rain.text}</span>
                <span className="visually-hidden">{rain.label}</span>
              </span>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
