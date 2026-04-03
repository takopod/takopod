import { useEffect, useRef } from "react"
import { ScrollArea } from "@/components/ui/scroll-area"
import type { ChatMessage } from "@/lib/types"

export function ChatMessageList({ messages }: { messages: ChatMessage[] }) {
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages.length])

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center text-muted-foreground">
        <p className="text-sm">Send a message to get started.</p>
      </div>
    )
  }

  return (
    <ScrollArea className="flex-1 p-4">
      <div className="flex flex-col gap-3">
        {messages.map((msg) => (
          <div key={msg.id} className="flex justify-end">
            <div className="max-w-[75%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground">
              {msg.content}
            </div>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </ScrollArea>
  )
}
