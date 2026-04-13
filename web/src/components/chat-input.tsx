import { useState, type FormEvent, type KeyboardEvent } from "react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { SendHorizontal } from "lucide-react"

interface ChatInputProps {
  onSend: (content: string) => void
  disabled: boolean
  sessionEnded?: string | null
}

export function ChatInput({ onSend, disabled, sessionEnded }: ChatInputProps) {
  const [value, setValue] = useState("")

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed) return
    onSend(trimmed)
    setValue("")
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex gap-2 border-t p-4">
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
      <Button type="submit" size="icon" disabled={disabled || !value.trim()}>
        <SendHorizontal />
      </Button>
    </form>
  )
}
