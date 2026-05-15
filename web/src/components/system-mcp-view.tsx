import { useCallback, useEffect, useMemo, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import {
  Globe,
  Loader2,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  Server,
  ShieldCheck,
  Terminal,
  Trash2,
  Unplug,
} from "lucide-react"

interface McpServer {
  id: string
  name: string
  transport: "stdio" | "http"
  command: string
  args: string[]
  url: string
  auth: "none" | "basic" | "oauth"
  env: Record<string, string>
  timeout: number
  scope: string
  builtin: boolean
  note?: string
  display_name?: string
}

function transportBadgeClass(transport: string): string {
  return transport === "http"
    ? "border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-400"
    : "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
}

function authBadgeClass(auth: string): string {
  switch (auth) {
    case "oauth":
      return "border-purple-500/30 bg-purple-500/10 text-purple-700 dark:text-purple-400"
    case "basic":
      return "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400"
    default:
      return ""
  }
}

export function SystemMcpView() {
  const [servers, setServers] = useState<McpServer[]>([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [newName, setNewName] = useState("")
  const [newTransport, setNewTransport] = useState<"stdio" | "http">("stdio")
  const [newCommand, setNewCommand] = useState("")
  const [newArgs, setNewArgs] = useState("")
  const [newUrl, setNewUrl] = useState("")
  const [newAuth, setNewAuth] = useState<"none" | "basic" | "oauth">("none")
  const [newScope, setNewScope] = useState("")
  const [newEnvVars, setNewEnvVars] = useState("")
  const [saving, setSaving] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)
  const [editTransport, setEditTransport] = useState<"stdio" | "http">("stdio")
  const [editCommand, setEditCommand] = useState("")
  const [editArgs, setEditArgs] = useState("")
  const [editUrl, setEditUrl] = useState("")
  const [editAuth, setEditAuth] = useState<"none" | "basic" | "oauth">("none")
  const [editScope, setEditScope] = useState("")
  const [editEnvVars, setEditEnvVars] = useState("")
  const [oauthStatus, setOauthStatus] = useState<Record<string, boolean>>({})
  const [authorizing, setAuthorizing] = useState<string | null>(null)
  const [confirmRemove, setConfirmRemove] = useState<McpServer | null>(null)

  const [activeTab, setActiveTab] = useState("all")
  const [searchQuery, setSearchQuery] = useState("")

  const fetchServers = useCallback(async () => {
    const res = await fetch("/api/mcp/servers")
    if (res.ok) {
      const data: McpServer[] = await res.json()
      setServers(data)
      const oauthServers = data.filter((s) => s.auth === "oauth")
      const statuses: Record<string, boolean> = {}
      await Promise.all(
        oauthServers.map(async (srv) => {
          try {
            const r = await fetch(`/oauth/status/${srv.name}`)
            if (r.ok) {
              const s = await r.json()
              statuses[srv.name] = s.authorized
            }
          } catch {
            // ignore
          }
        }),
      )
      setOauthStatus(statuses)
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    fetchServers()
  }, [fetchServers])

  const handleAuthorize = async (name: string) => {
    setAuthorizing(name)
    try {
      const res = await fetch(`/oauth/start/${name}`)
      if (res.ok) {
        const data = await res.json()
        window.open(data.authorize_url, "_blank")
        for (let i = 0; i < 60; i++) {
          await new Promise((r) => setTimeout(r, 2000))
          const statusRes = await fetch(`/oauth/status/${name}`)
          if (statusRes.ok) {
            const status = await statusRes.json()
            if (status.authorized) {
              setOauthStatus((prev) => ({ ...prev, [name]: true }))
              break
            }
          }
        }
      }
    } finally {
      setAuthorizing(null)
    }
  }

  const parseEnvVars = (text: string): Record<string, string> => {
    const env: Record<string, string> = {}
    for (const line of text.split("\n")) {
      const eq = line.indexOf("=")
      if (eq > 0) {
        env[line.slice(0, eq).trim()] = line.slice(eq + 1).trim()
      }
    }
    return env
  }

  const resetAddForm = () => {
    setNewName("")
    setNewTransport("stdio")
    setNewCommand("")
    setNewArgs("")
    setNewUrl("")
    setNewAuth("none")
    setNewScope("")
    setNewEnvVars("")
  }

  const closeAddDialog = () => {
    setShowAdd(false)
    resetAddForm()
  }

  const handleAdd = async () => {
    if (!newName.trim()) return
    if (newTransport === "stdio" && !newCommand.trim()) return
    if (newTransport === "http" && !newUrl.trim()) return

    setSaving(true)
    const env = parseEnvVars(newEnvVars)

    const body: Record<string, unknown> = {
      name: newName.trim(),
      transport: newTransport,
    }
    if (newTransport === "http") {
      body.url = newUrl.trim()
      body.auth = newAuth
      if (newAuth === "oauth" && newScope.trim()) body.scope = newScope.trim()
    } else {
      body.command = newCommand.trim()
      const args = newArgs.trim()
        ? newArgs.split("\n").map((a) => a.trim()).filter(Boolean)
        : []
      if (args.length > 0) body.args = args
    }
    if (Object.keys(env).length > 0) body.env = env

    const res = await fetch("/api/mcp/servers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
    if (res.ok) {
      await fetchServers()
      closeAddDialog()
    }
    setSaving(false)
  }

  const handleRemoveConfirm = async () => {
    if (!confirmRemove) return
    const res = await fetch(`/api/mcp/servers/${confirmRemove.id}`, {
      method: "DELETE",
    })
    if (res.ok) {
      setServers((prev) => prev.filter((s) => s.id !== confirmRemove.id))
    }
  }

  const startEdit = (srv: McpServer) => {
    setEditing(srv.id)
    setEditTransport(srv.transport || "stdio")
    setEditCommand(srv.command || "")
    setEditArgs((srv.args || []).join("\n"))
    setEditUrl(srv.url || "")
    setEditAuth(srv.auth || "none")
    setEditScope(srv.scope || "")
    setEditEnvVars(
      srv.env
        ? Object.entries(srv.env)
            .map(([k, v]) => `${k}=${v}`)
            .join("\n")
        : "",
    )
  }

  const cancelEdit = () => setEditing(null)

  const handleSaveEdit = async () => {
    if (!editing) return
    if (editTransport === "stdio" && !editCommand.trim()) return
    if (editTransport === "http" && !editUrl.trim()) return

    setSaving(true)
    const env = parseEnvVars(editEnvVars)

    const body: Record<string, unknown> = { transport: editTransport }
    if (editTransport === "http") {
      body.url = editUrl.trim()
      body.auth = editAuth
      body.scope = editAuth === "oauth" ? editScope.trim() : ""
    } else {
      body.command = editCommand.trim()
      const args = editArgs.trim()
        ? editArgs.split("\n").map((a) => a.trim()).filter(Boolean)
        : []
      body.args = args
    }
    body.env = env

    const res = await fetch(`/api/mcp/servers/${editing}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
    if (res.ok) {
      await fetchServers()
      setEditing(null)
    }
    setSaving(false)
  }

  const editingServer = servers.find((s) => s.id === editing)

  const stdioCount = servers.filter((s) => s.transport === "stdio").length
  const httpCount = servers.filter((s) => s.transport === "http").length
  const builtinCount = servers.filter((s) => s.builtin).length

  const filteredServers = useMemo(() => {
    let result = [...servers]
    if (activeTab === "stdio") result = result.filter((s) => s.transport === "stdio")
    if (activeTab === "http") result = result.filter((s) => s.transport === "http")
    if (activeTab === "builtin") result = result.filter((s) => s.builtin)
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      result = result.filter(
        (s) =>
          (s.display_name || s.name).toLowerCase().includes(q) ||
          (s.command || "").toLowerCase().includes(q) ||
          (s.url || "").toLowerCase().includes(q)
      )
    }
    return result
  }, [servers, activeTab, searchQuery])

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">MCP Servers</h2>
            <p className="text-xs text-muted-foreground">
              Manage servers available to assign to agents
            </p>
          </div>
          <Button size="sm" onClick={() => setShowAdd(true)}>
            <Plus className="mr-1 size-3.5" />
            Add Server
          </Button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl space-y-5 p-5">
          {/* Stat Cards */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Card size="sm" className="gap-0">
              <CardContent className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-lg bg-muted">
                  <Server className="size-4 text-muted-foreground" />
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Total</p>
                  <p className="text-xl font-semibold tracking-tight">{servers.length}</p>
                </div>
              </CardContent>
            </Card>
            <Card size="sm" className="gap-0">
              <CardContent className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-lg bg-emerald-500/10">
                  <Terminal className="size-4 text-emerald-600 dark:text-emerald-400" />
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Local (stdio)</p>
                  <p className="text-xl font-semibold tracking-tight">{stdioCount}</p>
                </div>
              </CardContent>
            </Card>
            <Card size="sm" className="gap-0">
              <CardContent className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-lg bg-blue-500/10">
                  <Globe className="size-4 text-blue-600 dark:text-blue-400" />
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Remote (HTTP)</p>
                  <p className="text-xl font-semibold tracking-tight">{httpCount}</p>
                </div>
              </CardContent>
            </Card>
            <Card size="sm" className="gap-0">
              <CardContent className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-lg bg-muted">
                  <Unplug className="size-4 text-muted-foreground" />
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Builtin</p>
                  <p className="text-xl font-semibold tracking-tight">{builtinCount}</p>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Tabs + Search */}
          <div className="flex items-center justify-between gap-4">
            <Tabs value={activeTab} onValueChange={setActiveTab}>
              <TabsList>
                <TabsTrigger value="all">
                  All
                  <Badge variant="secondary" className="ml-1 h-4 min-w-5 px-1 text-[10px]">
                    {servers.length}
                  </Badge>
                </TabsTrigger>
                <TabsTrigger value="stdio">
                  Local
                  <Badge variant="secondary" className="ml-1 h-4 min-w-5 px-1 text-[10px]">
                    {stdioCount}
                  </Badge>
                </TabsTrigger>
                <TabsTrigger value="http">
                  Remote
                  <Badge variant="secondary" className="ml-1 h-4 min-w-5 px-1 text-[10px]">
                    {httpCount}
                  </Badge>
                </TabsTrigger>
                <TabsTrigger value="builtin">
                  Builtin
                  <Badge variant="secondary" className="ml-1 h-4 min-w-5 px-1 text-[10px]">
                    {builtinCount}
                  </Badge>
                </TabsTrigger>
              </TabsList>
            </Tabs>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Search servers..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-8 w-56 pl-8 text-sm"
              />
            </div>
          </div>

          {/* Data Table */}
          <div className="rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="pl-4">Server</TableHead>
                  <TableHead>Transport</TableHead>
                  <TableHead className="min-w-[200px]">Connection</TableHead>
                  <TableHead>Auth</TableHead>
                  <TableHead className="w-10 pr-4"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading && (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={5} className="h-32 text-center">
                      <div className="flex items-center justify-center gap-2 text-muted-foreground">
                        <Loader2 className="size-4 animate-spin" />
                        <span className="text-sm">Loading servers...</span>
                      </div>
                    </TableCell>
                  </TableRow>
                )}
                {!loading && filteredServers.length === 0 && (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={5} className="h-32 text-center">
                      <div className="flex flex-col items-center gap-1.5 text-muted-foreground">
                        <Server className="size-8 opacity-30" />
                        <p className="text-sm">
                          {servers.length === 0
                            ? "No MCP servers configured"
                            : "No servers match your filters"}
                        </p>
                        {servers.length === 0 && (
                          <p className="text-xs">
                            Add a server to give agents external tool integrations.
                          </p>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                )}
                {filteredServers.map((srv) => (
                    <TableRow key={srv.id}>
                      {/* Server */}
                      <TableCell className="pl-4">
                        <div className="flex flex-col gap-0.5">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium">
                              {srv.display_name || srv.name}
                            </span>
                            {srv.builtin && (
                              <Badge variant="outline" className="h-4 px-1 text-[10px] font-normal">
                                builtin
                              </Badge>
                            )}
                          </div>
                          {srv.note && (
                            <span className="text-xs text-amber-600 dark:text-amber-400">{srv.note}</span>
                          )}
                          {srv.auth !== "oauth" && srv.env && Object.keys(srv.env).length > 0 && (
                            <span className="text-[11px] text-muted-foreground">
                              env: {Object.keys(srv.env).join(", ")}
                            </span>
                          )}
                        </div>
                      </TableCell>

                      {/* Transport */}
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={`text-[11px] font-normal ${transportBadgeClass(srv.transport)}`}
                        >
                          {srv.transport === "http" ? "HTTP" : "stdio"}
                        </Badge>
                      </TableCell>

                      {/* Connection */}
                      <TableCell>
                        <TooltipProvider>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <code className="block max-w-[300px] truncate text-xs text-muted-foreground">
                                {srv.transport === "http"
                                  ? srv.url
                                  : `${srv.command || ""} ${(srv.args || []).join(" ")}`.trim()}
                              </code>
                            </TooltipTrigger>
                            <TooltipContent side="bottom" className="max-w-sm">
                              <span className="font-mono">
                                {srv.transport === "http"
                                  ? srv.url
                                  : `${srv.command || ""} ${(srv.args || []).join(" ")}`.trim()}
                              </span>
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      </TableCell>

                      {/* Auth */}
                      <TableCell>
                        <div className="flex items-center gap-2">
                          {srv.auth === "none" ? (
                            <span className="text-xs text-muted-foreground">--</span>
                          ) : (
                            <Badge
                              variant="outline"
                              className={`text-[11px] font-normal ${authBadgeClass(srv.auth)}`}
                            >
                              {srv.auth}
                            </Badge>
                          )}
                          {srv.auth === "oauth" && (
                            <div className="flex items-center gap-1.5">
                              <div
                                className={`size-2 rounded-full ${
                                  oauthStatus[srv.name]
                                    ? "bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.4)]"
                                    : "bg-amber-500"
                                }`}
                              />
                              <span className="text-[11px] text-muted-foreground">
                                {oauthStatus[srv.name] ? "Authorized" : "Not authorized"}
                              </span>
                            </div>
                          )}
                        </div>
                      </TableCell>

                      {/* Actions */}
                      <TableCell className="pr-4">
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon-xs">
                              <MoreHorizontal className="size-3.5" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            {srv.auth === "oauth" && (
                              <DropdownMenuItem
                                onClick={() => handleAuthorize(srv.name)}
                                disabled={authorizing === srv.name}
                              >
                                {authorizing === srv.name ? (
                                  <Loader2 className="size-4 animate-spin" />
                                ) : (
                                  <ShieldCheck className="size-4" />
                                )}
                                {authorizing === srv.name
                                  ? "Authorizing..."
                                  : oauthStatus[srv.name]
                                    ? "Re-authorize"
                                    : "Authorize"}
                              </DropdownMenuItem>
                            )}
                            {!srv.builtin && (
                              <>
                                <DropdownMenuItem onClick={() => startEdit(srv)}>
                                  <Pencil className="size-4" />
                                  Edit
                                </DropdownMenuItem>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem
                                  variant="destructive"
                                  onClick={() => setConfirmRemove(srv)}
                                >
                                  <Trash2 className="size-4" />
                                  Remove
                                </DropdownMenuItem>
                              </>
                            )}
                            {srv.builtin && !srv.auth && (
                              <DropdownMenuItem disabled>
                                <span className="text-xs text-muted-foreground">No actions available</span>
                              </DropdownMenuItem>
                            )}
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </TableCell>
                    </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {filteredServers.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Showing {filteredServers.length} of {servers.length} server{servers.length !== 1 ? "s" : ""}
            </p>
          )}
        </div>
      </div>

      {/* ── Add Server Dialog ── */}
      <Dialog open={showAdd} onOpenChange={(open) => { if (!open) closeAddDialog() }}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Add MCP Server</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs">Server Name</Label>
              <Input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="e.g. jira"
                autoFocus
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs">Transport</Label>
              <Select value={newTransport} onValueChange={(v) => { setNewTransport(v as "stdio" | "http"); if (v === "stdio") setNewAuth("none") }}>
                <SelectTrigger className="h-9 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="stdio">stdio (local command)</SelectItem>
                  <SelectItem value="http">HTTP (remote server)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {newTransport === "stdio" ? (
              <>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs">Command</Label>
                  <Input
                    value={newCommand}
                    onChange={(e) => setNewCommand(e.target.value)}
                    placeholder="e.g. npx or uvx"
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs">Arguments (one per line)</Label>
                  <Textarea
                    value={newArgs}
                    onChange={(e) => setNewArgs(e.target.value)}
                    placeholder={"mcp-atlassian\n--jira-url\nhttps://your-domain.atlassian.net"}
                    className="min-h-20 resize-none font-mono text-xs"
                    spellCheck={false}
                  />
                </div>
              </>
            ) : (
              <>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs">Server URL</Label>
                  <Input
                    value={newUrl}
                    onChange={(e) => setNewUrl(e.target.value)}
                    placeholder="https://mcp.atlassian.com/v1/mcp"
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs">Authentication</Label>
                  <Select value={newAuth} onValueChange={(v) => setNewAuth(v as "none" | "basic" | "oauth")}>
                    <SelectTrigger className="h-9 text-sm">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">None</SelectItem>
                      <SelectItem value="basic">Basic (username + token)</SelectItem>
                      <SelectItem value="oauth">OAuth</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </>
            )}
            {newAuth === "oauth" && (
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs">OAuth Scopes (space-separated)</Label>
                <Input
                  value={newScope}
                  onChange={(e) => setNewScope(e.target.value)}
                  placeholder="read:jira-work write:jira-work read:jira-user read:me offline_access"
                  className="font-mono text-xs"
                  spellCheck={false}
                />
                <p className="text-[10px] text-muted-foreground">
                  Leave empty to let the server decide. Required for Atlassian Rovo write access.
                </p>
              </div>
            )}
            {newAuth !== "oauth" && (
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs">
                  {newTransport === "http"
                    ? "Credentials (KEY=VALUE, one per line)"
                    : "Environment Variables (KEY=VALUE, one per line)"}
                </Label>
                <Textarea
                  value={newEnvVars}
                  onChange={(e) => setNewEnvVars(e.target.value)}
                  placeholder={
                    newTransport === "http" && newAuth === "basic"
                      ? "MCP_USERNAME=user@example.com\nMCP_API_TOKEN=your-api-token"
                      : "JIRA_API_TOKEN=your-api-token"
                  }
                  className="min-h-16 resize-none font-mono text-xs"
                  spellCheck={false}
                />
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={closeAddDialog}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={handleAdd}
              disabled={
                !newName.trim() ||
                (newTransport === "stdio" && !newCommand.trim()) ||
                (newTransport === "http" && !newUrl.trim()) ||
                saving
              }
            >
              {saving ? "Adding..." : "Add Server"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Edit Server Dialog ── */}
      {editingServer && (
        <Dialog open onOpenChange={(open) => { if (!open) cancelEdit() }}>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <div className="flex items-center gap-2">
                <DialogTitle>Edit Server</DialogTitle>
                <Badge
                  variant="outline"
                  className={`text-[10px] ${transportBadgeClass(editingServer.transport)}`}
                >
                  {editingServer.display_name || editingServer.name}
                </Badge>
              </div>
            </DialogHeader>
            <div className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs">Transport</Label>
                <Select value={editTransport} onValueChange={(v) => { setEditTransport(v as "stdio" | "http"); if (v === "stdio") setEditAuth("none") }}>
                  <SelectTrigger className="h-9 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="stdio">stdio (local command)</SelectItem>
                    <SelectItem value="http">HTTP (remote server)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {editTransport === "stdio" ? (
                <>
                  <div className="flex flex-col gap-1.5">
                    <Label className="text-xs">Command</Label>
                    <Input
                      value={editCommand}
                      onChange={(e) => setEditCommand(e.target.value)}
                      autoFocus
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label className="text-xs">Arguments (one per line)</Label>
                    <Textarea
                      value={editArgs}
                      onChange={(e) => setEditArgs(e.target.value)}
                      className="min-h-20 resize-none font-mono text-xs"
                      spellCheck={false}
                    />
                  </div>
                </>
              ) : (
                <>
                  <div className="flex flex-col gap-1.5">
                    <Label className="text-xs">Server URL</Label>
                    <Input
                      value={editUrl}
                      onChange={(e) => setEditUrl(e.target.value)}
                      placeholder="https://mcp.atlassian.com/v1/mcp"
                      autoFocus
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label className="text-xs">Authentication</Label>
                    <Select value={editAuth} onValueChange={(v) => setEditAuth(v as "none" | "basic" | "oauth")}>
                      <SelectTrigger className="h-9 text-sm">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="none">None</SelectItem>
                        <SelectItem value="basic">Basic (username + token)</SelectItem>
                        <SelectItem value="oauth">OAuth</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </>
              )}
              {editAuth === "oauth" && (
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs">OAuth Scopes (space-separated)</Label>
                  <Input
                    value={editScope}
                    onChange={(e) => setEditScope(e.target.value)}
                    placeholder="read:jira-work write:jira-work read:jira-user read:me offline_access"
                    className="font-mono text-xs"
                    spellCheck={false}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Leave empty to let the server decide. Required for Atlassian Rovo write access.
                  </p>
                </div>
              )}
              {editAuth !== "oauth" && (
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs">
                    {editTransport === "http"
                      ? "Credentials (KEY=VALUE, one per line)"
                      : "Environment Variables (KEY=VALUE, one per line)"}
                  </Label>
                  <Textarea
                    value={editEnvVars}
                    onChange={(e) => setEditEnvVars(e.target.value)}
                    placeholder={
                      editTransport === "http" && editAuth === "basic"
                        ? "MCP_USERNAME=user@example.com\nMCP_API_TOKEN=your-api-token"
                        : "GITHUB_PERSONAL_ACCESS_TOKEN=ghp_..."
                    }
                    className="min-h-16 resize-none font-mono text-xs"
                    spellCheck={false}
                  />
                </div>
              )}
            </div>
            <DialogFooter>
              <Button variant="outline" size="sm" onClick={cancelEdit}>
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={handleSaveEdit}
                disabled={
                  (editTransport === "stdio" && !editCommand.trim()) ||
                  (editTransport === "http" && !editUrl.trim()) ||
                  saving
                }
              >
                {saving ? "Saving..." : "Save"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}

      <ConfirmDialog
        open={confirmRemove !== null}
        onOpenChange={(open) => { if (!open) setConfirmRemove(null) }}
        title="Remove MCP server"
        description={confirmRemove ? `Remove "${confirmRemove.display_name || confirmRemove.name}" from MCP servers?` : ""}
        confirmLabel="Remove"
        destructive
        onConfirm={handleRemoveConfirm}
      />
    </div>
  )
}
