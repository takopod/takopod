import { useCallback, useEffect, useState } from "react"
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
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
  File,
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
  Timer,
  Trash2,
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
  builtin?: boolean
  transport?: "stdio" | "http"
  command?: string
  args?: string[]
  url?: string
  auth?: "none" | "basic" | "oauth"
  note?: string
  display_name?: string
}

function McpServerLabel({ srv }: { srv: McpServer }) {
  return (
    <>
      <span className="text-sm font-medium">{srv.display_name || srv.name}</span>
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
  const [search, setSearch] = useState("")
  const [searchFocused, setSearchFocused] = useState(false)
  const [oauthStatus, setOauthStatus] = useState<Record<string, boolean>>({})
  const [confirmRemoveId, setConfirmRemoveId] = useState<string | null>(null)

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

  const handleRemoveConfirm = async () => {
    if (!confirmRemoveId) return
    const res = await fetch(`/api/agents/${agentId}/mcp/servers/${confirmRemoveId}`, {
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
          onClick={() => navigate(`/a/${encodeURIComponent(agentName!)}/settings?tab=extensions`)}
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
                          {srv.note && (
                            <span className="text-xs text-amber-500">{srv.note}</span>
                          )}
                        </div>
                        {srv.builtin && (
                          <Badge variant="outline" className="text-[10px]">BUILTIN</Badge>
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
                      {srv.note && (
                        <span className="text-xs text-amber-500">{srv.note}</span>
                      )}
                    </div>
                    {srv.builtin && (
                      <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                        BUILTIN
                      </span>
                    )}
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => setConfirmRemoveId(srv.id)}
                    >
                      <Trash2 className="size-3.5 text-destructive" />
                    </Button>
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
      <ConfirmDialog
        open={confirmRemoveId !== null}
        onOpenChange={(open) => { if (!open) setConfirmRemoveId(null) }}
        title="Remove MCP server"
        description="Remove this MCP server from the agent?"
        confirmLabel="Remove"
        destructive
        onConfirm={handleRemoveConfirm}
      />
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
  const [idleTimeout, setIdleTimeout] = useState(String(detail.idle_timeout_seconds ?? 300))
  const [hardTimeout, setHardTimeout] = useState(String(detail.inflight_hard_timeout ?? 600))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    setMemory(detail.container_memory ?? "2g")
    setCpus(detail.container_cpus ?? "2")
    setIdleTimeout(String(detail.idle_timeout_seconds ?? 300))
    setHardTimeout(String(detail.inflight_hard_timeout ?? 600))
  }, [detail.container_memory, detail.container_cpus, detail.idle_timeout_seconds, detail.inflight_hard_timeout])

  const dirty = memory !== (detail.container_memory ?? "2g")
    || cpus !== (detail.container_cpus ?? "2")
    || idleTimeout !== String(detail.idle_timeout_seconds ?? 300)
    || hardTimeout !== String(detail.inflight_hard_timeout ?? 600)

  const handleSave = async () => {
    setSaving(true)
    setError("")
    setSaved(false)
    try {
      const body: Record<string, unknown> = { container_memory: memory, container_cpus: cpus }
      const it = parseInt(idleTimeout, 10)
      const ht = parseInt(hardTimeout, 10)
      if (!isNaN(it)) body.idle_timeout_seconds = it
      if (!isNaN(ht)) body.inflight_hard_timeout = ht
      const res = await fetch(`/api/agents/${agentId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
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
          Resource limits and lifecycle settings. Changes take effect on next container start.
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
          <div>
            <label className="mb-1.5 flex items-center gap-1.5 text-sm font-medium">
              <Timer className="size-3.5 text-muted-foreground" />
              Idle Timeout (s)
            </label>
            <Input
              value={idleTimeout}
              onChange={(e) => { setIdleTimeout(e.target.value); setError(""); setSaved(false) }}
              placeholder="300"
              className="h-8 text-sm"
            />
            <span className="text-[11px] text-muted-foreground">Seconds before idle container shutdown</span>
          </div>
          <div>
            <label className="mb-1.5 flex items-center gap-1.5 text-sm font-medium">
              <Timer className="size-3.5 text-muted-foreground" />
              Hard Timeout (s)
            </label>
            <Input
              value={hardTimeout}
              onChange={(e) => { setHardTimeout(e.target.value); setError(""); setSaved(false) }}
              placeholder="600"
              className="h-8 text-sm"
            />
            <span className="text-[11px] text-muted-foreground">Max time for in-flight messages</span>
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

interface ExtMcpServer {
  id: string
  name: string
  builtin?: boolean
  transport?: "stdio" | "http"
  auth?: "none" | "basic" | "oauth"
  display_name?: string
}

interface ExtSkill {
  id: string
  name: string
  description: string
  builtin: boolean
  always_enabled: boolean
}

interface ExtDraft {
  id: string
  name: string
}

function AgentSettingsDashboard({
  agentId,
  agentName,
  detail,
  onSelectAgent,
  onDeleteAgent,
  onUpdateDetail,
  filesMode,
  fileSplat,
}: {
  agentId: string
  agentName: string
  detail: AgentDetail
  onSelectAgent: (id: string) => void
  onDeleteAgent: (id: string, deleteWorkDir?: boolean) => void
  onUpdateDetail: (d: AgentDetail) => void
  filesMode?: boolean
  fileSplat?: string
}) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const activeTab = filesMode ? "files" : (searchParams.get("tab") || "general")
  const [showDeleteModal, setShowDeleteModal] = useState(false)

  const [mcpServers, setMcpServers] = useState<ExtMcpServer[]>([])
  const [mcpOauth, setMcpOauth] = useState<Record<string, boolean>>({})
  const [skills, setSkills] = useState<ExtSkill[]>([])
  const [drafts, setDrafts] = useState<ExtDraft[]>([])
  const [extLoading, setExtLoading] = useState(false)

  const encodedName = encodeURIComponent(agentName)

  const fetchExtensions = useCallback(async () => {
    setExtLoading(true)
    try {
      const [mcpRes, skillsRes, draftsRes] = await Promise.all([
        fetch(`/api/agents/${agentId}/mcp`),
        fetch(`/api/agents/${agentId}/registry-skills`),
        fetch(`/api/agents/${agentId}/skill-drafts`),
      ])
      if (mcpRes.ok) {
        const data = await mcpRes.json()
        const srvs: ExtMcpServer[] = data.servers || []
        setMcpServers(srvs)
        const statuses: Record<string, boolean> = {}
        await Promise.all(
          srvs
            .filter((s) => s.auth === "oauth")
            .map(async (s) => {
              try {
                const r = await fetch(`/oauth/status/${s.name}`)
                if (r.ok) {
                  const st = await r.json()
                  statuses[s.name] = st.authorized
                }
              } catch { /* ignore */ }
            }),
        )
        setMcpOauth(statuses)
      }
      if (skillsRes.ok) {
        const data = await skillsRes.json()
        setSkills(data.skills || [])
      }
      if (draftsRes.ok) {
        setDrafts(await draftsRes.json())
      }
    } finally {
      setExtLoading(false)
    }
  }, [agentId])

  useEffect(() => {
    setMcpServers([])
    setMcpOauth({})
    setSkills([])
    setDrafts([])
  }, [agentId])

  useEffect(() => {
    if (activeTab === "extensions") {
      fetchExtensions()
    }
  }, [activeTab, fetchExtensions])

  const handleTabChange = (value: string) => {
    if (value === "files") {
      navigate(`/a/${encodedName}/settings/files`)
    } else {
      navigate(`/a/${encodedName}/settings?tab=${value}`)
    }
  }

  return (
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

      <Tabs value={activeTab} onValueChange={handleTabChange} className="flex flex-1 flex-col overflow-hidden">
        <div className="border-b px-4">
          <TabsList variant="line">
            <TabsTrigger value="general">General</TabsTrigger>
            <TabsTrigger value="extensions">Extensions</TabsTrigger>
            <TabsTrigger value="infrastructure">Infrastructure</TabsTrigger>
            <TabsTrigger value="files">Files</TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="general" className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl space-y-6 p-6">
            {/* Identity Files */}
            <div>
              <h3 className="mb-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Identity Files
              </h3>
              <div className="rounded-md border divide-y">
                {IDENTITY_FILES.map(({ file: f, description }) => (
                  <button
                    key={f}
                    type="button"
                    className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-accent/50"
                    onClick={() => navigate(`/a/${encodedName}/settings/${f}`)}
                  >
                    <File className="size-4 shrink-0 text-muted-foreground" />
                    <div className="flex-1 min-w-0">
                      <span className="text-sm font-medium">{f}</span>
                      <p className="text-xs text-muted-foreground">{description}</p>
                    </div>
                    <Pencil className="size-3.5 shrink-0 text-muted-foreground" />
                  </button>
                ))}
              </div>
            </div>

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
        </TabsContent>

        <TabsContent value="extensions" className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl space-y-6 p-6">
            {extLoading ? (
              <p className="text-sm text-muted-foreground">Loading...</p>
            ) : (
              <>
                {/* MCP Servers */}
                <div>
                  <div className="mb-3 flex items-center justify-between">
                    <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      MCP Servers
                      {mcpServers.length > 0 && (
                        <span className="ml-1.5 normal-case tracking-normal text-muted-foreground/60">
                          ({mcpServers.length})
                        </span>
                      )}
                    </h3>
                    <Link
                      to={`/a/${encodedName}/settings/mcp`}
                      className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                    >
                      Manage
                      <ChevronRight className="size-3" />
                    </Link>
                  </div>
                  {mcpServers.length === 0 ? (
                    <div className="rounded-md border border-dashed px-4 py-6 text-center">
                      <Server className="mx-auto mb-2 size-5 text-muted-foreground/50" />
                      <p className="text-sm text-muted-foreground">
                        No MCP servers attached.
                      </p>
                      <p className="text-xs text-muted-foreground/60 mt-1">
                        Add one to give this agent external tool access.
                      </p>
                      <Button
                        variant="outline"
                        size="sm"
                        className="mt-3"
                        onClick={() => navigate(`/a/${encodedName}/settings/mcp`)}
                      >
                        Add Server
                      </Button>
                    </div>
                  ) : (
                    <div className="rounded-md border divide-y">
                      {mcpServers.map((srv) => (
                        <div
                          key={srv.id}
                          className="flex items-center gap-3 px-4 py-2.5"
                        >
                          <span className="text-sm font-medium">
                            {srv.display_name || srv.name}
                          </span>
                          <Badge variant="secondary" className="text-[10px]">
                            {srv.transport || "stdio"}
                          </Badge>
                          {srv.builtin && (
                            <Badge variant="outline" className="text-[10px]">
                              BUILTIN
                            </Badge>
                          )}
                          {srv.auth === "oauth" && (
                            <span className={`ml-auto flex items-center gap-1.5 text-xs ${mcpOauth[srv.name] ? "text-green-600" : "text-yellow-600"}`}>
                              <span className={`size-1.5 rounded-full ${mcpOauth[srv.name] ? "bg-green-500" : "bg-yellow-500"}`} />
                              {mcpOauth[srv.name] ? "Authorized" : "Not authorized"}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Skills */}
                <div>
                  <div className="mb-3 flex items-center justify-between">
                    <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      Skills
                      {skills.length > 0 && (
                        <span className="ml-1.5 normal-case tracking-normal text-muted-foreground/60">
                          ({skills.length})
                        </span>
                      )}
                    </h3>
                    <Link
                      to={`/a/${encodedName}/settings/skills`}
                      className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                    >
                      Manage
                      <ChevronRight className="size-3" />
                    </Link>
                  </div>

                  {drafts.length > 0 && (
                    <Link
                      to={`/a/${encodedName}/settings/skills`}
                      className="mb-3 flex items-center gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 transition-colors hover:bg-amber-500/10"
                    >
                      <Sparkles className="size-3.5 text-amber-600" />
                      <span className="text-xs text-amber-700 dark:text-amber-400">
                        {drafts.length} skill {drafts.length === 1 ? "draft" : "drafts"} pending review
                      </span>
                      <ChevronRight className="ml-auto size-3 text-amber-600" />
                    </Link>
                  )}

                  {skills.length === 0 ? (
                    <div className="rounded-md border border-dashed px-4 py-6 text-center">
                      <Sparkles className="mx-auto mb-2 size-5 text-muted-foreground/50" />
                      <p className="text-sm text-muted-foreground">
                        No skills attached.
                      </p>
                      <p className="text-xs text-muted-foreground/60 mt-1">
                        Add skills to give this agent reusable capabilities.
                      </p>
                      <Button
                        variant="outline"
                        size="sm"
                        className="mt-3"
                        onClick={() => navigate(`/a/${encodedName}/settings/skills`)}
                      >
                        Add Skill
                      </Button>
                    </div>
                  ) : (
                    <div className="rounded-md border divide-y">
                      {skills.map((skill) => (
                        <div
                          key={skill.id}
                          className="flex items-center gap-3 px-4 py-2.5"
                        >
                          <span className="text-sm font-medium">{skill.name}</span>
                          {skill.always_enabled && (
                            <Badge variant="outline" className="text-[10px]">
                              BUILTIN
                            </Badge>
                          )}
                          {skill.description && (
                            <span className="ml-auto text-xs text-muted-foreground truncate max-w-[200px]">
                              {skill.description}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </TabsContent>

        <TabsContent value="infrastructure" className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl p-6">
            <ContainerResourcesPanel agentId={agentId} detail={detail} onUpdate={onUpdateDetail} />
          </div>
        </TabsContent>

        <TabsContent value="files" className="flex-1 overflow-hidden">
          <FileBrowser agentId={agentId} agentName={agentName} initialPath={fileSplat} />
        </TabsContent>
      </Tabs>

      <Dialog open={showDeleteModal} onOpenChange={setShowDeleteModal}>
        <DialogContent className="sm:max-w-sm" showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Delete "{detail.name}"?</DialogTitle>
            <DialogDescription>
              This will archive the agent, stop any running containers, and remove it from the sidebar. Choose whether to keep or delete the agent's workspace files.
            </DialogDescription>
          </DialogHeader>
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
          <DialogFooter>
            <Button
              variant="ghost"
              size="sm"
              className="w-full"
              onClick={() => setShowDeleteModal(false)
              }
            >
              Cancel
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
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

  const location = useLocation()
  const pathAfterAgent = agentName ? location.pathname.split(`/a/${encodeURIComponent(agentName)}/settings/`)[1] ?? "" : ""
  const showFileBrowser = file === "files" || (fileSplat !== undefined && !pathAfterAgent.startsWith("skills"))
  const showMcpConfig = file === "mcp"
  const showSkills = file === "skills" || pathAfterAgent.startsWith("skills")
  const skillsSplat = pathAfterAgent.startsWith("skills/") ? pathAfterAgent.slice("skills/".length) : undefined
  const openFile = !showFileBrowser && !showMcpConfig && !showSkills
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
      ) : showSkills ? (
        <SkillsPanel agentId={agentId} agentName={agentName} initialPath={skillsSplat} />
      ) : !openFile || showFileBrowser ? (
        <AgentSettingsDashboard
          agentId={agentId}
          agentName={agentName!}
          detail={detail}
          onSelectAgent={onSelectAgent}
          onDeleteAgent={onDeleteAgent}
          onUpdateDetail={setDetail}
          filesMode={showFileBrowser}
          fileSplat={fileSplat}
        />
      ) : (
        <div className="flex flex-1 flex-col overflow-hidden">
          <div className="flex items-center gap-3 border-b px-4 py-2">
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => navigate(`/a/${encodeURIComponent(agentName!)}/settings`)}
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
            markdown
          />
        </div>
      )}
    </div>
  )
}
