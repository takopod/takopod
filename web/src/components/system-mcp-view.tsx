import { useCallback, useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { Separator } from "@/components/ui/separator"
import { Info, Pencil, Plus, Trash2, X } from "lucide-react"

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
  builtin: boolean
  note?: string
  display_name?: string
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
  const [newEnvVars, setNewEnvVars] = useState("")
  const [saving, setSaving] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)
  const [editTransport, setEditTransport] = useState<"stdio" | "http">("stdio")
  const [editCommand, setEditCommand] = useState("")
  const [editArgs, setEditArgs] = useState("")
  const [editUrl, setEditUrl] = useState("")
  const [editAuth, setEditAuth] = useState<"none" | "basic" | "oauth">("none")
  const [editEnvVars, setEditEnvVars] = useState("")
  const [oauthStatus, setOauthStatus] = useState<Record<string, boolean>>({})
  const [authorizing, setAuthorizing] = useState<string | null>(null)
  const [confirmRemove, setConfirmRemove] = useState<McpServer | null>(null)

  const fetchServers = useCallback(async () => {
    const res = await fetch("/api/mcp/servers")
    if (res.ok) {
      const data: McpServer[] = await res.json()
      setServers(data)
      // Fetch OAuth status for all oauth-configured servers
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
        // Poll for completion
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
      setShowAdd(false)
      setNewName("")
      setNewTransport("stdio")
      setNewCommand("")
      setNewArgs("")
      setNewUrl("")
      setNewAuth("none")
      setNewEnvVars("")
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
    setEditEnvVars(
      srv.env
        ? Object.entries(srv.env)
            .map(([k, v]) => `${k}=${v}`)
            .join("\n")
        : "",
    )
  }

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

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="sticky top-0 z-10 flex items-center gap-2 border-b bg-background px-4 py-1.5">
        <SidebarTrigger className="-ml-1" />
        <Separator orientation="vertical" className="mr-1 data-[orientation=vertical]:h-4" />
        <span className="text-sm font-medium">Available MCP Servers</span>
        <div className="ml-auto">
          <Button size="sm" onClick={() => setShowAdd(true)} disabled={showAdd}>
            <Plus className="mr-1.5 size-3.5" />
            Add Server
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        <div className="mx-auto max-w-2xl">
          <div className="mb-4 flex items-start gap-2.5 rounded-md border border-primary/20 bg-primary/5 px-4 py-3">
            <Info className="mt-0.5 size-4 shrink-0 text-primary" />
            <p className="text-xs text-muted-foreground">
              MCP servers available to assign to agents. Add a server here,
              then enable it per-agent from the agent's MCP settings.
            </p>
          </div>

          {loading ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : (
            <div className="flex flex-col gap-3">
              {servers.length === 0 && !showAdd && (
                <p className="text-sm text-muted-foreground">
                  No MCP servers configured. Add one to give agents
                  external tool integrations.
                </p>
              )}

              {servers.map((srv) =>
                editing === srv.id ? (
                  <div key={srv.id} className="rounded-md border p-4">
                    <div className="mb-3 flex items-center justify-between">
                      <span className="text-sm font-medium">{srv.display_name || srv.name}</span>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => setEditing(null)}
                      >
                        <X className="size-4" />
                      </Button>
                    </div>
                    <div className="flex flex-col gap-3">
                      <div className="flex flex-col gap-1.5">
                        <Label className="text-xs">Transport</Label>
                        <select
                          value={editTransport}
                          onChange={(e) =>
                            setEditTransport(
                              e.target.value as "stdio" | "http",
                            )
                          }
                          className="h-9 rounded-md border bg-background px-3 text-sm"
                        >
                          <option value="stdio">stdio (local command)</option>
                          <option value="http">HTTP (remote server)</option>
                        </select>
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
                            <Label className="text-xs">
                              Arguments (one per line)
                            </Label>
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
                            <select
                              value={editAuth}
                              onChange={(e) =>
                                setEditAuth(
                                  e.target.value as "none" | "basic" | "oauth",
                                )
                              }
                              className="h-9 rounded-md border bg-background px-3 text-sm"
                            >
                              <option value="none">None</option>
                              <option value="basic">
                                Basic (username + token)
                              </option>
                              <option value="oauth">OAuth</option>
                            </select>
                          </div>
                        </>
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
                      <div className="flex justify-end gap-2 pt-1">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setEditing(null)}
                        >
                          Cancel
                        </Button>
                        <Button
                          size="sm"
                          onClick={handleSaveEdit}
                          disabled={
                            (editTransport === "stdio" &&
                              !editCommand.trim()) ||
                            (editTransport === "http" && !editUrl.trim()) ||
                            saving
                          }
                        >
                          {saving ? "Saving..." : "Save"}
                        </Button>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div
                    key={srv.id}
                    className="flex items-start justify-between rounded-md border px-4 py-3"
                  >
                    <div className="flex flex-col gap-1">
                      <span className="text-sm font-medium">{srv.display_name || srv.name}</span>
                      <code className="text-xs text-muted-foreground">
                        {srv.transport === "http"
                          ? `HTTP: ${srv.url}`
                          : `${srv.command || ""} ${(srv.args || []).join(" ")}`}
                      </code>
                      {srv.note && (
                        <span className="text-xs text-amber-500">{srv.note}</span>
                      )}
                      {srv.auth === "oauth" && (
                        <span
                          className={`text-xs ${oauthStatus[srv.name] ? "text-green-500" : "text-yellow-500"}`}
                        >
                          {oauthStatus[srv.name] ? "Authorized" : "Not authorized"}
                        </span>
                      )}
                      {srv.auth !== "oauth" &&
                        srv.env &&
                        Object.keys(srv.env).length > 0 && (
                          <span className="text-xs text-muted-foreground">
                            env: {Object.keys(srv.env).join(", ")}
                          </span>
                        )}
                    </div>
                    <div className="flex items-center gap-1">
                      {srv.auth === "oauth" && (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={authorizing === srv.name}
                          onClick={() => handleAuthorize(srv.name)}
                        >
                          {authorizing === srv.name
                            ? "Authorizing..."
                            : oauthStatus[srv.name]
                              ? "Re-authorize"
                              : "Authorize"}
                        </Button>
                      )}
                      {srv.builtin ? (
                        <span className="text-[10px] text-muted-foreground/60 uppercase tracking-wider">
                          builtin
                        </span>
                      ) : (
                        <>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => startEdit(srv)}
                          >
                            <Pencil className="size-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => setConfirmRemove(srv)}
                          >
                            <Trash2 className="size-3.5 text-destructive" />
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                ),
              )}

              {showAdd && (
                <div className="rounded-md border p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <span className="text-sm font-medium">
                      Add MCP Server
                    </span>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => setShowAdd(false)}
                    >
                      <X className="size-4" />
                    </Button>
                  </div>
                  <div className="flex flex-col gap-3">
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="mcp-name" className="text-xs">
                        Server Name
                      </Label>
                      <Input
                        id="mcp-name"
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        placeholder="e.g. jira"
                        autoFocus
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label className="text-xs">Transport</Label>
                      <select
                        value={newTransport}
                        onChange={(e) =>
                          setNewTransport(
                            e.target.value as "stdio" | "http",
                          )
                        }
                        className="h-9 rounded-md border bg-background px-3 text-sm"
                      >
                        <option value="stdio">stdio (local command)</option>
                        <option value="http">HTTP (remote server)</option>
                      </select>
                    </div>
                    {newTransport === "stdio" ? (
                      <>
                        <div className="flex flex-col gap-1.5">
                          <Label htmlFor="mcp-command" className="text-xs">
                            Command
                          </Label>
                          <Input
                            id="mcp-command"
                            value={newCommand}
                            onChange={(e) => setNewCommand(e.target.value)}
                            placeholder="e.g. npx or uvx"
                          />
                        </div>
                        <div className="flex flex-col gap-1.5">
                          <Label htmlFor="mcp-args" className="text-xs">
                            Arguments (one per line)
                          </Label>
                          <Textarea
                            id="mcp-args"
                            value={newArgs}
                            onChange={(e) => setNewArgs(e.target.value)}
                            placeholder={
                              "mcp-atlassian\n--jira-url\nhttps://your-domain.atlassian.net"
                            }
                            className="min-h-20 resize-none font-mono text-xs"
                            spellCheck={false}
                          />
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="flex flex-col gap-1.5">
                          <Label htmlFor="mcp-url" className="text-xs">
                            Server URL
                          </Label>
                          <Input
                            id="mcp-url"
                            value={newUrl}
                            onChange={(e) => setNewUrl(e.target.value)}
                            placeholder="https://mcp.atlassian.com/v1/mcp"
                          />
                        </div>
                        <div className="flex flex-col gap-1.5">
                          <Label className="text-xs">Authentication</Label>
                          <select
                            value={newAuth}
                            onChange={(e) =>
                              setNewAuth(
                                e.target.value as "none" | "basic" | "oauth",
                              )
                            }
                            className="h-9 rounded-md border bg-background px-3 text-sm"
                          >
                            <option value="none">None</option>
                            <option value="basic">
                              Basic (username + token)
                            </option>
                            <option value="oauth">OAuth</option>
                          </select>
                        </div>
                      </>
                    )}
                    {newAuth !== "oauth" && (
                      <div className="flex flex-col gap-1.5">
                        <Label htmlFor="mcp-env" className="text-xs">
                          {newTransport === "http"
                            ? "Credentials (KEY=VALUE, one per line)"
                            : "Environment Variables (KEY=VALUE, one per line)"}
                        </Label>
                        <Textarea
                          id="mcp-env"
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
                    <div className="flex justify-end gap-2 pt-1">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setShowAdd(false)}
                      >
                        Cancel
                      </Button>
                      <Button
                        size="sm"
                        onClick={handleAdd}
                        disabled={
                          !newName.trim() ||
                          (newTransport === "stdio" &&
                            !newCommand.trim()) ||
                          (newTransport === "http" && !newUrl.trim()) ||
                          saving
                        }
                      >
                        {saving ? "Adding..." : "Add"}
                      </Button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
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
