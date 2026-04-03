import { useCallback, useEffect, useRef, useState } from "react"
import type {
  ChatMessage,
  ErrorFrame,
  QueueStatusFrame,
  ServerFrame,
  UserMessageFrame,
} from "@/lib/types"

const RECONNECT_MAX_DELAY = 30_000

function getWsUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
  return `${protocol}//${window.location.host}/api/ws`
}

export function useWebSocket() {
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
    const ws = new WebSocket(getWsUrl())

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
  }, [clearError])

  useEffect(() => {
    connect()
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      if (errorTimer.current) clearTimeout(errorTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

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
