import clsx from 'clsx'

const TAGS = {
  ok: ['OK', 'text-ok'],
  runtime_error: ['RUNTIME ERROR', 'text-err'],
  compile_error: ['COMPILE ERROR', 'text-err'],
  timeout: ['TIMEOUT', 'text-warn'],
  oom: ['MEMORY LIMIT', 'text-warn'],
  sandbox_error: ['SANDBOX ERROR', 'text-err'],
  running: ['RUNNING', 'text-run'],
  fixing: ['ANALYSING', 'text-run'],
  fix_ready: ['FIX READY', 'text-accent'],
  no_change: ['NO CHANGE', 'text-dim'],
  error: ['ERROR', 'text-err'],
  // agent attempt phases
  thinking: ['THINKING', 'text-run'],
  patching: ['PATCHING', 'text-run'],
  passed: ['PASSED', 'text-ok'],
  failed: ['FAILED', 'text-err'],
  progress: ['PROGRESS', 'text-warn'],
  rejected: ['REJECTED', 'text-warn'],
  // agent verdicts
  fixed: ['FIXED · UNVERIFIED', 'text-warn'],
  verified: ['VERIFIED', 'text-ok'],
  wrong_answer: ['WRONG ANSWER', 'text-err'],
  generated: ['GENERATED', 'text-accent'],
  partial: ['PARTIAL FIX', 'text-warn'],
  unresolved: ['UNRESOLVED', 'text-err'],
  no_bug: ['NO BUG FOUND', 'text-dim'],
  unverified: ['SUGGESTION', 'text-warn'],
  cancelled: ['CANCELLED', 'text-dim'],
}

export default function StatusTag({ status, className }) {
  const [label, color] = TAGS[status] || [String(status).toUpperCase(), 'text-dim']
  return <span className={clsx('label whitespace-nowrap', color, className)}>[{label}]</span>
}
