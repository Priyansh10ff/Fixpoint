import clsx from 'clsx'
import { Eye, Lock } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import StatusTag from './StatusTag'

const HINT_LEVELS = [
  { key: 'nudge', label: 'nudge' },
  { key: 'concept', label: 'concept' },
  { key: 'root_cause', label: 'root cause' },
  { key: 'fix_summary', label: 'fix' },
]

const PROSE =
  'prose prose-invert prose-sm font-sans text-[13px] leading-relaxed text-text prose-p:my-1 prose-code:rounded-none prose-code:bg-surface-2 prose-code:px-1 prose-code:font-mono prose-code:text-[12px] prose-code:font-normal prose-code:text-accent prose-code:before:content-none prose-code:after:content-none'

/**
 * Four locked hints, revealed in order. The patch stays hidden until the last one is open
 * (or the learner solves it themselves).
 */
export default function HintLadder({ hints, revealed, onReveal, solvedWith, onShowPatch, patchUnlocked }) {
  if (!hints) return null
  if (hints.status !== 'ok') {
    return <div className="m-3 border border-line bg-surface p-3 font-mono text-[12px] text-dim">{hints.message}</div>
  }
  const { ladder, based_on: basedOn } = hints

  return (
    <section className="m-3 border border-line bg-surface" aria-label="Hints">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
        <span className="label text-text">hints</span>
        <span className="font-mono text-[11px] text-mute">
          {revealed} of {HINT_LEVELS.length} used
        </span>
        <div className="ml-auto flex flex-wrap gap-1">
          {ladder.concepts.map((c) => (
            <span key={c} className="rounded-sm border border-line px-1.5 py-0.5 font-mono text-[10px] text-dim">
              {c}
            </span>
          ))}
        </div>
      </div>
      {basedOn !== 'verified' && (
        <p className="border-b border-line px-3 py-1.5 font-mono text-[11px] text-warn">
          Built from a {basedOn === 'partial' ? 'partial' : 'runs-cleanly but unverified'} fix. Add test cases for
          stronger hints.
        </p>
      )}

      <ol>
        {HINT_LEVELS.map((level, i) => {
          const open = i < revealed
          const next = i === revealed
          return (
            <li
              key={level.key}
              className={clsx('border-b border-line px-3 py-2.5 last:border-b-0', !open && 'opacity-80')}
            >
              <div className="flex items-center gap-2">
                <span className="font-mono text-[12px] text-mute">{i + 1}</span>
                <span className={clsx('label', open ? 'text-accent' : 'text-dim')}>{level.label}</span>
                {!open && (
                  <button
                    type="button"
                    onClick={onReveal}
                    disabled={!next}
                    className="label ml-auto inline-flex items-center gap-1 text-dim hover:text-text disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <Lock className="h-3 w-3" /> reveal
                  </button>
                )}
              </div>
              {open && (
                <div className={clsx('mt-1 pl-5', PROSE)}>
                  <ReactMarkdown>{ladder[level.key]}</ReactMarkdown>
                </div>
              )}
            </li>
          )
        })}
      </ol>

      <div className="border-t border-line p-3">
        <button
          type="button"
          onClick={onShowPatch}
          disabled={!patchUnlocked}
          className="btn-secondary focus-ring w-full justify-center"
          title={patchUnlocked ? 'Show the patch the agent verified' : 'Reveal all hints or solve it yourself first'}
        >
          {patchUnlocked ? <Eye className="h-3.5 w-3.5" /> : <Lock className="h-3.5 w-3.5" />}
          {solvedWith !== null && solvedWith !== undefined ? 'Compare with the agent’s patch' : 'Show patch'}
        </button>
      </div>
    </section>
  )
}

export function SolvedBanner({ solvedWith }) {
  if (solvedWith === null || solvedWith === undefined) return null
  return (
    <div className="m-3 border border-ok/50 bg-ok/5 px-3 py-2.5">
      <div className="flex items-center gap-2">
        <StatusTag status="solved" />
        <span className="font-mono text-[12px] text-dim">
          with {solvedWith} of 4 hint{solvedWith === 1 ? '' : 's'}
        </span>
      </div>
      <p className="mt-1 font-sans text-[13px] text-dim">
        Your own fix passes. Compare it with the agent&apos;s patch.
      </p>
    </div>
  )
}
