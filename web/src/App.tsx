import { useState } from "react"
import { ChatInput } from "@/components/chat-input"
import { ChatMessageList } from "@/components/chat-message-list"
import { ErrorNotification } from "@/components/error-notification"
import { QueueStatusPanel } from "@/components/queue-status-panel"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useTheme } from "@/components/theme-provider"
import { useWebSocket } from "@/hooks/use-websocket"
import { Moon, Plus, Sun } from "lucide-react"

type View = "chat" | "queue"

export function App() {
  const [view, setView] = useState<View>("chat")
  const { theme, setTheme } = useTheme()
  const { messages, queueStatus, error, connected, sendMessage } =
    useWebSocket()

  return (
    <div className="flex h-svh flex-col">
      <header className="flex h-12 shrink-0 items-center justify-between border-b px-4">
        <span className="text-sm font-medium">rhclaw</span>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        >
          {theme === "dark" ? (
            <Sun className="size-4" />
          ) : (
            <Moon className="size-4" />
          )}
        </Button>
      </header>

      <div className="flex flex-1 overflow-hidden">
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
          <div className="mt-auto px-3 py-4">
            <Select defaultValue="default">
              <SelectTrigger className="w-full text-xs">
                <SelectValue placeholder="Select agent" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="default">Default Agent</SelectItem>
                <button className="flex w-full items-center gap-1.5 rounded-sm px-2 py-1.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground">
                  <Plus className="size-3.5" />
                  Create Agent
                </button>
              </SelectContent>
            </Select>
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
    </div>
  )
}

export default App
