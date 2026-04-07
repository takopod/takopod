import { useCallback, useEffect, useState } from "react"
import { Link, Route, Routes, useLocation, useNavigate } from "react-router-dom"
import { AgentsView } from "@/components/agents-view"
import { ChatInput } from "@/components/chat-input"
import { ContainersView } from "@/components/containers-view"
import { SchedulesView } from "@/components/schedules-view"
import { SettingsView } from "@/components/settings-view"
import { SlackView } from "@/components/slack-view"
import { GitHubView } from "@/components/github-view"
import { ChatMessageList } from "@/components/chat-message-list"
import { ErrorNotification, SessionEndedBanner, SystemErrorNotification } from "@/components/error-notification"
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
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Eraser, Moon, Plus, Sun, X } from "lucide-react"

interface Template {
  id: string
  name: string
}

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

export function App() {
  const { theme, setTheme } = useTheme()
  const location = useLocation()
  const navigate = useNavigate()
  const [agents, setAgents] = useState<Agent[]>([])
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(
    () => localStorage.getItem("rhclaw:selectedAgentId"),
  )
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [templates, setTemplates] = useState<Template[]>([])
  const [newAgentName, setNewAgentName] = useState("")
  const [newAgentType, setNewAgentType] = useState("default")
  const [newSlackEnabled, setNewSlackEnabled] = useState(false)
  const [slackConfigured, setSlackConfigured] = useState(false)
  const [newGitHubEnabled, setNewGitHubEnabled] = useState(false)
  const [githubConfigured, setGithubConfigured] = useState(false)

  useEffect(() => {
    if (selectedAgentId) {
      localStorage.setItem("rhclaw:selectedAgentId", selectedAgentId)
    } else {
      localStorage.removeItem("rhclaw:selectedAgentId")
    }
  }, [selectedAgentId])

  const { messages, queueStatus, error, systemError, connected, sessionEnded, sendMessage, sendSystemCommand, reconnect, hasOlderMessages, loadingOlder, loadOlderMessages } =
    useWebSocket(selectedAgentId)

  const fetchAgents = useCallback(async () => {
    const res = await fetch("/api/agents")
    if (res.ok) {
      const data: Agent[] = await res.json()
      setAgents(data)
      if (selectedAgentId && !data.some((a) => a.id === selectedAgentId)) {
        // Stored agent no longer exists — clear stale selection
        setSelectedAgentId(data.length > 0 ? data[0].id : null)
      } else if (!selectedAgentId && data.length > 0) {
        setSelectedAgentId(data[0].id)
      }
    }
  }, [selectedAgentId])

  useEffect(() => {
    fetchAgents()
  }, [fetchAgents])

  const openCreateDialog = async () => {
    const [templatesRes, slackRes, githubRes] = await Promise.all([
      fetch("/api/templates"),
      fetch("/api/slack/config"),
      fetch("/api/github/config"),
    ])
    if (templatesRes.ok) {
      setTemplates(await templatesRes.json())
    }
    if (slackRes.ok) {
      const data = await slackRes.json()
      setSlackConfigured(data.configured)
    }
    if (githubRes.ok) {
      const data = await githubRes.json()
      setGithubConfigured(data.configured)
    }
    setNewAgentName("")
    setNewAgentType("default")
    setNewSlackEnabled(false)
    setNewGitHubEnabled(false)
    setShowCreateDialog(true)
  }

  const handleCreateAgent = async () => {
    if (!newAgentName.trim()) return

    const res = await fetch("/api/agents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newAgentName.trim(), agent_type: newAgentType, slack_enabled: newSlackEnabled, github_enabled: newGitHubEnabled }),
    })
    if (res.ok) {
      const agent: Agent = await res.json()
      setAgents((prev) => [...prev, agent])
      setSelectedAgentId(agent.id)
      setShowCreateDialog(false)
    }
  }

  const handleSelectAgentFromView = (id: string) => {
    setSelectedAgentId(id)
    navigate("/")
  }

  const handleDeleteAgent = async (id: string) => {
    const res = await fetch(`/api/agents/${id}`, { method: "DELETE" })
    if (res.ok) {
      setAgents((prev) => prev.filter((a) => a.id !== id))
      if (selectedAgentId === id) {
        const remaining = agents.filter((a) => a.id !== id)
        setSelectedAgentId(remaining.length > 0 ? remaining[0].id : null)
      }
      navigate("/agents")
    }
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
            <NavLink to="/schedules" match={currentPath === "/schedules"}>
              Schedules
            </NavLink>
            <NavLink to="/containers" match={currentPath === "/containers"}>
              Containers
            </NavLink>
            <NavLink to="/queue" match={currentPath === "/queue"}>
              Queue Status
            </NavLink>
            <NavLink to="/settings" match={currentPath === "/settings"}>
              Settings
            </NavLink>
            <NavLink to="/slack" match={currentPath === "/slack"}>
              Slack
            </NavLink>
            <NavLink to="/github" match={currentPath === "/github"}>
              GitHub
            </NavLink>
          </div>
          <div className="mt-auto flex flex-col gap-2 px-3 py-4">
            {agents.length > 0 && (
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
                </SelectContent>
              </Select>
            )}
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              onClick={openCreateDialog}
            >
              <Plus className="mr-1.5 size-3.5" />
              Create Agent
            </Button>
          </div>
        </nav>

        <main className="flex flex-1 flex-col">
          <Routes>
            <Route
              path="/"
              element={
                !selectedAgentId ? (
                  <div className="flex flex-1 items-center justify-center text-muted-foreground">
                    <p className="text-sm">Select an agent or create one to get started.</p>
                  </div>
                ) : (
                  <>
                    <div className="flex items-center justify-end border-b px-4 py-1.5">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-xs text-muted-foreground"
                        disabled={!connected || !!sessionEnded}
                        onClick={() => sendSystemCommand("clear_context")}
                      >
                        <Eraser className="mr-1.5 size-3.5" />
                        Clear Context
                      </Button>
                    </div>
                    <ChatMessageList messages={messages} hasOlderMessages={hasOlderMessages} loadingOlder={loadingOlder} onLoadOlder={loadOlderMessages} />
                    {(queueStatus.queued > 0 || queueStatus.in_flight > 0) &&
                      !messages.some((m) => m.status === "streaming") && (
                        <div className="flex items-center gap-2 border-t px-4 py-2 text-xs text-muted-foreground">
                          <span className="inline-block size-2 animate-pulse rounded-full bg-primary" />
                          Processing...
                        </div>
                      )}
                    <ErrorNotification error={error} />
                    <SystemErrorNotification error={systemError} />
                    <SessionEndedBanner reason={sessionEnded} onReconnect={reconnect} />
                    {messages.some((m) => m.status === "streaming") && (
                      <div className="flex items-center gap-2 border-t px-4 py-1.5 text-xs text-muted-foreground">
                        <span className="inline-block size-2 animate-pulse rounded-full bg-primary" />
                        {agents.find((a) => a.id === selectedAgentId)?.name ?? "Agent"} is typing...
                      </div>
                    )}
                    <ChatInput onSend={sendMessage} disabled={!connected || !!sessionEnded} sessionEnded={sessionEnded} />
                  </>
                )
              }
            />
            <Route
              path="/agents"
              element={
                <AgentsView
                  agents={agents}
                  onSelectAgent={handleSelectAgentFromView}
                  onDeleteAgent={handleDeleteAgent}
                />
              }
            />
            <Route
              path="/agents/:agentId"
              element={
                <AgentsView
                  agents={agents}
                  onSelectAgent={handleSelectAgentFromView}
                  onDeleteAgent={handleDeleteAgent}
                />
              }
            />
            <Route
              path="/agents/:agentId/:file"
              element={
                <AgentsView
                  agents={agents}
                  onSelectAgent={handleSelectAgentFromView}
                  onDeleteAgent={handleDeleteAgent}
                />
              }
            />
            <Route
              path="/schedules"
              element={<SchedulesView />}
            />
            <Route
              path="/containers"
              element={<ContainersView />}
            />
            <Route
              path="/queue"
              element={
                <QueueStatusPanel status={queueStatus} connected={connected} />
              }
            />
            <Route path="/settings" element={<SettingsView />} />
            <Route path="/slack" element={<SlackView />} />
            <Route path="/github" element={<GitHubView />} />
          </Routes>
        </main>

        <aside className="w-52 shrink-0 border-l" />
      </div>

      {showCreateDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-96 rounded-lg border bg-background p-6 shadow-lg">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-medium">Create Agent</h2>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => setShowCreateDialog(false)}
              >
                <X className="size-4" />
              </Button>
            </div>
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="agent-name" className="text-sm">Name</Label>
                <Input
                  id="agent-name"
                  value={newAgentName}
                  onChange={(e) => setNewAgentName(e.target.value)}
                  placeholder="My Agent"
                  autoFocus
                  onKeyDown={(e) => e.key === "Enter" && handleCreateAgent()}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="agent-type" className="text-sm">Type</Label>
                <Select value={newAgentType} onValueChange={setNewAgentType}>
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {templates.map((t) => (
                      <SelectItem key={t.id} value={t.id}>
                        {t.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="slack-enabled"
                  checked={newSlackEnabled}
                  onChange={(e) => setNewSlackEnabled(e.target.checked)}
                  disabled={!slackConfigured}
                  className="size-4 rounded border"
                />
                <Label
                  htmlFor="slack-enabled"
                  className={`text-sm ${!slackConfigured ? "text-muted-foreground" : ""}`}
                  title={!slackConfigured ? "Configure Slack credentials in the Slack tab first" : ""}
                >
                  Enable Slack integration
                </Label>
                {!slackConfigured && (
                  <span className="text-xs text-muted-foreground">(not configured)</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="github-enabled"
                  checked={newGitHubEnabled}
                  onChange={(e) => setNewGitHubEnabled(e.target.checked)}
                  disabled={!githubConfigured}
                  className="size-4 rounded border"
                />
                <Label
                  htmlFor="github-enabled"
                  className={`text-sm ${!githubConfigured ? "text-muted-foreground" : ""}`}
                  title={!githubConfigured ? "Configure GitHub token in the GitHub tab first" : ""}
                >
                  Enable GitHub integration
                </Label>
                {!githubConfigured && (
                  <span className="text-xs text-muted-foreground">(not configured)</span>
                )}
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowCreateDialog(false)}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={handleCreateAgent}
                  disabled={!newAgentName.trim()}
                >
                  Create
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
