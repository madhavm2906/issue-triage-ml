export type DeliveryState = 'queued' | 'sending' | 'applied' | 'failed' | 'superseded'

export type SavedIssue = {
  github_id: string
  number: number
  title: string
  state: 'open' | 'closed'
  review_status: 'unreviewed' | 'pending' | 'approved' | 'corrected'
  delivery_state: DeliveryState | null
  delivery_error: string | null
  delivered_at: string | null
}

export type IssuePage = {
  repository: string
  issues: SavedIssue[]
  next_before: number | null
}

export function normalizeRepository(value: string) {
  const match = value.trim().match(/^([a-z0-9_-]+)\/([a-z0-9_.-]+)$/i)
  if (!match || match[2] === '.' || match[2] === '..') {
    throw new Error('Enter a repository in owner/repo format.')
  }
  return match[0].toLowerCase()
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options)
  const payload = await response.json().catch(() => null)
  if (!response.ok || payload === null) {
    const detail = payload?.detail
    throw new Error(typeof detail === 'string' ? detail : 'Request failed (' + response.status + ').')
  }
  return payload as T
}

export function listIssues(repo: string, before?: number) {
  const query = new URLSearchParams({ limit: '25' })
  if (before !== undefined) query.set('before', String(before))
  return request<IssuePage>('/repositories/' + repo + '/issues?' + query)
}

export function readDescription(repo: string, number: number) {
  return request<{ body: string }>('/repositories/' + repo + '/issues/' + number)
}

export function syncIssues(repo: string) {
  return request<{ fetched: number }>(
    '/repositories/' + repo + '/import?state=all&page=1&per_page=100',
    { method: 'POST' },
  )
}

export function queueIssue(issueId: string) {
  return request<{ status: SavedIssue['review_status'] }>('/reviews', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ issue_id: issueId }),
  })
}
