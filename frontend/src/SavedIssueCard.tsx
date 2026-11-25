import type { DeliveryState, SavedIssue } from './repository-api'

const deliveryText: Record<DeliveryState, string> = {
  queued: 'Queued locally',
  sending: 'Sending to GitHub',
  applied: 'Applied on GitHub',
  failed: 'Needs attention',
  superseded: 'Superseded',
}

type Props = {
  issue: SavedIssue
  busy: boolean
  description: string | null
  onDescription: () => void
  onQueue: () => void
}

export default function SavedIssueCard({ issue, busy, description, onDescription, onQueue }: Props) {
  const delivery = issue.delivery_state
  const reviewed = issue.review_status === 'approved' || issue.review_status === 'corrected'

  return (
    <article className="review">
      <p className="repo">#{issue.number} · {issue.state} · {issue.review_status}</p>
      <h3>{issue.title}</h3>
      {delivery && (
        <div className="scores" aria-label="GitHub delivery">
          <strong>{deliveryText[delivery]}</strong>
          {issue.delivered_at && (
            <span><time dateTime={issue.delivered_at}>{new Date(issue.delivered_at).toLocaleString()}</time></span>
          )}
        </div>
      )}
      {delivery && issue.delivery_error && (
        <p className={delivery === 'failed' ? 'message error' : 'message'}>{issue.delivery_error}</p>
      )}
      {!delivery && reviewed && <p className="repo">No GitHub update recorded.</p>}
      <div className="actions">
        <button type="button" disabled={busy} onClick={onDescription}>
          {description === null ? 'Read description' : 'Hide description'}
        </button>
        <button type="button" className="primary" disabled={busy || issue.review_status !== 'unreviewed'}
          onClick={onQueue}>Send to review</button>
      </div>
      {description !== null && (
        <p className="message" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
          {description || 'No description.'}
        </p>
      )}
    </article>
  )
}
