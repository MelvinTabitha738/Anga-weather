import {
  formatDayName,
  formatTemperature,
  rainfallCell,
  rainfallUnit,
  temperatureBar,
  weekRange,
} from '../lib/format'
import { RainDropIcon } from './MetricIcon'
import WeatherIcon from './WeatherIcon'

/**
 * The week ahead.
 *
 * Two decisions worth stating:
 *
 * 1. **Every row carries a rainfall value.** Weather-AI returns a figure for
 *    every day including 0.0, so a dry day is known, not missing. Showing
 *    nothing made an explicit "no rain" read as "no data" and left the reader
 *    wondering why only some rows had a number. Dry days now show an em dash.
 * 2. **The unit is stated once**, in the column legend, rather than repeated
 *    seven times. Each cell still carries a full spoken label for screen
 *    readers, since the legend is not adjacent to the value.
 *
 * Each row also carries a bar showing where that day's low-to-high sits inside
 * the week's range, turning fourteen numbers into a shape you can read at a
 * glance.
 */
export default function DailyForecast({ days, units = 'metric' }) {
  if (!days?.length) return null

  const { weekMin, weekMax } = weekRange(days)

  return (
    <section className="panel" aria-labelledby="daily-heading">
      <div className="panel__head">
        <h2 className="panel__title" id="daily-heading">
          Next {days.length} days
        </h2>
        <p className="panel__legend">
          <RainDropIcon className="panel__legend-icon" />
          Rainfall ({rainfallUnit(units)})
        </p>
      </div>

      <ul className="daily">
        {days.map((day, index) => {
          const bar = temperatureBar(day, weekMin, weekMax)
          const rain = rainfallCell(day.precipitation, units)

          return (
            <li className="daily__row" key={day.date || index}>
              <span className="daily__day">{formatDayName(day.date, index)}</span>

              <span className="daily__icon">
                <WeatherIcon
                  group={day.condition_group}
                  intensity={day.condition_intensity}
                  isDay
                  temperature={day.temp_max}
                  size={24}
                  label={day.condition || undefined}
                />
              </span>

              <span
                className={`daily__rain${rain.dry ? ' daily__rain--dry' : ''}`}
                title={rain.label}
              >
                <span aria-hidden="true">{rain.text}</span>
                <span className="visually-hidden">{rain.label}</span>
              </span>

              <span className="daily__low">{formatTemperature(day.temp_min) ?? '—'}</span>

              <span className="daily__track" aria-hidden="true">
                {bar && (
                  <span
                    className="daily__bar"
                    style={{ left: `${bar.left}%`, width: `${bar.width}%` }}
                  />
                )}
              </span>

              <span className="daily__high">{formatTemperature(day.temp_max) ?? '—'}</span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
