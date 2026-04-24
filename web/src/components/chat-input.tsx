import { useRef, useState, type FormEvent, type KeyboardEvent } from "react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { SendHorizontal, Square, Paperclip, X, FileIcon, ImageIcon, Loader2 } from "lucide-react"

interface PendingFile {
  file: File
  name: string
}

interface ChatInputProps {
  onSend: (content: string, attachments?: string[]) => void
  onStop?: () => void
  isStreaming?: boolean
  disabled: boolean
  sessionEnded?: string | null
  agentId?: string | null
}

export function ChatInput({ onSend, onStop, isStreaming, disabled, sessionEnded, agentId }: ChatInputProps) {
  const [value, setValue] = useState("")
  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([])
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  async function uploadFiles(files: PendingFile[]): Promise<string[]> {
    if (!agentId || files.length === 0) return []

    const formData = new FormData()
    for (const pf of files) {
      formData.append("files", pf.file)
    }

    const res = await fetch(`/api/agents/${agentId}/uploads`, {
      method: "POST",
      body: formData,
    })

    if (!res.ok) {
      throw new Error(`Upload failed: ${res.statusText}`)
    }

    const data = await res.json()
    return data.paths as string[]
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed && pendingFiles.length === 0) return

    let attachmentPaths: string[] | undefined
    if (pendingFiles.length > 0) {
      setUploading(true)
      try {
        attachmentPaths = await uploadFiles(pendingFiles)
      } catch {
        setUploading(false)
        return
      }
      setUploading(false)
    }

    onSend(trimmed || "See attached files.", attachmentPaths)
    setValue("")
    setPendingFiles([])
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  function handleFileSelect() {
    fileInputRef.current?.click()
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files
    if (!files) return

    const newFiles: PendingFile[] = Array.from(files).map((f) => ({
      file: f,
      name: f.name,
    }))
    setPendingFiles((prev) => [...prev, ...newFiles].slice(0, 10))

    // Reset input so the same file can be selected again
    e.target.value = ""
  }

  function removeFile(index: number) {
    setPendingFiles((prev) => prev.filter((_, i) => i !== index))
  }

  function isImage(name: string) {
    return /\.(png|jpe?g|gif|webp|svg|bmp)$/i.test(name)
  }

  const canSend = !disabled && !uploading && (value.trim() || pendingFiles.length > 0)

  return (
    <div className="border-t">
      {pendingFiles.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-4 pt-3">
          {pendingFiles.map((pf, i) => (
            <div
              key={`${pf.name}-${i}`}
              className="flex items-center gap-1.5 rounded-md border bg-muted/50 px-2 py-1 text-xs"
            >
              {isImage(pf.name) ? (
                <ImageIcon className="size-3.5 text-muted-foreground" />
              ) : (
                <FileIcon className="size-3.5 text-muted-foreground" />
              )}
              <span className="max-w-[120px] truncate">{pf.name}</span>
              <button
                type="button"
                onClick={() => removeFile(i)}
                className="ml-0.5 rounded-sm p-0.5 hover:bg-muted"
              >
                <X className="size-3" />
              </button>
            </div>
          ))}
        </div>
      )}
      <form onSubmit={handleSubmit} className="flex items-end gap-2 p-4">
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={handleFileChange}
        />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="shrink-0"
          disabled={disabled}
          onClick={handleFileSelect}
          title="Attach files"
        >
          <Paperclip className="size-4" />
        </Button>
        <Textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={sessionEnded ? "Session ended" : disabled ? "Disconnected..." : "Type a message..."}
          disabled={disabled}
          autoFocus
          rows={1}
          className="min-h-0 resize-none"
        />
        {isStreaming ? (
          <Button type="button" size="icon" variant="destructive" className="shrink-0" onClick={onStop} title="Stop generation">
            <Square className="size-4" />
          </Button>
        ) : (
          <Button type="submit" size="icon" className="shrink-0" disabled={!canSend}>
            {uploading ? <Loader2 className="size-4 animate-spin" /> : <SendHorizontal />}
          </Button>
        )}
      </form>
    </div>
  )
}
