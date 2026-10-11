import clsx from 'clsx'
import { LANGUAGES } from '../lib/languages'

function Dot({ tone }) {
  return (
    <span
      className={clsx('inline-block h-1.5 w-1.5', {
        'bg-ok': tone === 'ok',
        'bg-err': tone === 'err',
        'bg-warn': tone === 'warn',
        'bg-mute': tone === 'idle',
      })}
    />
  )
}

export default function StatusBar({ health, language, provider, model, cursor, lastDuration }) {
  let sandbox = { tone: 'idle', text: 'checking sandbox…' }
  if (health.state === 'offline') sandbox = { tone: 'err', text: 'backend offline' }
  else if (health.state === 'ok' && !health.docker) sandbox = { tone: 'err', text: 'docker not running' }
  else if (health.state === 'ok' && health.images && health.images[language] === false)
    sandbox = { tone: 'warn', text: `${language} image not pulled` }
  else if (health.state === 'ok') sandbox = { tone: 'ok', text: `docker · ${health.container_runtime}` }

  return (
    <footer className="flex h-6 shrink-0 items-center justify-between border-t border-line bg-surface px-3 font-mono text-[11px] text-dim">
      <div className="flex min-w-0 items-center gap-4">
        <span className="flex items-center gap-1.5" title={health.docker_error || health.error || ''}>
          <Dot tone={sandbox.tone} /> {sandbox.text}
        </span>
        <span className="truncate">{provider && model ? `${provider} · ${model}` : 'no model selected'}</span>
      </div>
      <div className="flex items-center gap-4">
        <span className="hidden sm:inline">{LANGUAGES[language].runtime}</span>
        <span>
          ln {cursor.line}, col {cursor.col}
        </span>
        {lastDuration !== null && <span>{(lastDuration / 1000).toFixed(2)}s</span>}
      </div>
    </footer>
  )
}
