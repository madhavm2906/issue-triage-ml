import { StrictMode, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import RepositoryIssues from './RepositoryIssues.tsx'

function Workspace() {
  const [screen, setScreen] = useState<'issues' | 'reviews'>('issues')
  const [repo, setRepo] = useState('microsoft/vscode')

  return (
    <>
      <nav className="shell" aria-label="Workspace" style={{ paddingBottom: 0 }}>
        <div className="actions">
          <button type="button" aria-pressed={screen === 'issues'}
            className={screen === 'issues' ? 'primary' : ''}
            onClick={() => setScreen('issues')}>Repository Issues</button>
          <button type="button" aria-pressed={screen === 'reviews'}
            className={screen === 'reviews' ? 'primary' : ''}
            onClick={() => setScreen('reviews')}>Review Queue</button>
        </div>
      </nav>
      {screen === 'issues'
        ? <RepositoryIssues key={repo} repo={repo} openRepo={setRepo} />
        : <App />}
    </>
  )
}

const root = document.getElementById('root')
if (!root) throw new Error('Root element is missing.')

createRoot(root).render(
  <StrictMode>
    <Workspace />
  </StrictMode>,
)
