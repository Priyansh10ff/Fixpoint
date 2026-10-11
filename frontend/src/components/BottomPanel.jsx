import clsx from 'clsx'
import { useRef } from 'react'

const MIN = 120
const MAX_RATIO = 0.75

/** Tabbed bottom panel with a drag handle on its top edge. */
export default function BottomPanel({ tabs, active, onTab, height, onResize, children }) {
  const drag = useRef(null)

  const startDrag = (e) => {
    e.preventDefault()
    drag.current = { y: e.clientY, h: height }
    const move = (ev) => {
      const next = drag.current.h + (drag.current.y - ev.clientY)
      onResize(Math.max(MIN, Math.min(next, window.innerHeight * MAX_RATIO)))
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      document.body.style.cursor = ''
    }
    document.body.style.cursor = 'row-resize'
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  return (
    <section className="relative flex shrink-0 flex-col border-t border-line bg-bg" style={{ height }}>
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize panel"
        onPointerDown={startDrag}
        className="absolute -top-1 left-0 right-0 z-10 h-2 cursor-row-resize hover:bg-accent/20"
      />
      <div role="tablist" className="flex shrink-0 border-b border-line bg-surface">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            type="button"
            aria-selected={active === t.id}
            onClick={() => onTab(t.id)}
            className={clsx(
              'label focus-ring flex items-center gap-2 border-r border-line px-4 py-2 transition-colors',
              active === t.id ? 'bg-bg text-text shadow-[inset_0_2px_0_#d4ff3a]' : 'text-mute hover:text-dim',
            )}
          >
            {t.label}
            {t.badge}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="min-h-0 flex-1 overflow-auto">
        {children}
      </div>
    </section>
  )
}
