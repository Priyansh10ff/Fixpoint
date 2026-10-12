import { LANGUAGES } from '../lib/languages'
import StatusTag from './StatusTag'

function ContextBox({ ctx }) {
  const where = [ctx.line && `line ${ctx.line}`, ctx.function && ctx.function !== '<module>' && `in ${ctx.function}()`]
    .filter(Boolean)
    .join(' ')
  const locals = Object.entries(ctx.locals || {})
  return (
    <div className="mb-3 border border-line bg-surface">
      <div className="flex flex-wrap items-baseline gap-2 border-b border-line px-3 py-1.5">
        <span className="text-err">{ctx.error_type}</span>
        {where && <span className="text-dim">{where}</span>}
        {ctx.message && <span className="truncate text-mute">— {ctx.message}</span>}
      </div>
      {locals.length > 0 && (
        <table className="w-full text-[12px]">
          <caption className="label px-3 pt-2 text-left text-mute">locals at crash</caption>
          <tbody>
            {locals.map(([k, v]) => (
              <tr key={k} className="align-top">
                <td className="w-1 whitespace-nowrap px-3 py-0.5 text-accent">{k}</td>
                <td className="break-all px-3 py-0.5 text-text">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export default function Terminal({ result, running, language, error, stale, onSwitchLanguage }) {
  if (running) {
    return (
      <div className="flex items-center gap-3 p-4 font-mono text-[13px]">
        <StatusTag status="running" />
        <span className="text-dim">$ {LANGUAGES[language].command}</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-2 p-4 font-mono text-[13px]">
        <StatusTag status="error" />
        <p className="text-err">{error}</p>
      </div>
    )
  }

  if (!result) {
    return (
      <div className="p-4 font-mono text-[13px] text-mute">
        No output yet. Run with Ctrl+Enter, or press Fix to run and repair.
      </div>
    )
  }

  const hint = result.language_hint
  return (
    <div className="p-4 font-mono text-[13px] leading-relaxed">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <StatusTag status={result.status} />
        <span className="text-dim">$ {LANGUAGES[result.language].command}</span>
        <span className="text-mute">
          {result.exit_code !== null && result.exit_code !== undefined ? `exit ${result.exit_code} · ` : ''}
          {(result.duration_ms / 1000).toFixed(2)}s
        </span>
      </div>

      {stale && <p className="mb-3 text-mute">› this output is from a different version of the code than the editor shows</p>}

      {hint && (
        <div className="mb-3 border border-warn/40 bg-warn/5 px-3 py-2 text-warn">
          This looks like {LANGUAGES[hint].label}, but it ran as {LANGUAGES[result.language].label}.{' '}
          <button type="button" className="underline underline-offset-2 hover:text-text" onClick={() => onSwitchLanguage(hint)}>
            Switch to {LANGUAGES[hint].label}
          </button>
        </div>
      )}

      {result.context && <ContextBox ctx={result.context} />}

      {result.stdout && <pre className="whitespace-pre-wrap break-words text-text">{result.stdout}</pre>}
      {result.stderr && <pre className="whitespace-pre-wrap break-words text-err">{result.stderr}</pre>}
      {!result.stdout && !result.stderr && <p className="text-mute">(no output)</p>}
      {result.message && result.status !== 'ok' && <p className="mt-3 text-dim">› {result.message}</p>}
    </div>
  )
}
