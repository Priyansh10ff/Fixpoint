import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { latestDiagnosis } from '../lib/fixSession'
import StatusTag from './StatusTag'

const PROSE =
  'prose prose-invert prose-sm max-w-3xl font-sans prose-headings:font-mono prose-strong:text-text prose-code:rounded-none prose-code:bg-surface-2 prose-code:px-1 prose-code:py-0.5 prose-code:font-mono prose-code:text-[12px] prose-code:font-normal prose-code:text-accent prose-code:before:content-none prose-code:after:content-none prose-pre:rounded-none prose-pre:border prose-pre:border-line prose-pre:bg-bg'

const NOTES = {
  verified: 'The patch was re-run in the sandbox and checked: see the agent panel for the evidence (passing test cases and/or a regression case).',
  fixed: 'The patched program runs without errors, but its output was not checked. Add test cases with expected outputs to verify it.',
  partial: 'The first error is fixed but the program still fails. The diff shows the partial fix.',
  unresolved: 'No attempt produced a program that runs cleanly. The analysis below is from the last attempt.',
  unverified: 'The program already ran cleanly, so this change could not be verified. Treat it as a suggestion.',
}

function ExplanationBlock({ explanation }) {
  if (!explanation || explanation.state === 'idle') return null
  if (explanation.state === 'loading') {
    return (
      <div className="mb-4 flex items-center gap-3 font-mono text-[13px]">
        <StatusTag status="running" /> <span className="text-dim">explaining the patch…</span>
      </div>
    )
  }
  if (explanation.state === 'error') {
    return <p className="mb-4 font-mono text-[13px] text-err">{explanation.error}</p>
  }
  const { summary, why, concepts } = explanation.data.explanation
  return (
    <div className="mb-5 border-b border-line pb-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="label text-accent">patch explained</span>
        <span className="font-mono text-[11px] text-mute">{explanation.label}</span>
        {concepts.map((c) => (
          <span key={c} className="rounded-sm border border-line px-1.5 py-0.5 font-mono text-[10px] text-dim">
            {c}
          </span>
        ))}
      </div>
      <p className="mb-2 max-w-3xl font-sans text-[14px] text-text">{summary}</p>
      <div className={PROSE}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{why}</ReactMarkdown>
      </div>
    </div>
  )
}

export default function DebugPanel({ session, locked, explanation }) {
  const { state, final, error } = session
  const diagnosis = latestDiagnosis(session)

  if (locked) {
    return (
      <div className="p-4 font-mono text-[13px] text-mute">
        Learn mode: the analysis contains the answer, so it unlocks after the last hint or once you solve it. Use the
        hints in the agent panel.
      </div>
    )
  }
  if (explanation && explanation.state !== 'idle' && state === 'idle') {
    return (
      <div className="p-4">
        <ExplanationBlock explanation={explanation} />
      </div>
    )
  }

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
      <ExplanationBlock explanation={explanation} />
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
