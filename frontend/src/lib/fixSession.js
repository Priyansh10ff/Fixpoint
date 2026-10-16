/** Folds the /api/fix event stream into one session object the UI renders. */

export const emptySession = () => ({
  state: 'idle', // idle | running | done | error
  startedAt: null,
  endedAt: null,
  original: null,
  provider: null,
  model: null,
  maxAttempts: null,
  baseline: null,
  attempts: [],
  final: null,
  error: null,
  learn: null,
  hints: null,
})

export function startSession(original, learn = false) {
  return {
    ...emptySession(),
    state: 'running',
    startedAt: Date.now(),
    original,
    learn: learn ? { revealed: 0, solvedWith: null } : null,
  }
}

/** In Learn mode the patch (and anything that gives it away) stays hidden until earned. */
export function patchUnlocked(session) {
  const learn = session.learn
  if (!learn) return true
  return learn.revealed >= 4 || learn.solvedWith !== null
}

export function revealHint(session) {
  if (!session.learn) return session
  return { ...session, learn: { ...session.learn, revealed: Math.min(4, session.learn.revealed + 1) } }
}

export function markSolved(session) {
  if (!session.learn || session.learn.solvedWith !== null) return session
  return { ...session, learn: { ...session.learn, solvedWith: session.learn.revealed } }
}

function updateAttempt(session, n, patch) {
  const attempts = session.attempts.map((a) => (a.n === n ? { ...a, ...patch } : a))
  return { ...session, attempts }
}

export function applyEvent(session, event, data) {
  switch (event) {
    case 'start':
      return {
        ...session,
        provider: data.provider,
        model: data.model,
        maxAttempts: data.max_attempts,
        mode: data.mode,
        testCount: data.test_count,
      }
    case 'baseline':
      return { ...session, baseline: data }
    case 'attempt_start':
      return { ...session, attempts: [...session.attempts, { n: data.n, phase: 'thinking' }] }
    case 'diagnosis':
      return updateAttempt(session, data.n, { diagnosis: data, phase: 'patching' })
    case 'guard_reject':
      return updateAttempt(session, data.n, { phase: 'rejected', guard: data.reason })
    case 'patch':
      return updateAttempt(session, data.n, { patch: data, phase: 'running' })
    case 'verify':
      return updateAttempt(session, data.n, { result: { run: data.run, tests: data.tests }, phase: data.outcome })
    case 'repro':
      return updateAttempt(session, data.n, { repro: data })
    case 'hints':
      return { ...session, hints: data }
    case 'done':
      return { ...session, state: 'done', endedAt: Date.now(), final: data }
    default:
      return session
  }
}

export function finishWithError(session, message) {
  return { ...session, state: 'error', endedAt: Date.now(), error: message }
}

export function cancelSession(session) {
  if (session.state !== 'running') return session
  return {
    ...session,
    state: 'done',
    endedAt: Date.now(),
    final: { status: 'cancelled', message: 'Stopped by you.', final_code: null, attempts: session.attempts.length },
  }
}

/** One-line summary of a run or test-suite result: { text, ok }. */
export function summarize(result) {
  if (!result) return null
  const { run, tests } = result
  if (tests) {
    if (tests.status === 'compile_error') return { text: 'compile error', ok: false }
    if (tests.status === 'sandbox_error') return { text: tests.message || 'sandbox error', ok: false }
    const firstFail = tests.results.find((r) => !r.passed)
    const detail = firstFail
      ? ` · case ${firstFail.index + 1}: ${firstFail.context?.error_type || firstFail.verdict.replace('_', ' ')}`
      : ''
    return { text: `${tests.passed}/${tests.total} tests${detail}`, ok: tests.passed === tests.total }
  }
  if (run) {
    const ctx = run.context
    if (run.status === 'ok') return { text: 'ran without errors', ok: true }
    return { text: ctx ? `${ctx.error_type}${ctx.line ? ` · line ${ctx.line}` : ''}` : run.message || run.status, ok: false }
  }
  return null
}

/** Latest diagnosis to show in the Analysis tab. */
export function latestDiagnosis(session) {
  if (session.final?.diagnosis) return session.final.diagnosis
  for (let i = session.attempts.length - 1; i >= 0; i--) {
    if (session.attempts[i].diagnosis) return session.attempts[i].diagnosis
  }
  return null
}
