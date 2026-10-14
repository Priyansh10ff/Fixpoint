import clsx from 'clsx'
import { FlaskConical, Plus, Trash2 } from 'lucide-react'
import { newCaseId } from '../lib/languages'
import StatusTag from './StatusTag'

function Field({ label, value, onChange, readOnly, tone }) {
  return (
    <label className="flex min-w-0 flex-1 flex-col gap-1">
      <span className={clsx('label', tone || 'text-mute')}>{label}</span>
      <textarea
        spellCheck={false}
        readOnly={readOnly}
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        rows={Math.min(5, Math.max(1, value.replace(/\n$/, '').split('\n').length))}
        className={clsx(
          'w-full resize-y border border-line bg-bg p-2 font-mono text-[12px] leading-snug text-text outline-none focus:border-accent',
          readOnly && 'text-dim',
        )}
      />
    </label>
  )
}

function CaseCard({ index, testCase, result, onChange, onRemove, disabled }) {
  const failedOutput = result && !result.passed && result.verdict !== 'compile_error'
  return (
    <div
      className={clsx(
        'border bg-surface',
        result ? (result.passed ? 'border-ok/40' : 'border-err/40') : 'border-line',
      )}
    >
      <div className="flex items-center gap-2 border-b border-line px-3 py-1.5">
        <span className="label text-dim">case {String(index + 1).padStart(2, '0')}</span>
        {result && <StatusTag status={result.passed ? 'passed' : result.verdict} />}
        {result?.context && !result.passed && (
          <span className="truncate font-mono text-[11px] text-err">
            {result.context.error_type}
            {result.context.line ? ` · line ${result.context.line}` : ''}
          </span>
        )}
        <button
          type="button"
          onClick={onRemove}
          disabled={disabled}
          className="ml-auto text-mute hover:text-err disabled:opacity-40"
          aria-label={`Remove case ${index + 1}`}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="flex flex-col gap-2 px-3 py-2 md:flex-row">
        <Field label="input" value={testCase.input} onChange={(v) => onChange({ ...testCase, input: v })} readOnly={disabled} />
        <Field
          label="expected output"
          value={testCase.expected}
          onChange={(v) => onChange({ ...testCase, expected: v })}
          readOnly={disabled}
        />
        {failedOutput && (
          <Field label="actual output" value={result.actual || result.stderr || ''} readOnly tone="text-err" />
        )}
      </div>
    </div>
  )
}

export default function TestsPanel({ tests, onChange, testRun, running, onRunTests, repro, onKeepRepro, disabled }) {
  const results = testRun?.suite?.results || []
  const byId = Object.fromEntries(results.filter((r) => r.id).map((r) => [r.id, r]))
  const suite = testRun?.suite
  const stale = testRun?.stale

  const update = (i, next) => onChange(tests.map((t, j) => (j === i ? next : t)))
  const remove = (i) => onChange(tests.filter((_, j) => j !== i))

  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="btn-secondary focus-ring"
          onClick={onRunTests}
          disabled={disabled || running || !tests.length}
          title="Run all test cases (Ctrl+')"
        >
          <FlaskConical className="h-3.5 w-3.5" /> {running ? 'Running…' : 'Run tests'}
        </button>
        <button
          type="button"
          className="btn-secondary focus-ring"
          disabled={disabled}
          onClick={() => onChange([...tests, { id: newCaseId(), input: '', expected: '' }])}
        >
          <Plus className="h-3.5 w-3.5" /> Add case
        </button>
        {suite && suite.status === 'ok' && (
          <span className="font-mono text-[12px]">
            <span className={suite.passed === suite.total ? 'text-ok' : 'text-err'}>
              {suite.passed}/{suite.total} passing
            </span>
            {stale && <span className="text-mute"> · results are for a different version of the code</span>}
          </span>
        )}
        {suite && suite.status !== 'ok' && (
          <span className="font-mono text-[12px] text-err">
            <StatusTag status={suite.status} /> {suite.message}
          </span>
        )}
        <span className="ml-auto font-mono text-[11px] text-mute">
          Fix uses these cases: a patch must pass all of them to count.
        </span>
      </div>

      {testRun?.error && <p className="font-mono text-[12px] text-err">{testRun.error}</p>}

      {suite?.status === 'compile_error' && suite.compile_output && (
        <pre className="max-h-40 overflow-auto border border-err/40 bg-err/5 p-2 font-mono text-[12px] text-err">
          {suite.compile_output}
        </pre>
      )}

      {repro && (
        <div className="border border-accent/50 bg-accent/5 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <StatusTag status="generated" />
            <span className="font-mono text-[12px] text-dim">
              Regression case from the agent: fails on the original code, passes on the fix.
            </span>
            <button type="button" className="btn-primary focus-ring ml-auto" onClick={onKeepRepro}>
              <Plus className="h-3.5 w-3.5" /> Add to tests
            </button>
          </div>
          <div className="mt-2 flex flex-col gap-2 md:flex-row">
            <Field label="input" value={repro.input} readOnly />
            <Field label="expected output" value={repro.expected} readOnly />
          </div>
        </div>
      )}

      {tests.length === 0 && (
        <p className="font-mono text-[12px] text-mute">
          No test cases. Add an input and the expected output. Without tests, Fix can only check that the program runs
          without crashing; with tests it can catch wrong answers and verify the fix.
        </p>
      )}

      {tests.map((t, i) => (
        <CaseCard
          key={t.id}
          index={i}
          testCase={t}
          result={byId[t.id]}
          onChange={(next) => update(i, next)}
          onRemove={() => remove(i)}
          disabled={disabled}
        />
      ))}
    </div>
  )
}
