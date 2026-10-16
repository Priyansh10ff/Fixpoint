import clsx from 'clsx'
import { Check, ChevronDown, FlaskConical, GraduationCap, MessageSquareText, Play, Square, Wrench, X } from 'lucide-react'
import { LANGUAGES, LANGUAGE_IDS } from '../lib/languages'
import ModelPicker from './ModelPicker'

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
const MOD = isMac ? '⌘' : 'Ctrl'

export default function Toolbar({
  language,
  onLanguage,
  fileName,
  providers,
  modelValue,
  onModel,
  onRefreshProviders,
  busy,
  mode,
  canApply,
  onRun,
  onTest,
  canTest,
  onFix,
  onApply,
  onReject,
  onCancel,
  onLoadExample,
  appMode,
  onModeChange,
  onExplain,
  explaining,
}) {
  const locked = Boolean(busy) || mode === 'diff'

  return (
    <header className="relative flex h-11 shrink-0 items-center justify-between gap-3 border-b border-line bg-surface px-3">
      <div className="flex min-w-0 items-center gap-3">
        <span className="font-mono text-sm font-bold tracking-wide text-text" aria-label="Fixpoint">
          FIXPOINT<span className="animate-blink text-accent">_</span>
        </span>
        <span className="hidden h-4 w-px bg-line sm:block" />
        <span className="hidden truncate font-mono text-xs text-dim sm:block">▸ {fileName}</span>

        <div className="relative">
          <select
            aria-label="Language"
            className="select focus-ring appearance-none pr-7"
            value={language}
            disabled={locked}
            onChange={(e) => onLanguage(e.target.value)}
          >
            {LANGUAGE_IDS.map((id) => (
              <option key={id} value={id}>
                {LANGUAGES[id].label.toLowerCase()}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-dim" />
        </div>

        <button type="button" className="label hidden text-dim hover:text-text md:block" onClick={onLoadExample} disabled={locked}>
          load example
        </button>
      </div>

      <div className="flex items-center gap-2">
        <div role="radiogroup" aria-label="Mode" className="hidden border border-line md:flex" title={`Switch mode (${MOD}+M)`}>
          {['fix', 'learn'].map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={appMode === m}
              disabled={Boolean(busy)}
              onClick={() => onModeChange(m)}
              className={clsx(
                'label h-7 px-2.5 transition-colors disabled:opacity-40',
                appMode === m ? 'bg-surface-2 text-accent' : 'text-mute hover:text-dim',
              )}
            >
              {m}
            </button>
          ))}
        </div>

        <ModelPicker
          providers={providers}
          value={modelValue}
          onChange={onModel}
          onRefresh={onRefreshProviders}
          disabled={Boolean(busy)}
        />

        {mode === 'diff' ? (
          <>
            <span className="label hidden text-dim lg:block">diff · review the patch</span>
            <button type="button" className="btn-secondary focus-ring" onClick={onExplain} disabled={explaining} title="Explain what this patch changes">
              <MessageSquareText className="h-3.5 w-3.5" /> {explaining ? 'Explaining…' : 'Explain'}
            </button>
            <button type="button" className="btn-primary focus-ring" onClick={onApply} disabled={!canApply} title={`Apply (${MOD}+Y)`}>
              <Check className="h-3.5 w-3.5" /> Apply
            </button>
            <button type="button" className="btn-danger focus-ring" onClick={onReject} title="Reject (Esc)">
              <X className="h-3.5 w-3.5" /> Reject
            </button>
          </>
        ) : busy === 'fix' ? (
          <button type="button" className="btn-secondary focus-ring" onClick={onCancel} title="Stop the agent">
            <Square className="h-3 w-3" /> Stop
          </button>
        ) : (
          <>
            <button type="button" className="btn-secondary focus-ring" onClick={onRun} disabled={Boolean(busy)} title={`Run (${MOD}+Enter)`}>
              <Play className="h-3.5 w-3.5" /> Run
            </button>
            <button
              type="button"
              className="btn-secondary focus-ring"
              onClick={onTest}
              disabled={Boolean(busy) || !canTest}
              title={canTest ? `Run test cases (${MOD}+')` : 'Add test cases in the Tests tab'}
            >
              <FlaskConical className="h-3.5 w-3.5" /> Test
            </button>
            <button
              type="button"
              className="btn-primary focus-ring"
              onClick={onFix}
              disabled={Boolean(busy)}
              title={appMode === 'learn' ? `Get hints (${MOD}+Shift+Enter)` : `Fix (${MOD}+Shift+Enter)`}
            >
              {appMode === 'learn' ? (
                <>
                  <GraduationCap className="h-3.5 w-3.5" /> Hints
                </>
              ) : (
                <>
                  <Wrench className="h-3.5 w-3.5" /> Fix
                </>
              )}
            </button>
          </>
        )}
      </div>

      {busy && (
        <div className="absolute inset-x-0 -bottom-px h-px overflow-hidden" aria-hidden>
          <div className="h-full w-1/3 animate-progress bg-accent" />
        </div>
      )}
    </header>
  )
}
