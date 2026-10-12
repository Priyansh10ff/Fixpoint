import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { latestDiagnosis } from '../lib/fixSession'
import StatusTag from './StatusTag'

const PROSE =
  'prose prose-invert prose-sm max-w-3xl font-sans prose-headings:font-mono prose-strong:text-text prose-code:rounded-none prose-code:bg-surface-2 prose-code:px-1 prose-code:py-0.5 prose-code:font-mono prose-code:text-[12px] prose-code:font-normal prose-code:text-accent prose-code:before:content-none prose-code:after:content-none prose-pre:rounded-none prose-pre:border prose-pre:border-line prose-pre:bg-bg'

const NOTES = {
  fixed: 'The patched program was re-run in the sandbox and finished without errors. Output correctness is checked once test cases arrive (Phase 3).',
  partial: 'The first error is fixed but the program still fails. The diff shows the partial fix.',
  unresolved: 'No attempt produced a program that runs cleanly. The analysis below is from the last attempt.',
  unverified: 'The program already ran cleanly, so this change could not be verified. Treat it as a suggestion.',
}

export default function DebugPanel({ session }) {
  const { state, final, error } = session
  const diagnosis = latestDiagnosis(session)

  if (state === 'idle') {
    return (
      <div className="p-4 font-mono text-[13px] text-mute">
        Press Fix (Ctrl+Shift+Enter). Fixpoint runs your code, patches it, re-runs the patch, and retries until it
        passes. The root cause appears here.
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
  if (!diagnosis) {
    return (
      <div className="flex items-center gap-3 p-4 font-mono text-[13px]">
        {final ? <StatusTag status={final.status} /> : <StatusTag status="fixing" />}
        <span className="text-dim">{final ? final.message : 'running in sandbox, then asking the model…'}</span>
      </div>
    )
  }

  return (
    <div className="p-4">
      <div className="mb-3 flex flex-wrap items-center gap-3 font-mono text-[13px]">
        <StatusTag status={final ? final.status : 'fixing'} />
        <span className="text-text">{diagnosis.error_type}</span>
        <span className="text-mute">
          {session.provider} · {session.model}
        </span>
      </div>
      {diagnosis.hypothesis && (
        <p className="mb-3 max-w-3xl border-l-2 border-accent pl-3 font-sans text-[14px] text-text">
          {diagnosis.hypothesis}
        </p>
      )}
      <div className={PROSE}>
        <h4 className="label !mb-1 !mt-0 text-dim">root cause</h4>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{diagnosis.root_cause}</ReactMarkdown>
        <h4 className="label !mb-1 text-dim">fix</h4>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{diagnosis.fix_summary}</ReactMarkdown>
      </div>
      {final && NOTES[final.status] && (
        <p className="mt-4 border-t border-line pt-3 font-mono text-[11px] text-mute">{NOTES[final.status]}</p>
      )}
    </div>
  )
}
