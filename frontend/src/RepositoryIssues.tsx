import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import SavedIssueCard from './SavedIssueCard'
import { listIssues, normalizeRepository, queueIssue, readDescription, syncIssues } from './repository-api'
import type { IssuePage, SavedIssue } from './repository-api'

type Props = { repo: string; openRepo: (repo: string) => void }

function message(error: unknown) {
  return error instanceof Error ? error.message : 'Request failed.'
}

export default function RepositoryIssues({ repo, openRepo }: Props) {
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

  async function loadFirstPage() {
    setPage(await listIssues(repo))
    setDetail(null)
  }

  function selectRepo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void run(async () => {
      const selected = normalizeRepository(draft)
      if (selected === repo) await loadFirstPage()
      else openRepo(selected)
    })
  }

  function sync() {
    void run(async () => {
      const result = await syncIssues(repo)
      await loadFirstPage()
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
      if (result.status === 'pending') {
        setPage((current) => current && {
          ...current,
          issues: current.issues.map((row) => row.github_id === issue.github_id
            ? { ...row, review_status: 'pending' } : row),
        })
        setNotice('Queued for review.')
      } else {
        await loadFirstPage()
        setNotice('Already reviewed.')
      }
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
          <div className="add-controls">
            <button type="button" disabled={busy} onClick={() => void run(loadFirstPage)}>Refresh</button>
            <button type="button" disabled={busy} onClick={sync}>Sync latest page</button>
          </div>
        </div>
        {page?.issues.length === 0 && <p className="empty">No saved issues.</p>}
        {page?.issues.map((issue) => (
          <SavedIssueCard key={issue.github_id} issue={issue} busy={busy}
            description={detail?.number === issue.number ? detail.body : null}
            onDescription={() => describe(issue)} onQueue={() => queue(issue)} />
        ))}
        {page?.next_before != null && (
          <button type="button" disabled={busy} onClick={more}>Load older issues</button>
        )}
      </section>
    </main>
  )
}
