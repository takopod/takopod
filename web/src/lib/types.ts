export interface UserMessageFrame {
  type: "user_message"
  content: string
  message_id: string
}

export interface QueueStatusFrame {
  type: "queue_status"
  queued: number
  in_flight: number
  processed: number
}

export interface ErrorFrame {
  type: "error"
  code: "RATE_LIMITED" | "QUEUE_FULL"
  retry_after_seconds?: number
}

export type ServerFrame = QueueStatusFrame | ErrorFrame

export interface ChatMessage {
  id: string
  role: "user"
  content: string
  timestamp: number
}
