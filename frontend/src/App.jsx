import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
import { fileNameFor, LANGUAGE_IDS, LANGUAGES } from './lib/languages'
import { modelKey } from './lib/models'
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

  const [mode, setMode] = useState('edit') // 'edit' | 'diff'
  const [tab, setTab] = useState('output') // 'output' | 'input' | 'analysis'
  const [panelHeight, setPanelHeight] = useState(() => load('panelHeight', 260))
  const [cursor, setCursor] = useState({ line: 1, col: 1 })

  const [busy, setBusy] = useState(null) // null | 'run' | 'fix'
  const [run, setRun] = useState({ result: null, error: null })
  const [debug, setDebug] = useState({ state: 'idle', data: null, error: null })
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

  const setCode = useCallback((value) => setBuffers((b) => ({ ...b, [language]: value })), [language])
  const setStdin = useCallback((value) => setStdins((s) => ({ ...s, [language]: value })), [language])

  const switchLanguage = useCallback((id) => {
    abortRef.current?.abort()
    setLanguage(id)
    setMode('edit')
    setRun({ result: null, error: null })
    setDebug({ state: 'idle', data: null, error: null })
  }, [])

  const handleRun = useCallback(
    async (source = code) => {
      if (busy) return
      if (!source.trim()) {
        setRun({ result: null, error: 'Editor is empty.' })
        setTab('output')
        return
      }
      const controller = new AbortController()
      abortRef.current = controller
      setBusy('run')
      setTab('output')
      try {
        const result = await api.run({ language, code: source, stdin }, controller.signal)
        setRun({ result, error: null })
      } catch (err) {
        if (err.name !== 'AbortError') setRun({ result: null, error: err.message })
      } finally {
        setBusy(null)
      }
    },
    [busy, code, language, stdin],
  )

  const handleFix = useCallback(async () => {
    if (busy) return
    if (!code.trim()) {
      setDebug({ state: 'error', data: null, error: 'Editor is empty.' })
      setTab('analysis')
      return
    }
    if (!activeModel) {
      setDebug({
        state: 'error',
        data: null,
        error: 'No model available. Start Ollama or add an API key in backend/.env, then refresh providers.',
      })
      setTab('analysis')
      return
    }
    const controller = new AbortController()
    abortRef.current = controller
    setBusy('fix')
    setTab('analysis')
    setDebug({ state: 'loading', data: null, error: null })
    try {
      const data = await api.debug(
        { language, code, stdin, provider: activeModel.provider, model: activeModel.model },
        controller.signal,
      )
      setRun({ result: data.run, error: null })
      setDebug({ state: 'done', data: { ...data, original: code }, error: null })
      if (data.changed) setMode('diff')
    } catch (err) {
      if (err.name !== 'AbortError') setDebug({ state: 'error', data: null, error: err.message })
    } finally {
      setBusy(null)
    }
  }, [busy, code, language, stdin, activeModel])

  const handleApply = useCallback(() => {
    const fixed = debug.data?.diagnosis.fixed_code
    if (!fixed) return
    setCode(fixed)
    setMode('edit')
    handleRun(fixed) // re-run so the result of the fix is visible immediately
  }, [debug.data, setCode, handleRun])

  const handleReject = useCallback(() => setMode('edit'), [])

  const loadExample = useCallback(() => {
    setCode(LANGUAGES[language].example)
    setStdin(LANGUAGES[language].stdin)
    setMode('edit')
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
      } else if (mode === 'diff' && e.key === 'Escape') {
        handleReject()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mode, handleApply, handleReject])

  const runBadge = busy === 'run' ? <StatusTag status="running" /> : run.result ? <StatusTag status={run.result.status} /> : null
  const fixBadge =
    debug.state === 'loading' ? (
      <StatusTag status="fixing" />
    ) : debug.state === 'done' ? (
      <StatusTag status={debug.data.changed ? 'fix_ready' : 'no_change'} />
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
        canApply={Boolean(debug.data?.changed)}
        onRun={() => handleRun()}
        onFix={handleFix}
        onApply={handleApply}
        onReject={handleReject}
        onLoadExample={loadExample}
      />

      {banner && (
        <div role="alert" className="shrink-0 border-b border-err/40 bg-err/10 px-3 py-1.5 font-mono text-[12px] text-err">
          {banner}
        </div>
      )}

      <main className="min-h-0 flex-1">
        {mode === 'diff' && debug.data ? (
          <DiffView
            original={debug.data.original}
            modified={debug.data.diagnosis.fixed_code}
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
            readOnly={Boolean(busy)}
          />
        )}
      </main>

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
            language={language}
            onSwitchLanguage={switchLanguage}
          />
        )}
        {tab === 'input' && <StdinPanel value={stdin} onChange={setStdin} />}
        {tab === 'analysis' && <DebugPanel debug={debug} />}
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
