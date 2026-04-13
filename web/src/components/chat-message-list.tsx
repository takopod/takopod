import { useEffect, useRef, useState } from "react"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import type { ChatMessage, ToolCallInfo } from "@/lib/types"
import { ChevronDown, ChevronRight, Clock, Terminal } from "lucide-react"

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
          {Object.entries(tool.tool_input).map(([key, value]) => (
            <div key={key} className="mb-1.5">
              <div className="mb-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                {key}
              </div>
              <pre className="whitespace-pre-wrap break-all font-mono text-[11px]">
                {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
              </pre>
            </div>
          ))}
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

interface ChatMessageListProps {
  messages: ChatMessage[]
  hasOlderMessages?: boolean
  loadingOlder?: boolean
  onLoadOlder?: () => void
}

export function ChatMessageList({
  messages,
  hasOlderMessages,
  loadingOlder,
  onLoadOlder,
}: ChatMessageListProps) {
  const endRef = useRef<HTMLDivElement>(null)
  const prevLastIdRef = useRef<string | null>(null)

  useEffect(() => {
    const lastId = messages.length > 0 ? messages[messages.length - 1].id : null
    // Only auto-scroll when the last message changes (new message appended),
    // not when older messages are prepended at the top.
    if (lastId !== prevLastIdRef.current) {
      endRef.current?.scrollIntoView({ behavior: "smooth" })
    }
    prevLastIdRef.current = lastId
  }, [messages])

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4">
      <div className="flex flex-col gap-3">
        {hasOlderMessages && (
          <div className="flex justify-center py-2">
            <button
              type="button"
              onClick={onLoadOlder}
              disabled={loadingOlder}
              className="text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
            >
              {loadingOlder ? "Loading..." : "Load older messages"}
            </button>
          </div>
        )}
        {messages.length === 0 && (
          <div className="flex flex-1 items-center justify-center text-muted-foreground py-8">
            <p className="text-sm">Send a message to get started.</p>
          </div>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div className="max-w-[75%]">
              {msg.source === "scheduled_task" && (
                <div className="mb-1 flex items-center gap-1 text-xs text-amber-600">
                  <Clock className="size-3" />
                  <span>Scheduled Task</span>
                </div>
              )}
              <div
                className={`rounded-lg px-3 py-2 text-sm ${
                  msg.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-foreground"
                } ${msg.source === "scheduled_task" ? "border-l-2 border-amber-500" : ""}`}
              >
              {msg.blocks && msg.blocks.length > 0 ? (
                msg.blocks.map((block, i) =>
                  block.type === "text" ? (
                    <div key={i} className="markdown-body">
                      <Markdown remarkPlugins={[remarkGfm]} components={{ a: ({ children, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer">{children}</a> }}>{block.text}</Markdown>
                    </div>
                  ) : (
                    <ToolCallBlock key={block.tool.tool_call_id} tool={block.tool} />
                  ),
                )
              ) : msg.status === "streaming" && !msg.content ? (
                <span className="inline-block animate-pulse text-muted-foreground text-xs">&nbsp;</span>
              ) : msg.role === "assistant" ? (
                <div className="markdown-body">
                  <Markdown remarkPlugins={[remarkGfm]} components={{ a: ({ children, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer">{children}</a> }}>{msg.content}</Markdown>
                </div>
              ) : (
                <span className="whitespace-pre-wrap">{msg.content}</span>
              )}
              </div>
            </div>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  )
}
