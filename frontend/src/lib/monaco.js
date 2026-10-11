// Bundle Monaco locally instead of loading it from a CDN, so the editor works offline.
import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor/esm/vs/editor/edcore.main'
import 'monaco-editor/esm/vs/basic-languages/python/python.contribution'
import 'monaco-editor/esm/vs/basic-languages/javascript/javascript.contribution'
import 'monaco-editor/esm/vs/basic-languages/cpp/cpp.contribution'
import 'monaco-editor/esm/vs/basic-languages/java/java.contribution'
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'

self.MonacoEnvironment = {
  getWorker: () => new EditorWorker(),
}

monaco.editor.defineTheme('fixpoint', {
  base: 'vs-dark',
  inherit: true,
  rules: [
    { token: 'comment', foreground: '555b63', fontStyle: 'italic' },
    { token: 'keyword', foreground: 'd4ff3a' },
    { token: 'string', foreground: '9ad1a8' },
    { token: 'number', foreground: 'ffb020' },
    { token: 'type', foreground: '5ab0ff' },
    { token: 'delimiter', foreground: '8a8f98' },
  ],
  colors: {
    'editor.background': '#0b0c0e',
    'editor.foreground': '#e6e6e3',
    'editorLineNumber.foreground': '#3a3f47',
    'editorLineNumber.activeForeground': '#8a8f98',
    'editor.lineHighlightBackground': '#111316',
    'editor.lineHighlightBorder': '#00000000',
    'editorCursor.foreground': '#d4ff3a',
    'editor.selectionBackground': '#d4ff3a33',
    'editor.inactiveSelectionBackground': '#d4ff3a1a',
    'editorIndentGuide.background1': '#1a1d21',
    'editorIndentGuide.activeBackground1': '#2c3138',
    'editorGutter.background': '#0b0c0e',
    'editorWidget.background': '#111316',
    'editorWidget.border': '#24282e',
    'diffEditor.insertedTextBackground': '#3ddc8426',
    'diffEditor.removedTextBackground': '#ff4d4d26',
    'diffEditor.insertedLineBackground': '#3ddc8414',
    'diffEditor.removedLineBackground': '#ff4d4d14',
    'diffEditor.diagonalFill': '#24282e',
    'scrollbarSlider.background': '#24282e99',
    'scrollbarSlider.hoverBackground': '#343a42',
  },
})

loader.config({ monaco })

export default monaco
