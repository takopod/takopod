import { useCallback, useEffect, useRef, useState } from "react"
import type {
  ChatMessage,
  ErrorFrame,
  QueueStatusFrame,
  ServerFrame,
  UserMessageFrame,
} from "@/lib/types"

const RECONNECT_MAX_DELAY = 30_000

function getWsUrl(agentId: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
  return `${protocol}//${window.location.host}/api/ws?agent_id=${agentId}`
}

export function useWebSocket(agentId: string | null) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttempt = useRef(0)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(null)
  const errorTimer = useRef<ReturnType<typeof setTimeout>>(null)

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [queueStatus, setQueueStatus] = useState<QueueStatusFrame>({
    type: "queue_status",
    queued: 0,
    in_flight: 0,
    processed: 0,
  })
  const [error, setError] = useState<ErrorFrame | null>(null)
  const [connected, setConnected] = useState(false)

  const clearError = useCallback(() => {
    if (errorTimer.current) clearTimeout(errorTimer.current)
    errorTimer.current = setTimeout(() => setError(null), 5000)
  }, [])

  const connect = useCallback(() => {
    if (!agentId) return
    const ws = new WebSocket(getWsUrl(agentId))

    ws.onopen = () => {
      setConnected(true)
      setError(null)
      reconnectAttempt.current = 0
    }

    ws.onmessage = (event) => {
      const frame = JSON.parse(event.data) as ServerFrame
      if (frame.type === "queue_status") {
        setQueueStatus(frame)
      } else if (frame.type === "error") {
        setError(frame)
        clearError()
      } else if (frame.type === "status" && frame.status === "thinking") {
        const assistantId = `assistant-${frame.message_id}`
        setMessages((prev) => [
          ...prev,
          {
            id: assistantId,
            role: "assistant",
            content: "",
            timestamp: Date.now(),
            streaming: true,
          },
        ])
      } else if (frame.type === "token") {
        const assistantId = `assistant-${frame.message_id}`
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantId
              ? { ...msg, content: msg.content + frame.content }
              : msg,
          ),
        )
      } else if (frame.type === "complete") {
        const assistantId = `assistant-${frame.message_id}`
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantId
              ? { ...msg, content: frame.content, streaming: false }
              : msg,
          ),
        )
      }
    }

    ws.onclose = () => {
      setConnected(false)
      wsRef.current = null

      const delay = Math.min(
        1000 * 2 ** reconnectAttempt.current,
        RECONNECT_MAX_DELAY,
      )
      reconnectAttempt.current += 1
      reconnectTimer.current = setTimeout(connect, delay)
    }

    wsRef.current = ws
  }, [agentId, clearError])

  useEffect(() => {
    if (!agentId) return
    setMessages([])
    setQueueStatus({ type: "queue_status", queued: 0, in_flight: 0, processed: 0 })
    connect()
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      if (errorTimer.current) clearTimeout(errorTimer.current)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [agentId, connect])

  const sendMessage = useCallback((content: string) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return

    const messageId = crypto.randomUUID()
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

  return { messages, queueStatus, error, connected, sendMessage }
}
