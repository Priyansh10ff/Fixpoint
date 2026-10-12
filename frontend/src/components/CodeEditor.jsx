import Editor from '@monaco-editor/react'
import { useEffect, useRef } from 'react'
import { EDITOR_OPTIONS } from '../lib/editorOptions'

/**
 * `commands` is a ref holding the latest { run, fix } handlers so Monaco keybindings
 * registered once on mount never call stale closures.
 * `marker` ({ line, message }) highlights the line where the last run failed.
 */
export default function CodeEditor({ value, language, onChange, onCursor, commands, marker, readOnly = false }) {
  const editorRef = useRef(null)
  const decorations = useRef(null)

  const handleMount = (editor, monaco) => {
    editorRef.current = editor
    decorations.current = editor.createDecorationsCollection([])
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => commands.current?.run())
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.Enter, () => commands.current?.fix())
    // Listener is disposed together with the editor on unmount.
    editor.onDidChangeCursorPosition((e) => onCursor?.({ line: e.position.lineNumber, col: e.position.column }))
    editor.focus()
    paint(marker)
  }

  const paint = (m) => {
    const editor = editorRef.current
    if (!editor || !decorations.current) return
    const lines = editor.getModel()?.getLineCount() ?? 0
    if (!m?.line || m.line > lines) {
      decorations.current.clear()
      return
    }
    decorations.current.set([
      {
        range: { startLineNumber: m.line, startColumn: 1, endLineNumber: m.line, endColumn: 1 },
        options: {
          isWholeLine: true,
          className: 'fp-error-line',
          linesDecorationsClassName: 'fp-error-gutter',
          hoverMessage: m.message ? { value: m.message } : undefined,
          overviewRuler: { color: '#ff4d4d', position: 4 },
        },
      },
    ])
  }

  useEffect(() => {
    paint(marker)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- paint only reads refs
  }, [marker?.line, marker?.message])

  return (
    <Editor
      height="100%"
      theme="fixpoint"
      language={language}
      value={value}
      onChange={(v) => onChange?.(v ?? '')}
      onMount={handleMount}
      loading={<div className="label p-4 text-mute">loading editor…</div>}
      options={{ ...EDITOR_OPTIONS, readOnly }}
    />
  )
}
