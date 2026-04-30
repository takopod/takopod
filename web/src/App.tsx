import { useCallback, useEffect, useRef, useState } from "react"
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
import { FileBrowserPanel } from "@/components/file-browser-panel"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"
import { useWebSocket } from "@/hooks/use-websocket"
import type { Agent, ModelOption } from "@/lib/types"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Eraser,
  MessageSquare,
  MoreHorizontal,
  Settings,
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

function agentSettingsUrl(name: string): string {
  return `/a/${encodeURIComponent(name)}/settings`
}

export function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const isAgentRoute = location.pathname.startsWith("/a/")
  const [agents, setAgents] = useState<Agent[]>([])
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [newAgentName, setNewAgentName] = useState("")
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([])
  const [selectedModel, setSelectedModel] = useState("")
  const [rightPanelWidth, setRightPanelWidth] = useState(() => {
    const saved = localStorage.getItem("takopod:rightPanelWidth")
    return saved ? Number(saved) : 208
  })
  const resizingRef = useRef(false)
  const startWidthRef = useRef(rightPanelWidth)

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

  const { messages, queueStatus, error, systemError, connected, sessionEnded, sendMessage, sendSystemCommand, sendApprovalResponse, stopQuery, reconnect, hasOlderMessages, loadingOlder, loadOlderMessages } =
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
    fetch("/api/models").then(r => r.ok ? r.json() : []).then(setModelOptions)
  }, [])

  useEffect(() => {
    if (modelOptions.length === 0) return
    const agentKey = selectedAgentId ? `takopod:model:${selectedAgentId}` : null
    const saved = agentKey && localStorage.getItem(agentKey)
    const fallback = localStorage.getItem("takopod:selectedModel")
    const pick = saved || fallback
    const valid = modelOptions.find(m => m.value === pick)
    setSelectedModel(valid?.value ?? modelOptions[0].value)
  }, [modelOptions, selectedAgentId])

  const handleModelChange = useCallback((v: string) => {
    setSelectedModel(v)
    if (selectedAgentId) {
      localStorage.setItem(`takopod:model:${selectedAgentId}`, v)
    }
  }, [selectedAgentId])

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

  const startResize = useCallback((e: React.MouseEvent) => {
    if (resizingRef.current) return
    e.preventDefault()
    resizingRef.current = true
    const startX = e.clientX
    startWidthRef.current = rightPanelWidth

    const onMouseMove = (ev: MouseEvent) => {
      const delta = startX - ev.clientX
      const newWidth = Math.min(Math.max(startWidthRef.current + delta, 120), 480)
      setRightPanelWidth(newWidth)
    }

    const onMouseUp = () => {
      resizingRef.current = false
      document.removeEventListener("mousemove", onMouseMove)
      document.removeEventListener("mouseup", onMouseUp)
      document.body.style.cursor = ""
      document.body.style.userSelect = ""
      setRightPanelWidth((w) => {
        localStorage.setItem("takopod:rightPanelWidth", String(w))
        return w
      })
    }

    document.body.style.cursor = "col-resize"
    document.body.style.userSelect = "none"
    document.addEventListener("mousemove", onMouseMove)
    document.addEventListener("mouseup", onMouseUp)
  }, [rightPanelWidth])

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
        navigate("/")
      }
    }
  }

  return (
    <SidebarProvider className="h-svh overflow-hidden">
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
                  <div className="flex flex-1 flex-col min-h-0">
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
                          <DropdownMenuCheckboxItem checked={false} onClick={() => navigate(agentSettingsUrl(selectedAgent!.name))} className="whitespace-nowrap">
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
                    <ChatInput onSend={(content, attachments) => sendMessage(content, attachments, selectedModel || undefined)} onStop={stopQuery} isStreaming={messages.some((m) => m.status === "streaming")} disabled={!connected || !!sessionEnded} sessionEnded={sessionEnded} agentId={selectedAgentId} modelOptions={modelOptions} selectedModel={selectedModel} onModelChange={handleModelChange} />
                  </div>
                )
              }
            />
            <Route
              path="/a/:agentName/settings"
              element={
                <AgentsView
                  agents={agents}
                  onSelectAgent={handleSelectAgentFromView}
                  onDeleteAgent={handleDeleteAgent}
                />
              }
            />
            <Route
              path="/a/:agentName/settings/skills/*"
              element={
                <AgentsView
                  agents={agents}
                  onSelectAgent={handleSelectAgentFromView}
                  onDeleteAgent={handleDeleteAgent}
                />
              }
            />
            <Route
              path="/a/:agentName/settings/files/*"
              element={
                <AgentsView
                  agents={agents}
                  onSelectAgent={handleSelectAgentFromView}
                  onDeleteAgent={handleDeleteAgent}
                />
              }
            />
            <Route
              path="/a/:agentName/settings/:file"
              element={
                <AgentsView
                  agents={agents}
                  onSelectAgent={handleSelectAgentFromView}
                  onDeleteAgent={handleDeleteAgent}
                />
              }
            />
            <Route path="/settings" element={<SettingsView />} />
            <Route path="/settings/slack" element={<SlackView />} />
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
            <Route path="/settings/search-index" element={<SearchIndexView />} />
            <Route path="/skills" element={<SystemSkillsView />} />
            <Route path="/mcp" element={<SystemMcpView />} />
            <Route path="/schedules" element={<SchedulesView />} />
          </Routes>
      </SidebarInset>

      <aside
        className="shrink-0 sticky top-0 h-svh overflow-y-auto flex"
        style={{ width: rightPanelWidth }}
      >
        <div
          className="w-1 shrink-0 cursor-col-resize border-l hover:bg-primary/20 active:bg-primary/30 transition-colors"
          onMouseDown={startResize}
        />
        <div className="flex-1 min-w-0 overflow-y-auto">
          {selectedAgentId && isAgentRoute && (
            <>
              <SkillsStatusPanel agentId={selectedAgentId} agentName={agents.find((a) => a.id === selectedAgentId)?.name} />
              <McpStatusPanel agentId={selectedAgentId} />
              <ContainerStatusPanel agentId={selectedAgentId} />
              <div className="border-t" />
              <FileBrowserPanel agentId={selectedAgentId} agentName={selectedAgent?.name ?? ""} />
            </>
          )}
        </div>
      </aside>

      <Dialog open={showCreateDialog} onOpenChange={(open) => { if (!open) setShowCreateDialog(false) }}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Create Agent</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="agent-name" className="text-xs">Name</Label>
            <Input
              id="agent-name"
              value={newAgentName}
              onChange={(e) => setNewAgentName(e.target.value)}
              placeholder="My Agent"
              autoFocus
              onKeyDown={(e) => e.key === "Enter" && handleCreateAgent()}
            />
          </div>
          <DialogFooter>
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
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </SidebarProvider>
  )
}

export default App
