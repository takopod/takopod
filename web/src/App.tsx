import { useCallback, useEffect, useState } from "react"
import { Route, Routes, useLocation, useMatch, useNavigate } from "react-router-dom"
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
import { SearchIndexView } from "@/components/search-index-view"
import { ChatMessageList } from "@/components/chat-message-list"
import { ErrorNotification, SessionEndedBanner, SystemErrorNotification } from "@/components/error-notification"
import { ContainerStatusPanel } from "@/components/container-status-panel"
import { McpStatusPanel } from "@/components/mcp-status-panel"
import { SkillsStatusPanel } from "@/components/skills-status-panel"
import { QueueStatusPanel } from "@/components/queue-status-panel"
import { Button } from "@/components/ui/button"
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

function agentUrl(name: string): string {
  return `/a/${encodeURIComponent(name)}`
}

export function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const isAgentRoute = location.pathname.startsWith("/a/") || location.pathname.startsWith("/agents")
  const [agents, setAgents] = useState<Agent[]>([])
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [newAgentName, setNewAgentName] = useState("")

  const chatMatch = useMatch("/a/:agentName")
  const selectedAgent = chatMatch
    ? agents.find((a) => a.name.toLowerCase() === chatMatch.params.agentName!.toLowerCase())
    : null
  const selectedAgentId = selectedAgent?.id ?? null

  useEffect(() => {
    if (selectedAgent) {
      localStorage.setItem("takopod:lastAgent", selectedAgent.name)
    }
  }, [selectedAgent])

  const { messages, queueStatus, error, systemError, connected, sessionEnded, sendMessage, sendSystemCommand, sendApprovalResponse, reconnect, hasOlderMessages, loadingOlder, loadOlderMessages } =
    useWebSocket(selectedAgentId)

  const fetchAgents = useCallback(async () => {
    const res = await fetch("/api/agents")
    if (res.ok) {
      setAgents(await res.json())
    }
  }, [])

  useEffect(() => {
    fetchAgents()
  }, [fetchAgents])

  useEffect(() => {
    if (agents.length === 0) return
    if (location.pathname === "/") {
      const lastName = localStorage.getItem("takopod:lastAgent")
      const target = agents.find((a) => a.name === lastName) ?? agents[0]
      if (target) navigate(agentUrl(target.name), { replace: true })
    } else if (chatMatch && !selectedAgent) {
      const lastName = localStorage.getItem("takopod:lastAgent")
      const target = agents.find((a) => a.name === lastName) ?? agents[0]
      navigate(target ? agentUrl(target.name) : "/", { replace: true })
    }
  }, [agents, location.pathname, chatMatch, selectedAgent, navigate])

  const openCreateDialog = () => {
    setNewAgentName("")
    setShowCreateDialog(true)
  }

  const handleCreateAgent = async () => {
    if (!newAgentName.trim()) return

    const res = await fetch("/api/agents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newAgentName.trim() }),
    })
    if (res.ok) {
      const agent: Agent = await res.json()
      setAgents((prev) => [agent, ...prev])
      setShowCreateDialog(false)
      navigate(agentUrl(agent.name))
    }
  }

  const handleSelectAgentFromView = (id: string) => {
    const agent = agents.find((a) => a.id === id)
    if (agent) navigate(agentUrl(agent.name))
  }

  const handleDeleteAgent = async (id: string, deleteWorkDir?: boolean) => {
    const url = deleteWorkDir ? `/api/agents/${id}?delete_work_dir=true` : `/api/agents/${id}`
    const res = await fetch(url, { method: "DELETE" })
    if (res.ok) {
      const remaining = agents.filter((a) => a.id !== id)
      setAgents(remaining)
      if (selectedAgentId === id) {
        if (remaining.length > 0) {
          navigate(agentUrl(remaining[0].name))
        } else {
          navigate("/")
        }
      } else {
        navigate("/agents")
      }
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
            const agent = agents.find((a) => a.id === value)
            if (agent) navigate(agentUrl(agent.name))
          }
        }}
      />

      <SidebarInset>
        <Routes>
            <Route
              path="/"
              element={
                <div className="flex flex-1 items-center justify-center text-muted-foreground">
                  <p className="text-sm">Select an agent or create one to get started.</p>
                </div>
              }
            />
            <Route
              path="/a/:agentName"
              element={
                !selectedAgentId ? (
                  <div className="flex flex-1 items-center justify-center text-muted-foreground">
                    <p className="text-sm">Loading...</p>
                  </div>
                ) : (
                  <>
                    <div className="sticky top-0 z-10 flex items-center gap-2 border-b bg-background px-4 py-1.5">
                      <SidebarTrigger className="-ml-1" />
                      <Separator orientation="vertical" className="mr-1 data-[orientation=vertical]:h-4" />
                      <span className="text-sm font-medium truncate flex items-center gap-1.5">
                        <AgentIcon name={selectedAgent?.icon ?? ""} className="size-4" />
                        {selectedAgent?.name}
                      </span>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon-sm">
                            <MoreHorizontal className="size-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start">
                          <DropdownMenuCheckboxItem checked={true} onClick={() => navigate(agentUrl(selectedAgent!.name))}>
                            <MessageSquare className="mr-2 size-3.5" />
                            Chat
                          </DropdownMenuCheckboxItem>
                          <DropdownMenuCheckboxItem checked={false} onClick={() => navigate(`/agents/${selectedAgent!.name}`)} className="whitespace-nowrap">
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
                    <ChatMessageList messages={messages} hasOlderMessages={hasOlderMessages} loadingOlder={loadingOlder} onLoadOlder={loadOlderMessages} onApprovalRespond={sendApprovalResponse} />
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
                        {selectedAgent?.name ?? "Agent"} is typing...
                      </div>
                    )}
                    <ChatInput onSend={sendMessage} disabled={!connected || !!sessionEnded} sessionEnded={sessionEnded} agentId={selectedAgentId} />
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
              path="/agents/:agentName/skills/*"
              element={
                <AgentsView
                  agents={agents}
                  onSelectAgent={handleSelectAgentFromView}
                  onDeleteAgent={handleDeleteAgent}
                />
              }
            />
            <Route
              path="/agents/:agentName/files/*"
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
            <Route path="/settings/search-index" element={<SearchIndexView />} />
          </Routes>
      </SidebarInset>

      <aside className="w-52 shrink-0 border-l sticky top-0 h-svh overflow-y-auto">
        {selectedAgentId && isAgentRoute && (
          <>
            <SkillsStatusPanel agentId={selectedAgentId} agentName={agents.find((a) => a.id === selectedAgentId)?.name} />
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
