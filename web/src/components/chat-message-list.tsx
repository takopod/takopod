import { useEffect, useRef, useState } from "react"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import type { ChatMessage, ContentBlock, ToolCallInfo } from "@/lib/types"
import { Check, ChevronDown, ChevronRight, Clock, FileIcon, ImageIcon, Shield, Terminal, Wrench, X } from "lucide-react"

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

const TOOL_GROUP_COLLAPSE_THRESHOLD = 3

function ToolCallGroup({ tools }: { tools: ToolCallInfo[] }) {
  const [expanded, setExpanded] = useState(false)

  if (tools.length < TOOL_GROUP_COLLAPSE_THRESHOLD) {
    return (
      <>
        {tools.map((t) => (
          <ToolCallBlock key={t.tool_call_id} tool={t} />
        ))}
      </>
    )
  }

  const toolNames = tools.map((t) => t.tool_name)
  const uniqueNames = [...new Set(toolNames)]
  const summary =
    uniqueNames.length <= 3
      ? uniqueNames.join(", ")
      : `${uniqueNames.slice(0, 3).join(", ")} +${uniqueNames.length - 3} more`

  return (
    <div className="mt-1.5 rounded border bg-background/50 text-xs">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left text-muted-foreground hover:text-foreground"
      >
        {expanded ? (
          <ChevronDown className="size-3 shrink-0" />
        ) : (
          <ChevronRight className="size-3 shrink-0" />
        )}
        <Wrench className="size-3 shrink-0" />
        <span className="font-medium text-foreground">
          {tools.length} tool calls
        </span>
        {!expanded && (
          <span className="truncate font-mono text-muted-foreground">
            {summary}
          </span>
        )}
      </button>
      {expanded && (
        <div className="border-t px-1 py-1">
          {tools.map((t) => (
            <ToolCallBlock key={t.tool_call_id} tool={t} />
          ))}
        </div>
      )}
    </div>
  )
}

const APPROVAL_SOURCE_LABELS: Record<string, string> = { github: "GitHub", jira: "Jira", gws: "Google Workspace" }
const APPROVAL_SOURCE_PREFIXES: Record<string, string> = { github: "gh", jira: "acli jira", gws: "gws" }

function GhApprovalBlock({
  block,
  onRespond,
}: {
  block: Extract<ContentBlock, { type: "gh_approval" }>
  onRespond?: (requestId: string, approved: boolean) => void
}) {
  const [clicked, setClicked] = useState(false)
  const isPending = block.status === "pending" && !clicked
  const isApproved = block.status === "approved"
  const isDenied = block.status === "denied"

  const source = block.source ?? "github"
  const displayLabel = `${APPROVAL_SOURCE_LABELS[source] ?? source} Command Approval`
  const commandPrefix = APPROVAL_SOURCE_PREFIXES[source] ?? source

  const handleRespond = (approved: boolean) => {
    setClicked(true)
    onRespond?.(block.request_id, approved)
  }

  return (
    <div className="mt-1.5 rounded border border-amber-500/30 bg-amber-50 dark:bg-amber-950/20 px-3 py-2 text-xs">
      <div className="flex items-center gap-1.5 mb-1.5 font-medium text-amber-700 dark:text-amber-400">
        <Shield className="size-3" />
        {displayLabel}
      </div>
      <code className="block bg-background/50 px-2 py-1 rounded text-[11px] mb-2">
        {commandPrefix} {block.command}
      </code>
      <div className="flex gap-2">
        {isPending ? (
          <>
            <button
              onClick={() => handleRespond(true)}
              className="inline-flex items-center gap-1 rounded bg-green-600 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-green-700 transition-colors"
            >
              <Check className="size-3" />
              Approve
            </button>
            <button
              onClick={() => handleRespond(false)}
              className="inline-flex items-center gap-1 rounded border border-red-400 px-2.5 py-1 text-[11px] font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
            >
              <X className="size-3" />
              Deny
            </button>
          </>
        ) : clicked && !isApproved && !isDenied ? (
          <span className="inline-flex items-center gap-1 text-[11px] font-medium text-muted-foreground animate-pulse">
            Waiting for response...
          </span>
        ) : (
          <span className={`inline-flex items-center gap-1 text-[11px] font-medium ${isApproved ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
            {isApproved ? <Check className="size-3" /> : <X className="size-3" />}
            {isApproved ? "Approved" : isDenied ? "Denied" : "Timed out"}
          </span>
        )}
      </div>
    </div>
  )
}

function isImageFile(path: string) {
  return /\.(png|jpe?g|gif|webp|svg|bmp)$/i.test(path)
}

function AttachmentChips({ paths }: { paths: string[] }) {
  return (
    <div className="mt-1.5 flex flex-wrap gap-1">
      {paths.map((p) => {
        const name = p.split("/").pop() ?? p
        return (
          <span
            key={p}
            className="inline-flex items-center gap-1 rounded border bg-primary-foreground/10 px-1.5 py-0.5 text-[11px] text-primary-foreground/80"
          >
            {isImageFile(name) ? (
              <ImageIcon className="size-3" />
            ) : (
              <FileIcon className="size-3" />
            )}
            <span className="max-w-[100px] truncate">{name}</span>
          </span>
        )
      })}
    </div>
  )
}

type GroupedBlock =
  | { kind: "single"; block: ContentBlock; index: number }
  | { kind: "tool_group"; tools: ToolCallInfo[]; startIndex: number }

function groupBlocks(blocks: ContentBlock[]): GroupedBlock[] {
  const groups: GroupedBlock[] = []
  let toolBatch: ToolCallInfo[] = []
  let batchStart = 0

  for (let i = 0; i < blocks.length; i++) {
    const block = blocks[i]
    if (block.type === "tool_call") {
      if (toolBatch.length === 0) batchStart = i
      toolBatch.push(block.tool)
    } else {
      if (toolBatch.length > 0) {
        groups.push({ kind: "tool_group", tools: toolBatch, startIndex: batchStart })
        toolBatch = []
      }
      groups.push({ kind: "single", block, index: i })
    }
  }
  if (toolBatch.length > 0) {
    groups.push({ kind: "tool_group", tools: toolBatch, startIndex: batchStart })
  }
  return groups
}

interface ChatMessageListProps {
  messages: ChatMessage[]
  hasOlderMessages?: boolean
  loadingOlder?: boolean
  onLoadOlder?: () => void
  onApprovalRespond?: (requestId: string, approved: boolean) => void
}

export function ChatMessageList({
  messages,
  hasOlderMessages,
  loadingOlder,
  onLoadOlder,
  onApprovalRespond,
}: ChatMessageListProps) {
  const endRef = useRef<HTMLDivElement>(null)
  const prevLastIdRef = useRef<string | null>(null)

  useEffect(() => {
    const lastId = messages.length > 0 ? messages[messages.length - 1].id : null
    if (lastId !== prevLastIdRef.current) {
      const isInitialLoad = prevLastIdRef.current === null
      endRef.current?.scrollIntoView({
        behavior: isInitialLoad ? "instant" : "smooth",
      })
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
            <div className="max-w-[75%] min-w-0 overflow-hidden">
              {msg.source === "scheduled_task" && (
                <div className="mb-1 flex items-center gap-1 text-xs text-amber-600">
                  <Clock className="size-3" />
                  <span>Scheduled Task</span>
                </div>
              )}
              <div
                className={`rounded-lg px-3 py-2 text-sm overflow-hidden ${
                  msg.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-foreground"
                } ${msg.source === "scheduled_task" ? "border-l-2 border-amber-500" : ""}`}
              >
              {msg.blocks && msg.blocks.length > 0 ? (
                groupBlocks(msg.blocks).map((group) =>
                  group.kind === "tool_group" ? (
                    <ToolCallGroup key={`tg-${group.startIndex}`} tools={group.tools} />
                  ) : group.block.type === "text" ? (
                    <div key={group.index} className="markdown-body">
                      <Markdown remarkPlugins={[remarkGfm]} components={{ a: ({ children, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer">{children}</a> }}>{group.block.text}</Markdown>
                    </div>
                  ) : group.block.type === "gh_approval" ? (
                    <GhApprovalBlock key={group.block.request_id} block={group.block} onRespond={onApprovalRespond} />
                  ) : null,
                )
              ) : msg.status === "streaming" && !msg.content ? (
                <span className="inline-block animate-pulse text-muted-foreground text-xs">&nbsp;</span>
              ) : msg.role === "assistant" ? (
                <div className="markdown-body">
                  <Markdown remarkPlugins={[remarkGfm]} components={{ a: ({ children, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer">{children}</a> }}>{msg.content}</Markdown>
                </div>
              ) : (
                <span className="whitespace-pre-wrap break-all">{msg.content}</span>
              )}
              {msg.role === "user" && msg.attachments && msg.attachments.length > 0 && (
                <AttachmentChips paths={msg.attachments} />
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
