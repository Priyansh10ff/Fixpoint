import clsx from 'clsx'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import AgentPanel from './components/AgentPanel'
import BottomPanel from './components/BottomPanel'
import CodeEditor from './components/CodeEditor'
import DebugPanel from './components/DebugPanel'
import DiffView from './components/DiffView'
import StatusBar from './components/StatusBar'
import StatusTag from './components/StatusTag'
import StdinPanel from './components/StdinPanel'
import Terminal from './components/Terminal'
import TestsPanel from './components/TestsPanel'
import Toolbar from './components/Toolbar'
import { useBackend } from './hooks/useBackend'
import { api } from './lib/api'
import { applyEvent, cancelSession, emptySession, finishWithError, startSession } from './lib/fixSession'
import { exampleTests, fileNameFor, LANGUAGE_IDS, LANGUAGES, newCaseId } from './lib/languages'
import { modelKey } from './lib/models'
import { streamEvents } from './lib/sse'
import { load, save } from './lib/storage'

const initialBuffers = () => {
  const saved = load('buffers', {})
  return Object.fromEntries(LANGUAGE_IDS.map((id) => [id, saved[id] ?? LANGUAGES[id].example]))
}
const initialTests = () => {
  const saved = load('tests', {})
  return Object.fromEntries(LANGUAGE_IDS.map((id) => [id, Array.isArray(saved[id]) ? saved[id] : exampleTests(id)]))
}
const filledTests = (tests) =>
  tests.filter((t) => t.input.trim() || t.expected.trim()).map(({ id, input, expected }) => ({ id, input, expected }))

const initialStdin = () => {
  const saved = load('stdin', {})
  return Object.fromEntries(LANGUAGE_IDS.map((id) => [id, saved[id] ?? LANGUAGES[id].stdin]))
}

export default function App() {
  const { health, providers, refreshProviders } = useBackend()

  const [language, setLanguage] = useState(() => {
    const saved = load('language', 'python')
    return LANGUAGES[saved] ? saved : 'python'
  })
  const [buffers, setBuffers] = useState(initialBuffers)
  const [stdins, setStdins] = useState(initialStdin)
  const [testsByLang, setTestsByLang] = useState(initialTests)
  const [testRun, setTestRun] = useState({ suite: null, code: null, error: null })
  const [selection, setSelection] = useState(() => load('model', null)) // { provider, model }

  const [tab, setTab] = useState('output') // 'output' | 'input' | 'tests' | 'analysis'
  const [panelHeight, setPanelHeight] = useState(() => load('panelHeight', 260))
  const [cursor, setCursor] = useState({ line: 1, col: 1 })

  const [busy, setBusy] = useState(null) // null | 'run' | 'test' | 'fix'
  const [run, setRun] = useState({ result: null, error: null, code: null })
  const [session, setSession] = useState(emptySession)
  const [viewing, setViewing] = useState(null) // null (editor) | attempt number | 'final'
  const abortRef = useRef(null)

  const code = buffers[language]
  const stdin = stdins[language]
  const tests = testsByLang[language]

  useEffect(() => save('buffers', buffers), [buffers])
  useEffect(() => save('stdin', stdins), [stdins])
  useEffect(() => save('tests', testsByLang), [testsByLang])
  useEffect(() => save('language', language), [language])
  useEffect(() => save('panelHeight', panelHeight), [panelHeight])
  useEffect(() => {
    if (selection) save('model', selection)
  }, [selection])

  // Resolve the active model: saved choice if still available, else backend default.
  const activeModel = useMemo(() => {
    const list = providers.list.filter((p) => p.available && p.models.length)
    if (!list.length) return null
    if (selection) {
      const p = list.find((x) => x.id === selection.provider)
      if (p && p.models.includes(selection.model)) return selection
    }
    const p = list.find((x) => x.id === providers.defaultProvider) || list[0]
    const model = p.default_model && p.models.includes(p.default_model) ? p.default_model : p.models[0]
    return { provider: p.id, model }
  }, [providers, selection])

  // Which patch the diff view shows.
  const diffTarget = useMemo(() => {
    if (viewing === null || !session.original) return null
    if (viewing === 'final') {
      return session.final?.final_code ? { code: session.final.final_code, label: 'final patch' } : null
    }
    const attempt = session.attempts.find((a) => a.n === viewing)
    return attempt?.patch ? { code: attempt.patch.code, label: `attempt ${attempt.n} patch` } : null
  }, [viewing, session])
  const mode = diffTarget ? 'diff' : 'edit'

  const setCode = useCallback((value) => setBuffers((b) => ({ ...b, [language]: value })), [language])
  const setStdin = useCallback((value) => setStdins((s) => ({ ...s, [language]: value })), [language])
  const setTests = useCallback((value) => setTestsByLang((t) => ({ ...t, [language]: value })), [language])

  const switchLanguage = useCallback((id) => {
    abortRef.current?.abort()
    setBusy(null)
    setLanguage(id)
    setViewing(null)
    setRun({ result: null, error: null, code: null })
    setTestRun({ suite: null, code: null, error: null })
    setSession(emptySession())
  }, [])

  const handleRun = useCallback(
    async (source = code) => {
      if (busy) return
      if (!source.trim()) {
        setRun({ result: null, error: 'Editor is empty.', code: null })
        setTab('output')
        return
      }
      const controller = new AbortController()
      abortRef.current = controller
      setBusy('run')
      setTab('output')
      try {
        const result = await api.run({ language, code: source, stdin }, controller.signal)
        setRun({ result, error: null, code: source })
      } catch (err) {
        if (err.name !== 'AbortError') setRun({ result: null, error: err.message, code: null })
      } finally {
        setBusy(null)
      }
    },
    [busy, code, language, stdin],
  )

  const handleRunTests = useCallback(
    async (source = code) => {
      if (busy) return
      const cases = filledTests(tests)
      setTab('tests')
      if (!cases.length) {
        setTestRun({ suite: null, code: null, error: 'Add at least one test case.' })
        return
      }
      const controller = new AbortController()
      abortRef.current = controller
      setBusy('test')
      try {
        const suite = await api.test({ language, code: source, tests: cases }, controller.signal)
        setTestRun({ suite, code: source, error: null })
      } catch (err) {
        if (err.name !== 'AbortError') setTestRun({ suite: null, code: null, error: err.message })
      } finally {
        setBusy(null)
      }
    },
    [busy, code, language, tests],
  )

  const handleFix = useCallback(async () => {
    if (busy) return
    if (!code.trim()) {
      setSession(finishWithError(startSession(code), 'Editor is empty.'))
      setTab('analysis')
      return
    }
    if (!activeModel) {
      setSession(
        finishWithError(
          startSession(code),
          'No model available. Start Ollama or add an API key in backend/.env, then refresh providers.',
        ),
      )
      setTab('analysis')
      return
    }
    const controller = new AbortController()
    abortRef.current = controller
    const original = code
    setBusy('fix')
    setViewing(null)
    setTab('analysis')
    setSession(startSession(original))
    try {
      await streamEvents(
        '/api/fix',
        {
          language,
          code: original,
          stdin,
          tests: filledTests(tests),
          provider: activeModel.provider,
          model: activeModel.model,
        },
        {
          signal: controller.signal,
          onEvent: (event, data) => {
            setSession((s) => applyEvent(s, event, data))
            if (event === 'baseline') {
              if (data.run) setRun({ result: data.run, error: null, code: original })
              if (data.tests) setTestRun({ suite: data.tests, code: original, error: null })
            }
            if (event === 'done') {
              if (data.run) setRun({ result: data.run, error: null, code: data.final_code || original })
              if (data.tests) setTestRun({ suite: data.tests, code: data.final_code || original, error: null })
              if (data.final_code) setViewing('final')
            }
          },
        },
      )
      // Stream ended without a done event (server restarted, proxy cut the connection).
      setSession((s) => (s.state === 'running' ? finishWithError(s, 'Connection closed before the agent finished.') : s))
    } catch (err) {
      if (err.name === 'AbortError') setSession((s) => cancelSession(s))
      else setSession((s) => finishWithError(s, err.message))
    } finally {
      setBusy(null)
    }
  }, [busy, code, language, stdin, tests, activeModel])

  const handleCancel = useCallback(() => abortRef.current?.abort(), [])

  // After applying a patch: re-run the tests if there are any, otherwise a plain run.
  const recheck = useCallback(
    (source) => (filledTests(tests).length ? handleRunTests(source) : handleRun(source)),
    [tests, handleRunTests, handleRun],
  )

  const keepRepro = useCallback(() => {
    const repro = session.final?.repro_case
    if (!repro) return
    setTests([...tests, { id: newCaseId(), input: repro.input, expected: repro.expected }])
    setSession((s) => ({ ...s, final: { ...s.final, repro_case: null } }))
  }, [session.final, tests, setTests])

  const handleApply = useCallback(() => {
    if (!diffTarget) return
    setCode(diffTarget.code)
    setViewing(null)
    recheck(diffTarget.code) // re-run so the result of the patch is visible immediately
  }, [diffTarget, setCode, recheck])

  const handleApplyFinal = useCallback(() => {
    const fixed = session.final?.final_code
    if (!fixed) return
    setCode(fixed)
    setViewing(null)
    recheck(fixed)
  }, [session.final, setCode, recheck])

  const handleReject = useCallback(() => setViewing(null), [])

  const loadExample = useCallback(() => {
    setCode(LANGUAGES[language].example)
    setStdin(LANGUAGES[language].stdin)
    setTests(exampleTests(language))
    setViewing(null)
  }, [language, setCode, setStdin, setTests])

  // Keyboard shortcuts outside Monaco (Monaco registers its own for run/fix).
  const commands = useRef({})
  useEffect(() => {
    commands.current = { run: () => handleRun(), fix: handleFix, test: () => handleRunTests() }
  }, [handleRun, handleFix, handleRunTests])

  useEffect(() => {
    const onKey = (e) => {
      if (e.defaultPrevented) return // already handled inside Monaco
      const mod = e.ctrlKey || e.metaKey
      if (mod && e.key === "'") {
        e.preventDefault()
        if (mode !== 'diff') commands.current.test()
      } else if (mod && e.key === 'Enter') {
        e.preventDefault()
        if (mode === 'diff') return
        if (e.shiftKey) commands.current.fix()
        else commands.current.run()
      } else if (mode === 'diff' && mod && e.key.toLowerCase() === 'y') {
        e.preventDefault()
        handleApply()
      } else if (e.key === 'Escape') {
        if (mode === 'diff') handleReject()
        else if (busy === 'fix') handleCancel()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mode, busy, handleApply, handleReject, handleCancel])

  // Highlight the failing line only while the editor still holds the code that produced it.
  const marker = useMemo(() => {
    const ctx = run.result?.context
    if (!ctx?.line || run.code !== code) return null
    return { line: ctx.line, message: `**${ctx.error_type}**${ctx.message ? `: ${ctx.message}` : ''}` }
  }, [run, code])

  const runBadge = busy === 'run' ? <StatusTag status="running" /> : run.result ? <StatusTag status={run.result.status} /> : null
  const suite = testRun.suite
  const testBadge =
    busy === 'test' ? (
      <StatusTag status="running" />
    ) : suite?.status === 'ok' ? (
      <span className={clsx('label', suite.passed === suite.total ? 'text-ok' : 'text-err')}>
        [{suite.passed}/{suite.total}]
      </span>
    ) : suite ? (
      <StatusTag status={suite.status} />
    ) : null

  const fixBadge =
    session.state === 'running' ? (
      <StatusTag status="fixing" />
    ) : session.final ? (
      <StatusTag status={session.final.status} />
    ) : session.state === 'error' ? (
      <StatusTag status="error" />
    ) : null

  const banner =
    health.state === 'offline'
      ? `Backend not reachable. Start it with: uvicorn app.main:app --reload (in backend/).`
      : health.state === 'ok' && !health.docker
        ? 'Docker is not running. Start Docker Desktop to run code.'
        : null

  return (
    <div className="flex h-full flex-col bg-bg text-text">
      <Toolbar
        language={language}
        onLanguage={switchLanguage}
        fileName={fileNameFor(language, code)}
        providers={providers}
        modelValue={activeModel ? modelKey(activeModel.provider, activeModel.model) : ''}
        onModel={setSelection}
        onRefreshProviders={refreshProviders}
        busy={busy}
        mode={mode}
        canApply={Boolean(diffTarget)}
        onRun={() => handleRun()}
        onTest={() => handleRunTests()}
        canTest={filledTests(tests).length > 0}
        onFix={handleFix}
        onApply={handleApply}
        onReject={handleReject}
        onCancel={handleCancel}
        onLoadExample={loadExample}
      />

      {banner && (
        <div role="alert" className="shrink-0 border-b border-err/40 bg-err/10 px-3 py-1.5 font-mono text-[12px] text-err">
          {banner}
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <main className="min-w-0 flex-1">
          {diffTarget ? (
            <DiffView
              original={session.original}
              modified={diffTarget.code}
              label={diffTarget.label}
              language={LANGUAGES[language].monaco}
            />
          ) : (
            <CodeEditor
              key={language}
              value={code}
              language={LANGUAGES[language].monaco}
              onChange={setCode}
              onCursor={setCursor}
              commands={commands}
              marker={marker}
              readOnly={Boolean(busy)}
            />
          )}
        </main>
        <div className="hidden lg:block">
          <AgentPanel
            session={session}
            viewing={viewing}
            onView={setViewing}
            onApply={handleApplyFinal}
            onCancel={handleCancel}
          />
        </div>
      </div>

      <BottomPanel
        tabs={[
          { id: 'output', label: 'Output', badge: runBadge },
          { id: 'input', label: 'Input', badge: stdin.trim() ? <span className="text-mute">·</span> : null },
          { id: 'tests', label: `Tests ${tests.length}`, badge: testBadge },
          { id: 'analysis', label: 'Analysis', badge: fixBadge },
        ]}
        active={tab}
        onTab={setTab}
        height={panelHeight}
        onResize={setPanelHeight}
      >
        {tab === 'output' && (
          <Terminal
            result={run.result}
            error={run.error}
            running={busy === 'run'}
            stale={Boolean(run.result && run.code && run.code !== code)}
            language={language}
            onSwitchLanguage={switchLanguage}
          />
        )}
        {tab === 'input' && <StdinPanel value={stdin} onChange={setStdin} />}
        {tab === 'tests' && (
          <TestsPanel
            tests={tests}
            onChange={setTests}
            testRun={{ ...testRun, stale: Boolean(testRun.suite && testRun.code !== code) }}
            running={busy === 'test'}
            onRunTests={() => handleRunTests()}
            repro={session.final?.repro_case}
            onKeepRepro={keepRepro}
            disabled={busy === 'fix'}
          />
        )}
        {tab === 'analysis' && <DebugPanel session={session} />}
      </BottomPanel>

      <StatusBar
        health={health}
        language={language}
        provider={activeModel?.provider}
        model={activeModel?.model}
        cursor={cursor}
        lastDuration={run.result?.duration_ms ?? null}
      />
    </div>
  )
}
