import { useCallback, useEffect, useState } from "react"
import { Link, Route, Routes, useLocation, useNavigate } from "react-router-dom"
import { AgentsView } from "@/components/agents-view"
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
import type { Agent } from "@/lib/types"
import { Moon, Plus, Sun } from "lucide-react"

function NavLink({
  to,
  children,
  match,
}: {
  to: string
  children: React.ReactNode
  match: boolean
}) {
  return (
    <Link
      to={to}
      className={`rounded-md px-3 py-1.5 text-left text-sm ${
        match
          ? "bg-muted font-medium text-foreground"
          : "text-muted-foreground hover:text-foreground"
      }`}
    >
      {children}
    </Link>
  )
}

function ChatView({
  selectedAgentId,
}: {
  selectedAgentId: string | null
}) {
  const { messages, queueStatus, error, connected, sendMessage } =
    useWebSocket(selectedAgentId)

  if (!selectedAgentId) {
    return (
      <div className="flex flex-1 items-center justify-center text-muted-foreground">
        <p className="text-sm">Select an agent or create one to get started.</p>
      </div>
    )
  }

  return (
    <>
      <ChatMessageList messages={messages} />
      <ErrorNotification error={error} />
      <ChatInput onSend={sendMessage} disabled={!connected} />
    </>
  )
}

function QueueView({
  selectedAgentId,
}: {
  selectedAgentId: string | null
}) {
  const { queueStatus, connected } = useWebSocket(selectedAgentId)

  return <QueueStatusPanel status={queueStatus} connected={connected} />
}

export function App() {
  const { theme, setTheme } = useTheme()
  const location = useLocation()
  const navigate = useNavigate()
  const [agents, setAgents] = useState<Agent[]>([])
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null)

  const fetchAgents = useCallback(async () => {
    const res = await fetch("/api/agents")
    if (res.ok) {
      const data: Agent[] = await res.json()
      setAgents(data)
      if (!selectedAgentId && data.length > 0) {
        setSelectedAgentId(data[0].id)
      }
    }
  }, [selectedAgentId])

  useEffect(() => {
    fetchAgents()
  }, [fetchAgents])

  const handleCreateAgent = async () => {
    const name = prompt("Agent name:")
    if (!name?.trim()) return

    const res = await fetch("/api/agents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() }),
    })
    if (res.ok) {
      const agent: Agent = await res.json()
      setAgents((prev) => [...prev, agent])
      setSelectedAgentId(agent.id)
    }
  }

  const handleSelectAgentFromView = (id: string) => {
    setSelectedAgentId(id)
    navigate("/")
  }

  const currentPath = location.pathname

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
            <NavLink to="/" match={currentPath === "/"}>
              Chat
            </NavLink>
            <NavLink
              to="/agents"
              match={currentPath.startsWith("/agents")}
            >
              Agents
            </NavLink>
            <NavLink to="/queue" match={currentPath === "/queue"}>
              Queue Status
            </NavLink>
          </div>
          <div className="mt-auto px-3 py-4">
            <Select
              value={selectedAgentId ?? undefined}
              onValueChange={setSelectedAgentId}
            >
              <SelectTrigger className="w-full text-xs">
                <SelectValue placeholder="Select agent" />
              </SelectTrigger>
              <SelectContent>
                {agents.map((agent) => (
                  <SelectItem key={agent.id} value={agent.id}>
                    {agent.name}
                  </SelectItem>
                ))}
                <button
                  onClick={handleCreateAgent}
                  className="flex w-full items-center gap-1.5 rounded-sm px-2 py-1.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  <Plus className="size-3.5" />
                  Create Agent
                </button>
              </SelectContent>
            </Select>
          </div>
        </nav>

        <main className="flex flex-1 flex-col">
          <Routes>
            <Route
              path="/"
              element={<ChatView selectedAgentId={selectedAgentId} />}
            />
            <Route
              path="/agents"
              element={
                <AgentsView
                  agents={agents}
                  onSelectAgent={handleSelectAgentFromView}
                />
              }
            />
            <Route
              path="/agents/:agentId"
              element={
                <AgentsView
                  agents={agents}
                  onSelectAgent={handleSelectAgentFromView}
                />
              }
            />
            <Route
              path="/agents/:agentId/:file"
              element={
                <AgentsView
                  agents={agents}
                  onSelectAgent={handleSelectAgentFromView}
                />
              }
            />
            <Route
              path="/queue"
              element={<QueueView selectedAgentId={selectedAgentId} />}
            />
          </Routes>
        </main>

        <aside className="w-52 shrink-0 border-l" />
      </div>
    </div>
  )
}

export default App
