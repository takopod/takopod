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

export interface TokenFrame {
  type: "token"
  content: string
  message_id: string
  seq: number
}

export interface StatusFrame {
  type: "status"
  status: string
  message_id: string
}

export interface CompleteFrame {
  type: "complete"
  content: string
  message_id: string
  usage?: { input_tokens: number; output_tokens: number }
}

export type ServerFrame =
  | QueueStatusFrame
  | ErrorFrame
  | TokenFrame
  | StatusFrame
  | CompleteFrame

export interface ChatMessage {
  id: string
  role: "user" | "assistant"
  content: string
  timestamp: number
  streaming?: boolean
}

export interface Agent {
  id: string
  name: string
  agent_type: string
  status: string
  created_at: string
}
