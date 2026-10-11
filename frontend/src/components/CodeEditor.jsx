import Editor from '@monaco-editor/react'
import { EDITOR_OPTIONS } from '../lib/editorOptions'


/**
 * `commands` is a ref holding the latest { run, fix } handlers so Monaco keybindings
 * registered once on mount never call stale closures.
 */
export default function CodeEditor({ value, language, onChange, onCursor, commands, readOnly = false }) {
  const handleMount = (editor, monaco) => {
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => commands.current?.run())
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.Enter, () => commands.current?.fix())
    // Listener is disposed together with the editor on unmount.
    editor.onDidChangeCursorPosition((e) => onCursor?.({ line: e.position.lineNumber, col: e.position.column }))
    editor.focus()
  }

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
