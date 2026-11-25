import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

type Label = 'bug' | 'feature-request'

type Review = {
  id: number
  repository: string
  number: number
  title: string
  body: string
  suggested_label: Label
  bug_score: number
  bug_cutoff: number
  status: 'pending' | 'approved' | 'corrected'
}

function labelText(label: Label) {
  return label === 'bug' ? 'bug' : 'feature request'
}

async function api<T>(path: string, method = 'GET', body?: object): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await response.json().catch(() => null)
  if (!response.ok || data === null) {
    const detail = data?.detail
    throw new Error(typeof detail === 'string' ? detail : `Request failed (HTTP ${response.status})`)
  }
  return data as T
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : 'Request failed.'
}

export default function App() {
  const [reviews, setReviews] = useState<Review[]>([])
  const [issueId, setIssueId] = useState('')
  const [busy, setBusy] = useState(true)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    api<Review[]>('/reviews')
      .then((rows) => { if (active) setReviews(rows) })
      .catch((reason: unknown) => { if (active) setError(errorText(reason)) })
      .finally(() => { if (active) setBusy(false) })
    return () => { active = false }
  }, [])

  async function run(action?: () => Promise<string>) {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      if (action) setNotice(await action())
      setReviews(await api<Review[]>('/reviews'))
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setBusy(false)
    }
  }

  function addIssue(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void run(async () => {
      const row = await api<Review>('/reviews', 'POST', { issue_id: issueId.trim() })
      setIssueId('')
      return row.status === 'pending' ? 'Added to queue.' : 'Already reviewed.'
    })
  }

  function decide(row: Review, label: Label) {
    void run(async () => {
      const saved = await api<Review>(`/reviews/${row.id}`, 'PATCH', { final_label: label })
      return saved.status === 'approved'
        ? `Approved as ${labelText(label)}.`
        : `Changed to ${labelText(label)}.`
    })
  }

  return (
    <main className="shell">
      <header className="banner">
        <h1>Issue Triage</h1>
      </header>

      <form className="add" onSubmit={addIssue}>
        <label htmlFor="issue-id">Imported GitHub issue ID</label>
        <div className="add-controls">
          <input id="issue-id" inputMode="numeric" pattern="[0-9]+" required
            value={issueId} onChange={(event) => setIssueId(event.target.value)} disabled={busy} />
          <button className="primary" disabled={busy}>Add to queue</button>
        </div>
        <small>Use the imported github_id.</small>
      </form>

      {error && <p className="message error" role="alert">{error}</p>}
      {notice && <p className="message" role="status">{notice}</p>}

      <section aria-labelledby="queue-heading" aria-busy={busy}>
        <div className="queue-head">
          <h2 id="queue-heading">Pending reviews</h2>
          <button type="button" disabled={busy}
            onClick={() => void run()}>Refresh</button>
        </div>

        {reviews.length === 0 && !error && (
          <p className="empty">{busy ? 'Loading…' : 'No pending issues.'}</p>
        )}

        {reviews.map((row) => {
          const alternative: Label = row.suggested_label === 'bug' ? 'feature-request' : 'bug'
          return (
            <article key={row.id} className="review">
              <p className="repo">{row.repository} #{row.number}</p>
              <h3>{row.title}</h3>
              <p className="scores">
                <strong>Suggested {labelText(row.suggested_label)}</strong>
                <span>Bug score {row.bug_score.toFixed(3)} · Cutoff {row.bug_cutoff.toFixed(2)}</span>
              </p>
              <details>
                <summary>Issue description</summary>
                <p>{row.body || 'No description.'}</p>
              </details>
              <div className="actions">
                <button type="button" className="primary" disabled={busy}
                  onClick={() => decide(row, row.suggested_label)}>Approve suggestion</button>
                <button type="button" disabled={busy} onClick={() => decide(row, alternative)}>
                  Change to {labelText(alternative)}
                </button>
              </div>
            </article>
          )
        })}
      </section>
    </main>
  )
}
