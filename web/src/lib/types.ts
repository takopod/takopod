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

export interface MessageUpdatedFrame {
  type: "message_updated"
  message_id: string
}

export interface StatusFrame {
  type: "status"
  status: string
  message_id: string
}

export interface SystemErrorFrame {
  type: "system_error"
  error: string
  fatal: boolean
}

export type ServerFrame =
  | QueueStatusFrame
  | ErrorFrame
  | MessageUpdatedFrame
  | StatusFrame
  | SystemErrorFrame

export interface ToolCallInfo {
  tool_name: string
  tool_input: Record<string, unknown>
  tool_call_id: string
  output?: string
}

export type ContentBlock =
  | { type: "text"; text: string }
  | { type: "tool_call"; tool: ToolCallInfo }

export interface ChatMessage {
  id: string
  role: "user" | "assistant"
  content: string
  timestamp: number
  status?: "streaming" | "complete"
  toolCalls?: ToolCallInfo[]
  blocks?: ContentBlock[]
  source?: "user" | "scheduled_task"
}

export interface FileEntry {
  name: string
  path: string
  type: "file" | "directory"
  size?: number
  modified_at?: string
}

export interface Agent {
  id: string
  name: string
  agent_type: string
  status: string
  created_at: string
}
