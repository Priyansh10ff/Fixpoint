import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import StatusTag from './StatusTag'

export default function DebugPanel({ debug }) {
  const { state, data, error } = debug

  if (state === 'loading') {
    return (
      <div className="flex items-center gap-3 p-4 font-mono text-[13px]">
        <StatusTag status="fixing" />
        <span className="text-dim">running in sandbox, then asking the model…</span>
      </div>
    )
  }

  if (state === 'error') {
    return (
      <div className="space-y-2 p-4 font-mono text-[13px]">
        <StatusTag status="error" />
        <p className="text-err">{error}</p>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="p-4 font-mono text-[13px] text-mute">
        Press Fix (Ctrl+Shift+Enter). Fixpoint runs your code, reads the real output, and proposes a fix.
      </div>
    )
  }

  const { diagnosis, changed, provider, model } = data
  return (
    <div className="p-4">
      <div className="mb-3 flex flex-wrap items-center gap-3 font-mono text-[13px]">
        <StatusTag status={changed ? 'fix_ready' : 'no_change'} />
        <span className="text-text">{diagnosis.error_type}</span>
        <span className="text-mute">
          {provider} · {model}
        </span>
      </div>
      <div className="prose prose-invert prose-sm max-w-3xl font-sans prose-headings:font-mono prose-strong:text-text prose-code:rounded-none prose-code:bg-surface-2 prose-code:px-1 prose-code:py-0.5 prose-code:font-mono prose-code:text-[12px] prose-code:font-normal prose-code:text-accent prose-code:before:content-none prose-code:after:content-none prose-pre:rounded-none prose-pre:border prose-pre:border-line prose-pre:bg-bg">
        <h4 className="label !mb-1 !mt-0 text-dim">root cause</h4>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{diagnosis.root_cause}</ReactMarkdown>
        <h4 className="label !mb-1 text-dim">fix</h4>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{diagnosis.fix_summary}</ReactMarkdown>
      </div>
      {!changed && <p className="mt-3 font-mono text-[12px] text-mute">The model proposed no code changes.</p>}
      <p className="mt-4 border-t border-line pt-3 font-mono text-[11px] text-mute">
        Unverified: this fix has not been re-run yet. Automatic verification arrives in Phase 2.
      </p>
    </div>
  )
}
