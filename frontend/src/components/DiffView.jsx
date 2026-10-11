import { DiffEditor } from '@monaco-editor/react'
import { EDITOR_OPTIONS } from '../lib/editorOptions'

export default function DiffView({ original, modified, language }) {
  return (
    <div className="flex h-full flex-col">
      <div className="grid shrink-0 grid-cols-2 border-b border-line bg-surface">
        <div className="label border-r border-line px-3 py-1.5 text-err">original</div>
        <div className="label px-3 py-1.5 text-ok">proposed fix</div>
      </div>
      <div className="min-h-0 flex-1">
        <DiffEditor
          height="100%"
          theme="fixpoint"
          language={language}
          original={original}
          modified={modified}
          keepCurrentOriginalModel
          keepCurrentModifiedModel
          loading={<div className="label p-4 text-mute">loading diff…</div>}
          options={{
            ...EDITOR_OPTIONS,
            readOnly: true,
            originalEditable: false,
            renderSideBySide: true,
            useInlineViewWhenSpaceIsLimited: true,
            renderOverviewRuler: false,
            enableSplitViewResizing: true,
          }}
        />
      </div>
    </div>
  )
}
