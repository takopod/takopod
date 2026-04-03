import { useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { SendHorizontal } from "lucide-react"

interface ChatInputProps {
  onSend: (content: string) => void
  disabled: boolean
}

export function ChatInput({ onSend, disabled }: ChatInputProps) {
  const [value, setValue] = useState("")

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed) return
    onSend(trimmed)
    setValue("")
  }

  return (
    <form onSubmit={handleSubmit} className="flex gap-2 border-t p-4">
      <Input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={disabled ? "Disconnected..." : "Type a message..."}
        disabled={disabled}
        autoFocus
      />
      <Button type="submit" size="icon" disabled={disabled || !value.trim()}>
        <SendHorizontal />
      </Button>
    </form>
  )
}
