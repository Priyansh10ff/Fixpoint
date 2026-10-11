export default function StdinPanel({ value, onChange }) {
  return (
    <div className="flex h-full flex-col">
      <p className="label shrink-0 px-4 pt-3 text-mute">standard input · passed to the program on every run</p>
      <textarea
        aria-label="Standard input"
        className="m-3 mt-2 min-h-0 flex-1 resize-none border border-line bg-bg p-3 font-mono text-[13px] text-text outline-none placeholder:text-mute focus:border-accent"
        spellCheck={false}
        placeholder="Type input here, e.g.&#10;5&#10;1 2 3 4 5"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  )
}
