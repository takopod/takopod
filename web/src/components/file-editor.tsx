import { useState } from "react"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Eye, Pencil } from "lucide-react"

interface FileEditorProps {
  value: string
  onChange?: (value: string) => void
  readOnly?: boolean
  markdown?: boolean
}

export function FileEditor({ value, onChange, readOnly, markdown }: FileEditorProps) {
  const [preview, setPreview] = useState(!!markdown)
  const lineCount = value.split("\n").length
  const showPreview = markdown && preview

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {markdown && (
        <div className="flex items-center border-b px-3 py-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setPreview(!preview)}
          >
            {preview ? (
              <><Pencil className="mr-1.5 size-3.5" />Edit</>
            ) : (
              <><Eye className="mr-1.5 size-3.5" />Preview</>
            )}
          </Button>
        </div>
      )}
      {showPreview ? (
        <div className="flex-1 overflow-y-auto p-6">
          <div className="prose prose-sm dark:prose-invert max-w-none">
            <Markdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ children, ...props }) => (
                  <a {...props} target="_blank" rel="noopener noreferrer">{children}</a>
                ),
              }}
            >
              {value}
            </Markdown>
          </div>
        </div>
      ) : (
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
      )}
    </div>
  )
}
