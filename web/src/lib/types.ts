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

export interface ToolCallFrame {
  type: "tool_call"
  tool_name: string
  tool_input: Record<string, unknown>
  tool_call_id: string
  message_id: string
}

export interface ToolResultFrame {
  type: "tool_result"
  tool_call_id: string
  output: string
  message_id: string
}

export type ServerFrame =
  | QueueStatusFrame
  | ErrorFrame
  | TokenFrame
  | StatusFrame
  | CompleteFrame
  | ToolCallFrame
  | ToolResultFrame

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
  streaming?: boolean
  toolCalls?: ToolCallInfo[]
  blocks?: ContentBlock[]
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
