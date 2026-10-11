import { RefreshCw } from 'lucide-react'
import { modelKey } from '../lib/models'

export default function ModelPicker({ providers, value, onChange, onRefresh, disabled }) {
  const { state, list } = providers
  const available = list.filter((p) => p.available && p.models.length)

  return (
    <div className="flex items-center gap-1">
      <select
        aria-label="Model"
        className="select focus-ring max-w-[260px]"
        value={value || ''}
        disabled={disabled || state !== 'ok' || !available.length}
        onChange={(e) => {
          const [provider, ...rest] = e.target.value.split('::')
          onChange({ provider, model: rest.join('::') })
        }}
        title={list
          .filter((p) => !p.available)
          .map((p) => `${p.label}: ${p.reason}`)
          .join('\n')}
      >
        {state === 'loading' && <option value="">loading models…</option>}
        {state === 'error' && <option value="">models unavailable</option>}
        {state === 'ok' && !available.length && <option value="">no provider reachable</option>}
        {list.map((p) =>
          p.available && p.models.length ? (
            <optgroup key={p.id} label={`${p.label}${p.local ? ' · local' : ''}`}>
              {p.models.map((m) => (
                <option key={m} value={modelKey(p.id, m)}>
                  {m}
                </option>
              ))}
            </optgroup>
          ) : null,
        )}
      </select>
      <button
        type="button"
        onClick={onRefresh}
        className="btn-secondary focus-ring h-7 px-2"
        title="Refresh providers"
        aria-label="Refresh providers"
      >
        <RefreshCw className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}
