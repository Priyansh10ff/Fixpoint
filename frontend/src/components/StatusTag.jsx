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
}

export default function StatusTag({ status, className }) {
  const [label, color] = TAGS[status] || [String(status).toUpperCase(), 'text-dim']
  return <span className={clsx('label whitespace-nowrap', color, className)}>[{label}]</span>
}
