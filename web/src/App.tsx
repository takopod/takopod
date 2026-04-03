import { useState } from "react"
import { ChatInput } from "@/components/chat-input"
import { ChatMessageList } from "@/components/chat-message-list"
import { ErrorNotification } from "@/components/error-notification"
import { QueueStatusPanel } from "@/components/queue-status-panel"
import { useWebSocket } from "@/hooks/use-websocket"

type View = "chat" | "queue"

export function App() {
  const [view, setView] = useState<View>("chat")
  const { messages, queueStatus, error, connected, sendMessage } =
    useWebSocket()

  return (
    <div className="flex h-svh">
      <nav className="flex w-52 shrink-0 flex-col border-r">
        <div className="px-4 py-5 text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Navigation
        </div>
        <div className="flex flex-col gap-0.5 px-2">
          <button
            onClick={() => setView("chat")}
            className={`rounded-md px-3 py-1.5 text-left text-sm ${
              view === "chat"
                ? "bg-muted font-medium text-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            Chat
          </button>
          <button
            onClick={() => setView("queue")}
            className={`rounded-md px-3 py-1.5 text-left text-sm ${
              view === "queue"
                ? "bg-muted font-medium text-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            Queue Status
          </button>
        </div>
        <div className="mt-auto px-4 py-4">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span
              className={`inline-block size-2 rounded-full ${connected ? "bg-green-500" : "bg-destructive"}`}
            />
            {connected ? "Connected" : "Disconnected"}
          </div>
        </div>
      </nav>

      <main className="flex flex-1 flex-col">
        {view === "chat" ? (
          <>
            <ChatMessageList messages={messages} />
            <ErrorNotification error={error} />
            <ChatInput onSend={sendMessage} disabled={!connected} />
          </>
        ) : (
          <QueueStatusPanel status={queueStatus} connected={connected} />
        )}
      </main>

      <aside className="w-52 shrink-0 border-l" />
    </div>
  )
}

export default App
