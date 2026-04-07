import { useCallback, useEffect, useRef, useState } from "react"
import type {
  ChatMessage,
  ErrorFrame,
  QueueStatusFrame,
  ServerFrame,
  SystemErrorFrame,
  UserMessageFrame,
} from "@/lib/types"

const RECONNECT_MAX_DELAY = 30_000

function getWsUrl(agentId: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
  return `${protocol}//${window.location.host}/api/ws?agent_id=${agentId}`
}

interface ApiMessage {
  id: string
  role: string
  content: string
  created_at: string
  metadata?: string
  status?: string
}

function parseMessage(m: ApiMessage): ChatMessage {
  const msg: ChatMessage = {
    id: m.id,
    role: m.role as "user" | "assistant",
    content: m.content,
    timestamp: new Date(m.created_at).getTime(),
    status: (m.status as "streaming" | "complete") ?? "complete",
  }
  if (m.metadata) {
    try {
      const meta = JSON.parse(m.metadata)
      if (Array.isArray(meta.blocks) && meta.blocks.length > 0) {
        msg.blocks = meta.blocks
        msg.toolCalls = meta.blocks
          .filter((b: { type: string }) => b.type === "tool_call")
          .map((b: { tool: import("@/lib/types").ToolCallInfo }) => b.tool)
      }
      if (meta.source === "scheduled_task") {
        msg.source = "scheduled_task"
      }
    } catch {
      // metadata is not valid JSON — ignore
    }
  }
  return msg
}

export function useWebSocket(agentId: string | null) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttempt = useRef(0)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(null)
  const errorTimer = useRef<ReturnType<typeof setTimeout>>(null)
  const agentIdRef = useRef(agentId)
  agentIdRef.current = agentId

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [hasOlderMessages, setHasOlderMessages] = useState(true)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [queueStatus, setQueueStatus] = useState<QueueStatusFrame>({
    type: "queue_status",
    queued: 0,
    in_flight: 0,
    processed: 0,
  })
  const [error, setError] = useState<ErrorFrame | null>(null)
  const [systemError, setSystemError] = useState<SystemErrorFrame | null>(null)
  const [connected, setConnected] = useState(false)
  const [sessionEnded, setSessionEnded] = useState<string | null>(null)

  const clearError = useCallback(() => {
    if (errorTimer.current) clearTimeout(errorTimer.current)
    errorTimer.current = setTimeout(() => setError(null), 5000)
  }, [])

  const fetchMessage = useCallback((messageId: string) => {
    const aid = agentIdRef.current
    if (!aid) return
    fetch(`/api/agents/${aid}/messages/${messageId}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data: ApiMessage | null) => {
        if (!data) return
        const parsed = parseMessage(data)
        setMessages((prev) => {
          const idx = prev.findIndex((m) => m.id === parsed.id)
          if (idx >= 0) {
            const updated = [...prev]
            updated[idx] = parsed
            return updated
          }
          return [...prev, parsed]
        })
      })
      .catch(() => {})
  }, [])

  const connect = useCallback(() => {
    if (!agentId) return
    const ws = new WebSocket(getWsUrl(agentId))

    ws.onopen = () => {
      setConnected(true)
      setError(null)
      setSystemError(null)
      setSessionEnded(null)
      reconnectAttempt.current = 0
    }

    ws.onmessage = (event) => {
      const frame = JSON.parse(event.data) as ServerFrame
      if (frame.type === "queue_status") {
        setQueueStatus(frame)
      } else if (frame.type === "system_error") {
        setSystemError(frame)
        if (!frame.fatal) {
          // Auto-dismiss transient errors after 5s
          setTimeout(() => setSystemError(null), 5000)
        }
      } else if (frame.type === "error") {
        setError(frame)
        clearError()
      } else if (frame.type === "message_updated") {
        fetchMessage(frame.message_id)
      } else if (
        frame.type === "status" &&
        frame.status === "context_cleared"
      ) {
        // Messages already cleared optimistically in sendSystemCommand.
        // Don't setMessages([]) here — it would wipe any message the user
        // sent between the clear request and this server confirmation.
        setHasOlderMessages(true)
      }
    }

    ws.onclose = (event) => {
      setConnected(false)

      // Application-specific close codes (4000-4999): session ended, do NOT reconnect
      if (event.code >= 4000 && event.code <= 4999) {
        const reason =
          event.code === 4001
            ? "Session ended due to inactivity"
            : event.code === 4002
              ? "Session terminated by admin"
              : "Session ended"
        setSessionEnded(reason)
        wsRef.current = null
        return
      }

      // Normal/unexpected close: auto-reconnect with backoff
      if (wsRef.current === ws) {
        wsRef.current = null
        const delay = Math.min(
          1000 * 2 ** reconnectAttempt.current,
          RECONNECT_MAX_DELAY,
        )
        reconnectAttempt.current += 1
        reconnectTimer.current = setTimeout(connect, delay)
      }
    }

    wsRef.current = ws
  }, [agentId, clearError, fetchMessage])

  useEffect(() => {
    if (!agentId) return

    // Close any existing connection immediately
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
    if (wsRef.current) {
      wsRef.current.onclose = null // prevent stale reconnect
      wsRef.current.close()
      wsRef.current = null
    }

    // Load message history from the API
    setMessages([])
    setQueueStatus({ type: "queue_status", queued: 0, in_flight: 0, processed: 0 })

    fetch(`/api/agents/${agentId}/messages`)
      .then((res) => (res.ok ? res.json() : []))
      .then((history: ApiMessage[]) => {
        setMessages(history.map(parseMessage))
      })
      .catch(() => {})

    reconnectAttempt.current = 0
    connect()
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      if (errorTimer.current) clearTimeout(errorTimer.current)
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [agentId, connect])

  const sendMessage = useCallback((content: string) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return

    const messageId = crypto.randomUUID?.() ??
      "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0
        return (c === "x" ? r : (r & 0x3) | 0x8).toString(16)
      })
    const frame: UserMessageFrame = {
      type: "user_message",
      content,
      message_id: messageId,
    }

    setMessages((prev) => [
      ...prev,
      { id: messageId, role: "user", content, timestamp: Date.now() },
    ])

    ws.send(JSON.stringify(frame))
  }, [])

  const sendSystemCommand = useCallback((command: string) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ type: "system_command", command }))

    // Hide persisted messages so they don't reload on refresh
    if (command === "clear_context") {
      setMessages([])
      setHasOlderMessages(true)
      if (agentId) {
        fetch(`/api/agents/${agentId}/messages`, { method: "PATCH" }).catch(() => {})
      }
    }
  }, [agentId])

  const loadOlderMessages = useCallback(async () => {
    if (!agentId || loadingOlder) return
    setLoadingOlder(true)
    try {
      const oldest = messages[0]
      const params = oldest
        ? `?before=${encodeURIComponent(new Date(oldest.timestamp).toISOString())}`
        : ""
      const res = await fetch(`/api/agents/${agentId}/messages/older${params}`)
      if (!res.ok) return
      const data = await res.json()
      if (data.messages.length > 0) {
        const olderMessages = (data.messages as ApiMessage[]).map(parseMessage)
        setMessages((prev) => [...olderMessages, ...prev])
      }
      setHasOlderMessages(data.has_more)
    } catch {
      // ignore
    } finally {
      setLoadingOlder(false)
    }
  }, [agentId, loadingOlder, messages])

  const reconnect = useCallback(() => {
    setSessionEnded(null)
    reconnectAttempt.current = 0
    connect()
  }, [connect])

  return { messages, queueStatus, error, systemError, connected, sessionEnded, sendMessage, sendSystemCommand, reconnect, hasOlderMessages, loadingOlder, loadOlderMessages }
}
