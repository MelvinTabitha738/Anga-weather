import { messageForError } from '../lib/messages'

/**
 * A calm, actionable failure.
 *
 * Wording comes from the error CODE, never from backend prose, so no internal
 * detail can reach the screen. Retry is offered only where retrying could
 * plausibly help.
 */
export default function ErrorState({ error, onRetry, onBack }) {
  const { title, body } = messageForError(error)
  // A monthly quota lockout clears at a fixed time; an immediate retry only
  // adds load and disappoints.
  const canRetry = error?.code !== 'rate_limited' && error?.code !== 'too_many_requests'

  return (
    <section className="state" role="alert">
      <h1 className="state__title">{title}</h1>
      <p className="state__body">{body}</p>
      <div className="state__actions">
        {canRetry && onRetry && (
          <button type="button" className="button" onClick={onRetry}>
            Try again
          </button>
        )}
        {onBack && (
          <button type="button" className="button button--quiet" onClick={onBack}>
            Choose another location
          </button>
        )}
      </div>
    </section>
  )
}
