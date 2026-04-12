import { Textarea } from "@/components/ui/textarea"

interface FileEditorProps {
  value: string
  onChange?: (value: string) => void
  readOnly?: boolean
}

export function FileEditor({ value, onChange, readOnly }: FileEditorProps) {
  const lineCount = value.split("\n").length

  return (
    <div className="flex flex-1 overflow-hidden font-mono text-xs">
      <div
        className="shrink-0 select-none border-r bg-muted/50 px-3 py-3 text-right text-muted-foreground"
        aria-hidden
      >
        {Array.from({ length: lineCount }, (_, i) => (
          <div key={i} className="leading-5">
            {i + 1}
          </div>
        ))}
      </div>
      <Textarea
        value={value}
        onChange={onChange ? (e) => onChange(e.target.value) : undefined}
        readOnly={readOnly}
        className="flex-1 resize-none rounded-none border-0 p-3 leading-5 shadow-none focus-visible:ring-0"
        spellCheck={false}
      />
    </div>
  )
}
