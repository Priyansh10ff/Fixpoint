import clsx from 'clsx'
import { Check, Eye, Square } from 'lucide-react'
import { useEffect, useState } from 'react'
import StatusTag from './StatusTag'

const pad = (n) => String(n).padStart(2, '0')

function failureText(run) {
  if (!run) return null
  const ctx = run.context
  if (!ctx) return run.message || run.status
  return `${ctx.error_type}${ctx.line ? ` · line ${ctx.line}` : ''}`
}

function Elapsed({ from, to }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (to) return
    const id = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(id)
  }, [to])
  if (!from) return null
  return <span>{(((to || now) - from) / 1000).toFixed(1)}s</span>
}

function Row({ index, label, tag, children, active }) {
  return (
    <li className={clsx('border-b border-line px-3 py-2.5', active && 'bg-surface')}>
      <div className="flex items-center gap-2 font-mono text-[12px]">
        <span className="text-mute">{index}</span>
        <span className="label text-dim">{label}</span>
        <span className="ml-auto">{tag}</span>
      </div>
      {children && <div className="mt-1.5 pl-6 font-mono text-[12px] leading-relaxed">{children}</div>}
    </li>
  )
}

const VERDICT_TONE = {
  fixed: 'border-ok/50 bg-ok/5',
  partial: 'border-warn/50 bg-warn/5',
  unverified: 'border-warn/50 bg-warn/5',
  unresolved: 'border-err/50 bg-err/5',
  error: 'border-err/50 bg-err/5',
}

export default function AgentPanel({ session, viewing, onView, onApply, onCancel }) {
  const { state, baseline, attempts, final } = session
  const running = state === 'running'

  return (
    <aside className="flex h-full w-[360px] shrink-0 flex-col border-l border-line bg-bg" aria-label="Agent">
      <div className="flex h-8 shrink-0 items-center gap-3 border-b border-line bg-surface px-3">
        <span className="label text-text">agent</span>
        {session.model && <span className="truncate font-mono text-[11px] text-mute">{session.model}</span>}
        <span className="ml-auto font-mono text-[11px] text-mute">
          <Elapsed from={session.startedAt} to={session.endedAt} />
        </span>
      </div>

      {state === 'idle' ? (
        <div className="space-y-3 p-4 font-mono text-[12px] leading-relaxed text-mute">
          <p>
            <span className="text-dim">FIX</span> runs your code, asks the model for a patch, re-runs the patch in the
            sandbox, and retries with what it learned until the program runs cleanly.
          </p>
          <p>Each attempt shows up here: the hypothesis, the patch, and the re-run result.</p>
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto" aria-live="polite">
          <ol>
            <Row
              index="00"
              label="baseline"
              tag={baseline ? <StatusTag status={baseline.status} /> : <StatusTag status="running" />}
            >
              {baseline && baseline.status !== 'ok' && <span className="text-err">{failureText(baseline)}</span>}
              {baseline?.status === 'ok' && <span className="text-mute">ran without errors</span>}
            </Row>

            {attempts.map((a) => (
              <Row
                key={a.n}
                index={pad(a.n)}
                label="attempt"
                tag={<StatusTag status={a.phase} />}
                active={viewing === a.n}
              >
                {a.diagnosis?.hypothesis && <p className="text-dim">{a.diagnosis.hypothesis}</p>}
                {a.guard && <p className="mt-1 text-warn">› {a.guard}</p>}
                {a.run && a.phase !== 'passed' && (
                  <p className={clsx('mt-1', a.phase === 'progress' ? 'text-warn' : 'text-err')}>
                    › {a.phase === 'progress' ? 'error moved: ' : ''}
                    {failureText(a.run)}
                  </p>
                )}
                {a.phase === 'passed' && <p className="mt-1 text-ok">› re-run passed</p>}
                {a.patch && (
                  <button
                    type="button"
                    onClick={() => onView(a.n)}
                    className="label mt-1.5 inline-flex items-center gap-1 text-mute hover:text-text"
                  >
                    <Eye className="h-3 w-3" /> view patch · {a.patch.changed_lines} line
                    {a.patch.changed_lines === 1 ? '' : 's'}
                  </button>
                )}
              </Row>
            ))}
          </ol>

          {running && (
            <div className="p-3">
              <button type="button" onClick={onCancel} className="btn-secondary focus-ring w-full justify-center">
                <Square className="h-3 w-3" /> Stop
              </button>
            </div>
          )}

          {state === 'error' && (
            <div className="m-3 border border-err/50 bg-err/5 p-3 font-mono text-[12px] text-err">{session.error}</div>
          )}

          {final && (
            <div className={clsx('m-3 border p-3', VERDICT_TONE[final.status] || 'border-line bg-surface')}>
              <div className="flex items-center gap-2">
                <StatusTag status={final.status} className="text-[12px]" />
                {final.attempts > 0 && (
                  <span className="font-mono text-[11px] text-mute">
                    {final.attempts} attempt{final.attempts === 1 ? '' : 's'}
                  </span>
                )}
              </div>
              <p className="mt-2 font-sans text-[13px] leading-relaxed text-dim">{final.message}</p>
              {final.final_code && (
                <div className="mt-3 flex gap-2">
                  <button type="button" onClick={onApply} className="btn-primary focus-ring">
                    <Check className="h-3.5 w-3.5" /> Apply
                  </button>
                  <button type="button" onClick={() => onView('final')} className="btn-secondary focus-ring">
                    <Eye className="h-3.5 w-3.5" /> Diff
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </aside>
  )
}
