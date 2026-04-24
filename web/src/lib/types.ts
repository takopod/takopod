export interface UserMessageFrame {
  type: "user_message"
  content: string
  message_id: string
  attachments?: string[]  // relative workspace paths from upload endpoint
}

export interface QueueStatusFrame {
  type: "queue_status"
  queued: number
  in_flight: number
}

export interface ErrorFrame {
  type: "error"
  code: "RATE_LIMITED" | "QUEUE_FULL"
  retry_after_seconds?: number
}

export interface MessageUpdatedFrame {
  type: "message_updated"
  message_id: string
  message?: {
    id: string
    role: string
    content: string
    created_at: string
    metadata?: string
    status?: string
  }
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

export interface GhApprovalRequestFrame {
  type: "gh_approval_request"
  request_id: string
  agent_id: string
  command: string
  message_id: string
  timestamp: string
}

export interface MessagesSyncFrame {
  type: "messages_sync"
  messages: {
    id: string
    role: string
    content: string
    created_at: string
    metadata?: string
    status?: string
  }[]
}

export type ServerFrame =
  | QueueStatusFrame
  | ErrorFrame
  | MessageUpdatedFrame
  | StatusFrame
  | SystemErrorFrame
  | GhApprovalRequestFrame
  | MessagesSyncFrame

export interface ToolCallInfo {
  tool_name: string
  tool_input: Record<string, unknown>
  tool_call_id: string
  output?: string
}

export type ContentBlock =
  | { type: "text"; text: string }
  | { type: "tool_call"; tool: ToolCallInfo }
  | { type: "gh_approval"; request_id: string; command: string; status: "pending" | "approved" | "denied" }

export interface ChatMessage {
  id: string
  role: "user" | "assistant"
  content: string
  timestamp: number
  status?: "streaming" | "complete"
  toolCalls?: ToolCallInfo[]
  blocks?: ContentBlock[]
  source?: "user" | "scheduled_task"
  attachments?: string[]
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
  icon: string
  status: string
  created_at: string
  container_status?: string | null
  container_memory?: string
  container_cpus?: string
  model?: string | null
}
