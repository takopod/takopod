import { useCallback, useEffect, useState } from "react"
import { Route, Routes, useNavigate } from "react-router-dom"
import { AgentsView } from "@/components/agents-view"
import { AppSidebar } from "@/components/app-sidebar"
import { ChatInput } from "@/components/chat-input"
import { ContainerLogsView } from "@/components/container-logs-view"
import { ContainersView } from "@/components/containers-view"
import { SchedulesView } from "@/components/schedules-view"
import { SystemSkillsView } from "@/components/system-skills-view"
import { SystemMcpView } from "@/components/system-mcp-view"
import { SettingsView } from "@/components/settings-view"
import { SlackView } from "@/components/slack-view"
import { GitHubView } from "@/components/github-view"
import { SearchIndexView } from "@/components/search-index-view"
import { ChatMessageList } from "@/components/chat-message-list"
import { ErrorNotification, SessionEndedBanner, SystemErrorNotification } from "@/components/error-notification"
import { ContainerStatusPanel } from "@/components/container-status-panel"
import { McpStatusPanel } from "@/components/mcp-status-panel"
import { SkillsStatusPanel } from "@/components/skills-status-panel"
import { QueueStatusPanel } from "@/components/queue-status-panel"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"
import { useWebSocket } from "@/hooks/use-websocket"
import type { Agent } from "@/lib/types"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Eraser,
  MessageSquare,
  MoreHorizontal,
  Settings,
  X,
} from "lucide-react"
import { AgentIcon } from "@/components/agent-icon"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Separator } from "@/components/ui/separator"

interface Template {
  id: string
  name: string
}

export function App() {
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
      setAgents((prev) => [agent, ...prev])
      setSelectedAgentId(agent.id)
      setShowCreateDialog(false)
      navigate("/")
    }
  }

  const handleSelectAgentFromView = (id: string) => {
    setSelectedAgentId(id)
    navigate("/")
  }

  const handleDeleteAgent = async (id: string, deleteWorkDir?: boolean) => {
    const url = deleteWorkDir ? `/api/agents/${id}?delete_work_dir=true` : `/api/agents/${id}`
    const res = await fetch(url, { method: "DELETE" })
    if (res.ok) {
      setAgents((prev) => prev.filter((a) => a.id !== id))
      if (selectedAgentId === id) {
        const remaining = agents.filter((a) => a.id !== id)
        setSelectedAgentId(remaining.length > 0 ? remaining[0].id : null)
      }
      navigate("/agents")
    }
  }

  return (
    <SidebarProvider>
      <AppSidebar
        agents={agents}
        selectedAgentId={selectedAgentId}
        onAgentChange={(value) => {
          if (value === "__create__") {
            openCreateDialog()
          } else {
            setSelectedAgentId(value)
            navigate("/")
          }
        }}
      />

      <SidebarInset>
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
                    <div className="sticky top-0 z-10 flex items-center gap-2 border-b bg-background px-4 py-1.5">
                      <SidebarTrigger className="-ml-1" />
                      <Separator orientation="vertical" className="mr-1 data-[orientation=vertical]:h-4" />
                      <span className="text-sm font-medium truncate flex items-center gap-1.5">
                        <AgentIcon name={agents.find((a) => a.id === selectedAgentId)?.icon ?? ""} className="size-4" />
                        {agents.find((a) => a.id === selectedAgentId)?.name}
                      </span>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon-sm">
                            <MoreHorizontal className="size-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start">
                          <DropdownMenuCheckboxItem checked={true} onClick={() => navigate("/")}>
                            <MessageSquare className="mr-2 size-3.5" />
                            Chat
                          </DropdownMenuCheckboxItem>
                          <DropdownMenuCheckboxItem checked={false} onClick={() => navigate(`/agents/${agents.find((a) => a.id === selectedAgentId)?.name ?? selectedAgentId}`)} className="whitespace-nowrap">
                            <Settings className="mr-2 size-3.5" />
                            Agent Settings
                          </DropdownMenuCheckboxItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                      <div className="ml-auto">
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
                    {(queueStatus.in_flight > 0 || queueStatus.queued > 0) &&
                      messages.some((m) => m.status === "streaming") && (
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
              path="/agents/:agentName"
              element={
                <AgentsView
                  agents={agents}
                  onSelectAgent={handleSelectAgentFromView}
                  onDeleteAgent={handleDeleteAgent}
                />
              }
            />
            <Route
              path="/agents/:agentName/:file"
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
            <Route path="/skills" element={<SystemSkillsView />} />
            <Route path="/mcp" element={<SystemMcpView />} />
            <Route
              path="/settings/containers"
              element={<ContainersView />}
            />
            <Route
              path="/settings/containers/:containerName/logs"
              element={<ContainerLogsView />}
            />
            <Route
              path="/settings/queue"
              element={
                <QueueStatusPanel status={queueStatus} connected={connected} />
              }
            />
            <Route path="/settings" element={<SettingsView />} />
            <Route path="/settings/slack" element={<SlackView />} />
            <Route path="/settings/github" element={<GitHubView />} />
            <Route path="/settings/search-index" element={<SearchIndexView />} />
          </Routes>
      </SidebarInset>

      <aside className="w-52 shrink-0 border-l sticky top-0 h-svh overflow-y-auto">
        {selectedAgentId && (
          <>
            <SkillsStatusPanel agentId={selectedAgentId} />
            <McpStatusPanel agentId={selectedAgentId} />
            <ContainerStatusPanel agentId={selectedAgentId} />
          </>
        )}
      </aside>

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
                  title={!slackConfigured ? "Configure Slack credentials in Settings first" : ""}
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
                  title={!githubConfigured ? "Configure GitHub token in Settings first" : ""}
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
    </SidebarProvider>
  )
}

export default App
