/**
 * Skeleton shaped like the real dashboard.
 *
 * The blocks match the final layout's proportions - hero, metric row, forecast
 * rows - so content does not jump when it arrives. A generic spinner would be
 * less work and a worse experience.
 */
export default function LoadingState({ label }) {
  return (
    <div className="skeleton" role="status" aria-live="polite">
      <span className="visually-hidden">
        {label ? `Loading weather for ${label}` : 'Loading weather'}
      </span>
      <div className="skeleton__bar skeleton__bar--place" />
      <div className="skeleton__bar skeleton__bar--temp" />
      <div className="skeleton__row">
        <div className="skeleton__bar skeleton__bar--cell" />
        <div className="skeleton__bar skeleton__bar--cell" />
        <div className="skeleton__bar skeleton__bar--cell" />
        <div className="skeleton__bar skeleton__bar--cell" />
      </div>
      <div className="skeleton__bar skeleton__bar--panel" />
      <div className="skeleton__bar skeleton__bar--panel" />
    </div>
  )
}
