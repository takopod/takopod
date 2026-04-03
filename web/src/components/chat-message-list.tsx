import { useEffect, useRef, useState } from "react"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import type { ChatMessage, ToolCallInfo } from "@/lib/types"
import { ChevronDown, ChevronRight, Terminal } from "lucide-react"

function ToolCallBlock({ tool }: { tool: ToolCallInfo }) {
  const [open, setOpen] = useState(false)

  const inputSnippet = JSON.stringify(tool.tool_input)
  const truncated =
    inputSnippet.length > 80 ? inputSnippet.slice(0, 77) + "..." : inputSnippet

  return (
    <div className="mt-1.5 rounded border bg-background/50 text-xs">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-1.5 px-2 py-1 text-left text-muted-foreground hover:text-foreground"
      >
        {open ? (
          <ChevronDown className="size-3 shrink-0" />
        ) : (
          <ChevronRight className="size-3 shrink-0" />
        )}
        <Terminal className="size-3 shrink-0" />
        <span className="font-medium text-foreground">{tool.tool_name}</span>
        {!open && (
          <span className="truncate font-mono text-muted-foreground">
            {truncated}
          </span>
        )}
      </button>
      {open && (
        <div className="border-t px-2 py-1.5">
          <div className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            Input
          </div>
          <pre className="whitespace-pre-wrap break-all font-mono text-[11px]">
            {JSON.stringify(tool.tool_input, null, 2)}
          </pre>
          {tool.output != null && (
            <>
              <div className="mb-1 mt-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                Output
              </div>
              <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px]">
                {tool.output}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  )
}

export function ChatMessageList({ messages }: { messages: ChatMessage[] }) {
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center text-muted-foreground">
        <p className="text-sm">Send a message to get started.</p>
      </div>
    )
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4">
      <div className="flex flex-col gap-3">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[75%] rounded-lg px-3 py-2 text-sm ${
                msg.role === "user"
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-foreground"
              }`}
            >
              {msg.streaming && !msg.content ? (
                <span className="inline-block animate-pulse">...</span>
              ) : msg.role === "assistant" ? (
                <div className="markdown-body">
                  <Markdown remarkPlugins={[remarkGfm]}>{msg.content}</Markdown>
                </div>
              ) : (
                <span className="whitespace-pre-wrap">{msg.content}</span>
              )}
              {msg.toolCalls && msg.toolCalls.length > 0 && (
                <div className="mt-2">
                  {msg.toolCalls.map((tool) => (
                    <ToolCallBlock key={tool.tool_call_id} tool={tool} />
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  )
}
