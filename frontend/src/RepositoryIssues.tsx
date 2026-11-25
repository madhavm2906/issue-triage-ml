import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { listIssues, normalizeRepository, queueIssue, readDescription, syncIssues } from './repository-api'
import type { IssuePage, SavedIssue } from './repository-api'

function message(error: unknown) {
  return error instanceof Error ? error.message : 'Request failed.'
}

export default function RepositoryIssues({ repo, openRepo }: { repo: string; openRepo: (repo: string) => void }) {
  const [draft, setDraft] = useState(repo)
  const [page, setPage] = useState<IssuePage | null>(null)
  const [detail, setDetail] = useState<{ number: number; body: string } | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    let active = true
    listIssues(repo)
      .then((result) => { if (active) setPage(result) })
      .catch((reason: unknown) => { if (active) setError(message(reason)) })
      .finally(() => { if (active) setBusy(false) })
    return () => { active = false }
  }, [repo])

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await action()
    } catch (reason) {
      setError(message(reason))
    } finally {
      setBusy(false)
    }
  }

  function selectRepo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void run(async () => {
      const selected = normalizeRepository(draft)
      if (selected !== repo) {
        openRepo(selected)
        return
      }
      setPage(await listIssues(repo))
      setDetail(null)
    })
  }

  function sync() {
    void run(async () => {
      const result = await syncIssues(repo)
      setPage(await listIssues(repo))
      setDetail(null)
      setNotice('Synced ' + result.fetched + ' issues.')
    })
  }

  function more() {
    const before = page?.next_before
    if (before == null) return
    void run(async () => {
      const next = await listIssues(repo, before)
      setPage((current) => current && {
        ...next, issues: [...current.issues, ...next.issues],
      })
    })
  }

  function describe(issue: SavedIssue) {
    if (detail?.number === issue.number) {
      setDetail(null)
      return
    }
    void run(async () => {
      const result = await readDescription(repo, issue.number)
      setDetail({ number: issue.number, body: result.body })
    })
  }

  function queue(issue: SavedIssue) {
    void run(async () => {
      const result = await queueIssue(issue.github_id)
      setPage((current) => current && {
        ...current,
        issues: current.issues.map((row) => row.github_id === issue.github_id
          ? { ...row, review_status: result.status } : row),
      })
      setNotice(result.status === 'pending' ? 'Queued.' : 'Already reviewed.')
    })
  }

  return (
    <main className="shell">
      <header className="banner"><h1>Repository Issues</h1></header>
      <form className="add" onSubmit={selectRepo}>
        <label htmlFor="repo">Repository</label>
        <div className="add-controls">
          <input id="repo" value={draft} placeholder="owner/repo" required disabled={busy}
            onChange={(event) => setDraft(event.target.value)} />
          <button className="primary" disabled={busy}>Open</button>
        </div>
      </form>
      {error && <p className="message error" role="alert">{error}</p>}
      {notice && <p className="message" role="status">{notice}</p>}

      <section aria-label="Saved issues" aria-busy={busy}>
        <div className="queue-head">
          <h2>{repo}</h2>
          <button type="button" disabled={busy} onClick={sync}>Sync latest page</button>
        </div>
        {page?.issues.length === 0 && <p className="empty">No saved issues.</p>}

        {page?.issues.map((issue) => (
          <article className="review" key={issue.github_id}>
            <p className="repo">#{issue.number} · {issue.state} · {issue.review_status}</p>
            <h3>{issue.title}</h3>
            <div className="actions">
              <button type="button" disabled={busy} onClick={() => describe(issue)}>
                {detail?.number === issue.number ? 'Hide description' : 'Read description'}
              </button>
              <button type="button" className="primary" disabled={busy || issue.review_status !== 'unreviewed'}
                onClick={() => queue(issue)}>Send to review</button>
            </div>
            {detail?.number === issue.number && (
              <p className="message" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
                {detail.body || 'No description.'}
              </p>
            )}
          </article>
        ))}
        {page?.next_before != null && (
          <button type="button" disabled={busy} onClick={more}>Load older issues</button>
        )}
      </section>
    </main>
  )
}
