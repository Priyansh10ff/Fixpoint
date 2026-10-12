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
})

export function startSession(original) {
  return { ...emptySession(), state: 'running', startedAt: Date.now(), original }
}

function updateAttempt(session, n, patch) {
  const attempts = session.attempts.map((a) => (a.n === n ? { ...a, ...patch } : a))
  return { ...session, attempts }
}

export function applyEvent(session, event, data) {
  switch (event) {
    case 'start':
      return { ...session, provider: data.provider, model: data.model, maxAttempts: data.max_attempts }
    case 'baseline':
      return { ...session, baseline: data.run }
    case 'attempt_start':
      return { ...session, attempts: [...session.attempts, { n: data.n, phase: 'thinking' }] }
    case 'diagnosis':
      return updateAttempt(session, data.n, { diagnosis: data, phase: 'patching' })
    case 'guard_reject':
      return updateAttempt(session, data.n, { phase: 'rejected', guard: data.reason })
    case 'patch':
      return updateAttempt(session, data.n, { patch: data, phase: 'running' })
    case 'verify':
      return updateAttempt(session, data.n, { run: data.run, phase: data.outcome })
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

/** Latest diagnosis to show in the Analysis tab. */
export function latestDiagnosis(session) {
  if (session.final?.diagnosis) return session.final.diagnosis
  for (let i = session.attempts.length - 1; i >= 0; i--) {
    if (session.attempts[i].diagnosis) return session.attempts[i].diagnosis
  }
  return null
}
