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
import Toolbar from './components/Toolbar'
import { useBackend } from './hooks/useBackend'
import { api } from './lib/api'
import { applyEvent, cancelSession, emptySession, finishWithError, startSession } from './lib/fixSession'
import { fileNameFor, LANGUAGE_IDS, LANGUAGES } from './lib/languages'
import { modelKey } from './lib/models'
import { streamEvents } from './lib/sse'
import { load, save } from './lib/storage'

const initialBuffers = () => {
  const saved = load('buffers', {})
  return Object.fromEntries(LANGUAGE_IDS.map((id) => [id, saved[id] ?? LANGUAGES[id].example]))
}
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
  const [selection, setSelection] = useState(() => load('model', null)) // { provider, model }

  const [tab, setTab] = useState('output') // 'output' | 'input' | 'analysis'
  const [panelHeight, setPanelHeight] = useState(() => load('panelHeight', 260))
  const [cursor, setCursor] = useState({ line: 1, col: 1 })

  const [busy, setBusy] = useState(null) // null | 'run' | 'fix'
  const [run, setRun] = useState({ result: null, error: null, code: null })
  const [session, setSession] = useState(emptySession)
  const [viewing, setViewing] = useState(null) // null (editor) | attempt number | 'final'
  const abortRef = useRef(null)

  const code = buffers[language]
  const stdin = stdins[language]

  useEffect(() => save('buffers', buffers), [buffers])
  useEffect(() => save('stdin', stdins), [stdins])
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

  const switchLanguage = useCallback((id) => {
    abortRef.current?.abort()
    setBusy(null)
    setLanguage(id)
    setViewing(null)
    setRun({ result: null, error: null, code: null })
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
        { language, code: original, stdin, provider: activeModel.provider, model: activeModel.model },
        {
          signal: controller.signal,
          onEvent: (event, data) => {
            setSession((s) => applyEvent(s, event, data))
            if (event === 'baseline') setRun({ result: data.run, error: null, code: original })
            if (event === 'done') {
              if (data.run) setRun({ result: data.run, error: null, code: data.final_code || original })
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
  }, [busy, code, language, stdin, activeModel])

  const handleCancel = useCallback(() => abortRef.current?.abort(), [])

  const handleApply = useCallback(() => {
    if (!diffTarget) return
    setCode(diffTarget.code)
    setViewing(null)
    handleRun(diffTarget.code) // re-run so the result of the patch is visible immediately
  }, [diffTarget, setCode, handleRun])

  const handleApplyFinal = useCallback(() => {
    const fixed = session.final?.final_code
    if (!fixed) return
    setCode(fixed)
    setViewing(null)
    handleRun(fixed)
  }, [session.final, setCode, handleRun])

  const handleReject = useCallback(() => setViewing(null), [])

  const loadExample = useCallback(() => {
    setCode(LANGUAGES[language].example)
    setStdin(LANGUAGES[language].stdin)
    setViewing(null)
  }, [language, setCode, setStdin])

  // Keyboard shortcuts outside Monaco (Monaco registers its own for run/fix).
  const commands = useRef({})
  useEffect(() => {
    commands.current = { run: () => handleRun(), fix: handleFix }
  }, [handleRun, handleFix])

  useEffect(() => {
    const onKey = (e) => {
      if (e.defaultPrevented) return // already handled inside Monaco
      const mod = e.ctrlKey || e.metaKey
      if (mod && e.key === 'Enter') {
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
