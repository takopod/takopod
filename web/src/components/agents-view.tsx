import { useCallback, useEffect, useState } from "react"
import { Link, useLocation, useNavigate, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardHeader, CardTitle, CardDescription, CardAction } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { FileBrowser } from "@/components/file-browser"
import { FileEditor } from "@/components/file-editor"
import { SkillsPanel } from "@/components/skills-panel"
import type { Agent } from "@/lib/types"
import { Input } from "@/components/ui/input"
import {
  ArrowLeft,
  Check,
  ChevronRight,
  Cpu,
  FolderOpen,
  HardDrive,
  MessageSquare,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  Server,
  Settings,
  Sparkles,
  Terminal,
  Trash2,
  X,
} from "lucide-react"
import { AgentIcon } from "@/components/agent-icon"

interface AgentDetail extends Agent {}

const IDENTITY_FILES = [
  { file: "CLAUDE.md", description: "System prompt & instructions" },
  { file: "SOUL.md", description: "Personality & behavior" },
  { file: "MEMORY.md", description: "Persistent memory store" },
]

interface McpServer {
  id: string
  name: string
  enabled?: boolean
  builtin?: boolean
  transport?: "stdio" | "http"
  command?: string
  args?: string[]
  url?: string
  auth?: "none" | "basic" | "oauth"
}

function McpServerLabel({ srv }: { srv: McpServer }) {
  return (
    <>
      <span className="text-sm font-medium">{srv.name}</span>
      <code className="text-xs text-muted-foreground">
        {srv.transport === "http"
          ? `HTTP: ${srv.url}`
          : `${srv.command || ""} ${(srv.args || []).join(" ")}`}
      </code>
    </>
  )
}

function McpConfigPanel({ agentId, agentName }: { agentId: string; agentName?: string }) {
  const navigate = useNavigate()
  const [servers, setServers] = useState<McpServer[]>([])
  const [available, setAvailable] = useState<McpServer[]>([])
  const [availableLoaded, setAvailableLoaded] = useState(false)
  const [loading, setLoading] = useState(true)
  const [toggling, setToggling] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const [searchFocused, setSearchFocused] = useState(false)
  const [oauthStatus, setOauthStatus] = useState<Record<string, boolean>>({})

  const fetchServers = useCallback(async () => {
    const res = await fetch(`/api/agents/${agentId}/mcp`)
    if (res.ok) {
      const data = await res.json()
      const srvList: McpServer[] = (data.servers || []).sort(
        (a: McpServer, b: McpServer) => (b.builtin ? 1 : 0) - (a.builtin ? 1 : 0),
      )
      setServers(srvList)
      const statuses: Record<string, boolean> = {}
      await Promise.all(
        srvList
          .filter((s) => s.auth === "oauth")
          .map(async (s) => {
            try {
              const r = await fetch(`/oauth/status/${s.name}`)
              if (r.ok) {
                const st = await r.json()
                statuses[s.name] = st.authorized
              }
            } catch {
              // ignore
            }
          }),
      )
      setOauthStatus(statuses)
    }
    setLoading(false)
  }, [agentId])

  const fetchAvailable = useCallback(async () => {
    if (availableLoaded) return
    const res = await fetch(`/api/agents/${agentId}/mcp`)
    if (res.ok) {
      const data = await res.json()
      setAvailable(data.available || [])
    }
    setAvailableLoaded(true)
  }, [agentId, availableLoaded])

  useEffect(() => {
    fetchServers()
  }, [fetchServers])

  const handleToggle = async (id: string, enabled: boolean) => {
    setToggling(id)
    const res = await fetch(`/api/agents/${agentId}/mcp/servers/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    })
    if (res.ok) {
      setServers((prev) =>
        prev.map((s) => (s.id === id ? { ...s, enabled } : s)),
      )
    }
    setToggling(null)
  }

  const handleAdd = async (id: string) => {
    const res = await fetch(`/api/agents/${agentId}/mcp/servers/${id}`, {
      method: "POST",
    })
    if (res.ok) {
      setSearch("")
      setAvailableLoaded(false)
      setAvailable([])
      await fetchServers()
    }
  }

  const handleRemove = async (id: string) => {
    const res = await fetch(`/api/agents/${agentId}/mcp/servers/${id}`, {
      method: "DELETE",
    })
    if (res.ok) {
      setAvailableLoaded(false)
      setAvailable([])
      await fetchServers()
    }
  }

  const filtered = available
    .filter((s) => s.name.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => (b.builtin ? 1 : 0) - (a.builtin ? 1 : 0))
    .slice(0, 5)

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center gap-3 border-b px-4 py-2">
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => navigate(`/agents/${agentName}`)}
        >
          <ArrowLeft className="size-4" />
        </Button>
        <span className="text-sm font-medium">MCP Servers</span>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : (
          <div className="flex flex-col gap-4">
            {/* Search & add section */}
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onFocus={() => {
                  setSearchFocused(true)
                  fetchAvailable()
                }}
                onBlur={() => {
                  setTimeout(() => setSearchFocused(false), 150)
                }}
                placeholder="Search available MCP servers..."
                className="pl-8"
              />
              {searchFocused && availableLoaded && (
                <div className="absolute left-0 right-0 top-full z-50 mt-1 flex flex-col rounded-md border bg-popover shadow-md">
                  {filtered.length === 0 ? (
                    <p className="px-3 py-2 text-xs text-muted-foreground">
                      {available.length === 0
                        ? <>No servers available. Configure them in the global{" "}
                            <Link to="/mcp" className="underline">MCP Servers</Link>{" "}
                            settings.</>
                        : "No matching servers."}
                    </p>
                  ) : (
                    filtered.map((srv, i) => (
                      <div
                        key={srv.name}
                        className={`flex items-center gap-3 px-3 py-2 ${
                          i > 0 ? "border-t" : ""
                        }`}
                      >
                        <div className="flex flex-1 flex-col gap-0.5">
                          <McpServerLabel srv={srv} />
                        </div>
                        {srv.builtin && (
                          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                            BUILTIN
                          </span>
                        )}
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          onClick={() => handleAdd(srv.id)}
                        >
                          <Plus className="size-3.5" />
                        </Button>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>

            <Separator />

            {/* Added servers */}
            {servers.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No MCP servers added to this agent yet.
              </p>
            ) : (
              <div className="flex flex-col gap-3">
                {servers.map((srv) => (
                  <div
                    key={srv.name}
                    className="flex items-center gap-3 rounded-md border px-4 py-2.5"
                  >
                    <button
                      type="button"
                      className={`relative inline-flex h-5 w-9 shrink-0 rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                        srv.enabled ? "bg-primary" : "bg-input"
                      } ${toggling === srv.id ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
                      disabled={toggling === srv.id}
                      onClick={() => handleToggle(srv.id, !srv.enabled)}
                    >
                      <span
                        className={`pointer-events-none block size-4 rounded-full bg-background shadow-lg ring-0 transition-transform ${
                          srv.enabled ? "translate-x-4" : "translate-x-0"
                        }`}
                      />
                    </button>
                    <div className="flex flex-1 flex-col gap-0.5">
                      <McpServerLabel srv={srv} />
                      {srv.auth === "oauth" && (
                        <span
                          className={`text-xs ${oauthStatus[srv.name] ? "text-green-500" : "text-yellow-500"}`}
                        >
                          {oauthStatus[srv.name]
                            ? "Authorized"
                            : "Not authorized"}
                        </span>
                      )}
                    </div>
                    {srv.builtin ? (
                      <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                        BUILTIN
                      </span>
                    ) : (
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => handleRemove(srv.id)}
                      >
                        <X className="size-3.5" />
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            )}

            <p className="text-xs text-muted-foreground">
              Changes take effect after stopping and restarting the worker.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

interface ExternalTool {
  id: string
  name: string
  builtin: boolean
  enabled: boolean
  config_summary?: Record<string, string>
}

interface AvailableExternalTool {
  id: string
  name: string
  builtin: boolean
  config_summary?: Record<string, string>
}

function ExternalToolsConfigPanel({ agentId, agentName }: { agentId: string; agentName?: string }) {
  const navigate = useNavigate()
  const [tools, setTools] = useState<ExternalTool[]>([])
  const [available, setAvailable] = useState<AvailableExternalTool[]>([])
  const [availableLoaded, setAvailableLoaded] = useState(false)
  const [loading, setLoading] = useState(true)
  const [toggling, setToggling] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const [searchFocused, setSearchFocused] = useState(false)

  const fetchTools = useCallback(async () => {
    const res = await fetch(`/api/agents/${agentId}/external-tools`)
    if (res.ok) {
      const data = await res.json()
      setTools(data.tools || [])
      if (!availableLoaded) {
        setAvailable(data.available || [])
        setAvailableLoaded(true)
      }
    }
    setLoading(false)
  }, [agentId, availableLoaded])

  const fetchAvailable = useCallback(async () => {
    if (availableLoaded) return
    const res = await fetch(`/api/agents/${agentId}/external-tools`)
    if (res.ok) {
      const data = await res.json()
      setAvailable(data.available || [])
    }
    setAvailableLoaded(true)
  }, [agentId, availableLoaded])

  useEffect(() => {
    fetchTools()
  }, [fetchTools])

  const handleToggle = async (id: string, enabled: boolean) => {
    setToggling(id)
    const res = await fetch(`/api/agents/${agentId}/external-tools/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    })
    if (res.ok) {
      setTools((prev) =>
        prev.map((t) => (t.id === id ? { ...t, enabled } : t)),
      )
    }
    setToggling(null)
  }

  const handleAdd = async (id: string) => {
    const res = await fetch(`/api/agents/${agentId}/external-tools/${id}`, {
      method: "POST",
    })
    if (res.ok) {
      setSearch("")
      setAvailableLoaded(false)
      setAvailable([])
      await fetchTools()
    }
  }

  const handleRemove = async (id: string) => {
    const res = await fetch(`/api/agents/${agentId}/external-tools/${id}`, {
      method: "DELETE",
    })
    if (res.ok) {
      setAvailableLoaded(false)
      setAvailable([])
      await fetchTools()
    }
  }

  const filtered = available
    .filter((t) => t.name.toLowerCase().includes(search.toLowerCase()))
    .slice(0, 5)

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center gap-3 border-b px-4 py-2">
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => navigate(`/agents/${agentName}`)}
        >
          <ArrowLeft className="size-4" />
        </Button>
        <span className="text-sm font-medium">CLI Tools</span>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : (
          <div className="flex flex-col gap-4">
            {/* Search & add section */}
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onFocus={() => {
                  setSearchFocused(true)
                  fetchAvailable()
                }}
                onBlur={() => {
                  setTimeout(() => setSearchFocused(false), 150)
                }}
                placeholder="Search available tools..."
                className="pl-8"
              />
              {searchFocused && availableLoaded && (
                <div className="absolute left-0 right-0 top-full z-50 mt-1 flex flex-col rounded-md border bg-popover shadow-md">
                  {filtered.length === 0 ? (
                    <p className="px-3 py-2 text-xs text-muted-foreground">
                      No tools available to add.
                    </p>
                  ) : (
                    filtered.map((tool, i) => (
                      <div
                        key={tool.id}
                        className={`flex items-center gap-3 px-3 py-2 ${
                          i > 0 ? "border-t" : ""
                        }`}
                      >
                        <div className="flex flex-1 flex-col gap-0.5">
                          <span className="text-sm font-medium">{tool.name}</span>
                          {tool.config_summary && Object.keys(tool.config_summary).length > 0 && (
                            <span className="text-xs text-muted-foreground">
                              {Object.values(tool.config_summary).join(", ")}
                            </span>
                          )}
                        </div>
                        {tool.builtin && (
                          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                            BUILTIN
                          </span>
                        )}
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          onClick={() => handleAdd(tool.id)}
                        >
                          <Plus className="size-3.5" />
                        </Button>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>

            <Separator />

            {/* Added tools */}
            {tools.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No CLI tools added to this agent yet.
              </p>
            ) : (
              <div className="flex flex-col gap-3">
                {tools.map((tool) => (
                  <div
                    key={tool.id}
                    className="flex items-center gap-3 rounded-md border px-4 py-2.5"
                  >
                    <button
                      type="button"
                      className={`relative inline-flex h-5 w-9 shrink-0 rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                        tool.enabled ? "bg-primary" : "bg-input"
                      } ${toggling === tool.id ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
                      disabled={toggling === tool.id}
                      onClick={() => handleToggle(tool.id, !tool.enabled)}
                    >
                      <span
                        className={`pointer-events-none block size-4 rounded-full bg-background shadow-lg ring-0 transition-transform ${
                          tool.enabled ? "translate-x-4" : "translate-x-0"
                        }`}
                      />
                    </button>
                    <div className="flex flex-1 flex-col gap-0.5">
                      <span className="text-sm font-medium">{tool.name}</span>
                      {tool.config_summary && Object.keys(tool.config_summary).length > 0 && (
                        <span className="text-xs text-muted-foreground">
                          {Object.values(tool.config_summary).join(", ")}
                        </span>
                      )}
                    </div>
                    {tool.builtin ? (
                      <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                        BUILTIN
                      </span>
                    ) : (
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => handleRemove(tool.id)}
                      >
                        <X className="size-3.5" />
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            )}

            <p className="text-xs text-muted-foreground">
              Changes take effect after stopping and restarting the worker.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

function ContainerResourcesPanel({
  agentId,
  detail,
  onUpdate,
}: {
  agentId: string
  detail: AgentDetail
  onUpdate: (d: AgentDetail) => void
}) {
  const [memory, setMemory] = useState(detail.container_memory ?? "2g")
  const [cpus, setCpus] = useState(detail.container_cpus ?? "2")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    setMemory(detail.container_memory ?? "2g")
    setCpus(detail.container_cpus ?? "2")
  }, [detail.container_memory, detail.container_cpus])

  const dirty = memory !== (detail.container_memory ?? "2g") || cpus !== (detail.container_cpus ?? "2")

  const handleSave = async () => {
    setSaving(true)
    setError("")
    setSaved(false)
    try {
      const res = await fetch(`/api/agents/${agentId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ container_memory: memory, container_cpus: cpus }),
      })
      if (res.ok) {
        const data = await res.json()
        onUpdate(data)
        setSaved(true)
        setTimeout(() => setSaved(false), 2000)
      } else {
        const data = await res.json().catch(() => null)
        setError(data?.detail ?? "Failed to save")
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <h3 className="mb-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
        Container Settings
      </h3>
      <div className="rounded-md border px-4 py-4">
        <p className="text-xs text-muted-foreground mb-4">
          CPU and memory limits for this agent's container. Changes take effect on next container start.
        </p>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="mb-1.5 flex items-center gap-1.5 text-sm font-medium">
              <HardDrive className="size-3.5 text-muted-foreground" />
              Memory
            </label>
            <Input
              value={memory}
              onChange={(e) => { setMemory(e.target.value); setError(""); setSaved(false) }}
              placeholder="2g"
              className="h-8 text-sm"
            />
            <span className="text-[11px] text-muted-foreground">e.g. 512m, 1g, 4g</span>
          </div>
          <div>
            <label className="mb-1.5 flex items-center gap-1.5 text-sm font-medium">
              <Cpu className="size-3.5 text-muted-foreground" />
              CPUs
            </label>
            <Input
              value={cpus}
              onChange={(e) => { setCpus(e.target.value); setError(""); setSaved(false) }}
              placeholder="2"
              className="h-8 text-sm"
            />
            <span className="text-[11px] text-muted-foreground">e.g. 1, 2, 4</span>
          </div>
        </div>
        {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
        <div className="mt-3 flex items-center gap-2">
          <Button size="sm" onClick={handleSave} disabled={!dirty || saving}>
            {saving ? "Saving..." : "Save"}
          </Button>
          {saved && (
            <span className="flex items-center gap-1 text-xs text-green-600">
              <Check className="size-3" /> Saved
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

interface AgentsViewProps {
  agents: Agent[]
  onSelectAgent: (id: string) => void
  onDeleteAgent: (id: string, deleteWorkDir?: boolean) => void
}

export function AgentsView({ agents, onSelectAgent, onDeleteAgent }: AgentsViewProps) {
  const { agentName, file, "*": fileSplat } = useParams<{ agentName?: string; file?: string; "*"?: string }>()
  const agentId = agentName
    ? agents.find((a) => a.name === agentName)?.id
    : undefined
  const navigate = useNavigate()
  const [detail, setDetail] = useState<AgentDetail | null>(null)
  const [content, setContent] = useState("")
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)

  const location = useLocation()
  const pathAfterAgent = agentName ? location.pathname.split(`/agents/${agentName}/`)[1] ?? "" : ""
  // /agents/:name/files/* matched → file browser with optional deep path
  const showFileBrowser = file === "files" || (fileSplat !== undefined && !pathAfterAgent.startsWith("skills"))
  const showMcpConfig = file === "mcp"
  const showExternalTools = file === "external-tools"
  const showSkills = file === "skills" || pathAfterAgent.startsWith("skills")
  const skillsSplat = pathAfterAgent.startsWith("skills/") ? pathAfterAgent.slice("skills/".length) : undefined
  const openFile = !showFileBrowser && !showMcpConfig && !showExternalTools && !showSkills
    ? IDENTITY_FILES.find((f) => f.file === file)
    : null

  const fetchDetail = useCallback(async (id: string) => {
    const res = await fetch(`/api/agents/${id}`)
    if (res.ok) {
      const data: AgentDetail = await res.json()
      setDetail(data)
      return data
    }
    return null
  }, [])

  useEffect(() => {
    if (!agentId) {
      setDetail(null)
      return
    }
    fetchDetail(agentId)
  }, [agentId, fetchDetail])

  useEffect(() => {
    if (!agentId || !openFile) return
    fetch(`/api/agents/${agentId}/files/${openFile.file}`)
      .then((res) => (res.ok ? res.text() : ""))
      .then((text) => {
        setContent(text)
        setDirty(false)
      })
  }, [agentId, openFile])

  const handleSave = async () => {
    if (!agentId || !openFile) return
    setSaving(true)
    const res = await fetch(`/api/agents/${agentId}/files/${openFile.file}`, {
      method: "PUT",
      body: content,
    })
    if (res.ok) {
      setDirty(false)
    }
    setSaving(false)
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {!agentId || !detail ? (
        <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
          Select an agent to view and edit its files.
        </div>
      ) : showMcpConfig ? (
        <McpConfigPanel agentId={agentId} agentName={agentName} />
      ) : showExternalTools ? (
        <ExternalToolsConfigPanel agentId={agentId} agentName={agentName} />
      ) : showSkills ? (
        <SkillsPanel agentId={agentId} agentName={agentName} initialPath={skillsSplat} />
      ) : showFileBrowser ? (
        <FileBrowser agentId={agentId} agentName={agentName} initialPath={fileSplat} />
      ) : !openFile ? (
        <>
          <div className="sticky top-0 z-10 flex items-center gap-2 border-b bg-background px-4 py-1.5">
            <SidebarTrigger className="-ml-1" />
            <Separator orientation="vertical" className="mr-1 data-[orientation=vertical]:h-4" />
            <span className="text-sm font-medium truncate flex items-center gap-1.5">
              <AgentIcon name={detail.icon} className="size-4" />
              {detail.name}
            </span>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon-sm">
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                <DropdownMenuCheckboxItem checked={false} onClick={() => onSelectAgent(detail.id)}>
                  <MessageSquare className="mr-2 size-3.5" />
                  Chat
                </DropdownMenuCheckboxItem>
                <DropdownMenuCheckboxItem checked={true} className="whitespace-nowrap">
                  <Settings className="mr-2 size-3.5" />
                  Agent Settings
                </DropdownMenuCheckboxItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
          <div className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl space-y-6 p-6">
            {/* Configuration */}
            <div>
              <h3 className="mb-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Configuration
              </h3>
              <div className="rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>File</TableHead>
                      <TableHead>Description</TableHead>
                      <TableHead className="w-10" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {IDENTITY_FILES.map(({ file: f, description }) => (
                      <TableRow key={f}>
                        <TableCell className="font-medium">{f}</TableCell>
                        <TableCell className="text-muted-foreground">{description}</TableCell>
                        <TableCell className="text-right">
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button variant="ghost" size="icon" className="size-8">
                                <MoreHorizontal className="size-4" />
                                <span className="sr-only">Open menu</span>
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuItem onClick={() => navigate(`/agents/${agentName}/${f}`)}>
                                <Pencil className="mr-2 size-3.5" />
                                Edit
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>

            {/* Tools & Extensions */}
            <div>
              <h3 className="mb-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Tools & Extensions
              </h3>
              <div className="grid grid-cols-2 gap-4">
                <Link to={`/agents/${agentName}/mcp`} className="block">
                  <Card size="sm" className="h-full transition-colors hover:bg-muted/50">
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2">
                        <Server className="size-4 text-muted-foreground" />
                        MCP Servers
                      </CardTitle>
                      <CardDescription>External tool integrations</CardDescription>
                      <CardAction>
                        <ChevronRight className="size-4 text-muted-foreground" />
                      </CardAction>
                    </CardHeader>
                  </Card>
                </Link>

                <Link to={`/agents/${agentName}/skills`} className="block">
                  <Card size="sm" className="h-full transition-colors hover:bg-muted/50">
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2">
                        <Sparkles className="size-4 text-muted-foreground" />
                        Skills
                      </CardTitle>
                      <CardDescription>Agent capabilities</CardDescription>
                      <CardAction>
                        <ChevronRight className="size-4 text-muted-foreground" />
                      </CardAction>
                    </CardHeader>
                  </Card>
                </Link>

                <Link to={`/agents/${agentName}/external-tools`} className="block">
                  <Card size="sm" className="h-full transition-colors hover:bg-muted/50">
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2">
                        <Terminal className="size-4 text-muted-foreground" />
                        CLI Tools
                      </CardTitle>
                      <CardDescription>Container-side tool integrations</CardDescription>
                      <CardAction>
                        <ChevronRight className="size-4 text-muted-foreground" />
                      </CardAction>
                    </CardHeader>
                  </Card>
                </Link>
              </div>
            </div>

            {/* Files */}
            <div>
              <h3 className="mb-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Files
              </h3>
              <div className="grid grid-cols-2 gap-4">
                <Link to={`/agents/${agentName}/files?dir=memory`} className="block">
                  <Card size="sm" className="h-full transition-colors hover:bg-muted/50">
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2">
                        <FolderOpen className="size-4 text-muted-foreground" />
                        Memory Files
                      </CardTitle>
                      <CardDescription>Agent memory directory</CardDescription>
                      <CardAction>
                        <ChevronRight className="size-4 text-muted-foreground" />
                      </CardAction>
                    </CardHeader>
                  </Card>
                </Link>

                <Link to={`/agents/${agentName}/files`} className="block">
                  <Card size="sm" className="h-full transition-colors hover:bg-muted/50">
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2">
                        <FolderOpen className="size-4 text-muted-foreground" />
                        Workspace
                      </CardTitle>
                      <CardDescription>Browse all agent files</CardDescription>
                      <CardAction>
                        <ChevronRight className="size-4 text-muted-foreground" />
                      </CardAction>
                    </CardHeader>
                  </Card>
                </Link>
              </div>

            </div>

            {/* Container Settings */}
            <ContainerResourcesPanel agentId={agentId} detail={detail} onUpdate={setDetail} />

            {/* Danger Zone */}
            <Separator />
            <div>
              <h3 className="mb-3 text-xs font-medium uppercase tracking-wider text-destructive">
                Danger Zone
              </h3>
              <div className="flex items-center justify-between rounded-md border border-destructive/30 px-4 py-3">
                <div>
                  <p className="text-sm font-medium">Delete this agent</p>
                  <p className="text-xs text-muted-foreground">
                    Once deleted, this agent cannot be recovered.
                  </p>
                </div>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => setShowDeleteModal(true)}
                >
                  <Trash2 className="mr-1.5 size-3.5" />
                  Delete Agent
                </Button>
              </div>
            </div>
          </div>
        </div>

        {showDeleteModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
            <div className="w-96 rounded-lg border bg-background p-6 shadow-lg">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-sm font-medium">Delete "{detail.name}"?</h2>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => setShowDeleteModal(false)}
                >
                  <X className="size-4" />
                </Button>
              </div>
              <p className="text-sm text-muted-foreground mb-5">
                This will archive the agent, stop any running containers, and remove it from the sidebar. Choose whether to keep or delete the agent's workspace files.
              </p>
              <div className="flex flex-col gap-2">
                <Button
                  variant="outline"
                  className="w-full justify-start"
                  onClick={() => {
                    setShowDeleteModal(false)
                    onDeleteAgent(detail.id, false)
                  }}
                >
                  <FolderOpen className="mr-2 size-4" />
                  Keep Agent Workspace
                </Button>
                <Button
                  variant="destructive"
                  className="w-full justify-start"
                  onClick={() => {
                    setShowDeleteModal(false)
                    onDeleteAgent(detail.id, true)
                  }}
                >
                  <Trash2 className="mr-2 size-4" />
                  Delete Everything
                </Button>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="mt-3 w-full"
                onClick={() => setShowDeleteModal(false)}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}
        </>
      ) : (
        <div className="flex flex-1 flex-col overflow-hidden">
          <div className="flex items-center gap-3 border-b px-4 py-2">
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => navigate(`/agents/${agentName}`)}
            >
              <ArrowLeft className="size-4" />
            </Button>
            <span className="text-sm font-medium">
              {openFile?.file}
            </span>
            <div className="ml-auto">
              <Button
                size="sm"
                onClick={handleSave}
                disabled={!dirty || saving}
              >
                {saving ? "Saving..." : "Save"}
              </Button>
            </div>
          </div>
          <FileEditor
            value={content}
            onChange={(v) => {
              setContent(v)
              setDirty(true)
            }}
          />
        </div>
      )}
    </div>
  )
}
