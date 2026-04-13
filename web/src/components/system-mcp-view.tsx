import { useCallback, useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { Separator } from "@/components/ui/separator"
import { Info, Pencil, Plus, Trash2, X } from "lucide-react"

interface McpServerConfig {
  transport?: "stdio" | "http"
  command?: string
  args?: string[]
  url?: string
  auth?: "none" | "basic" | "oauth"
  env?: Record<string, string>
}

interface McpConfig {
  mcpServers: Record<string, McpServerConfig>
}

export function SystemMcpView() {
  const [config, setConfig] = useState<McpConfig>({ mcpServers: {} })
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

  const fetchConfig = useCallback(async () => {
    const res = await fetch("/api/mcp")
    if (res.ok) {
      const data = await res.json()
      setConfig(data)
      // Fetch OAuth status for all oauth-configured servers
      const oauthServers = Object.entries(
        data.mcpServers as Record<string, McpServerConfig>,
      ).filter(([, srv]) => srv.auth === "oauth")
      const statuses: Record<string, boolean> = {}
      await Promise.all(
        oauthServers.map(async ([name]) => {
          try {
            const r = await fetch(`/oauth/status/${name}`)
            if (r.ok) {
              const s = await r.json()
              statuses[name] = s.authorized
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
    fetchConfig()
  }, [fetchConfig])

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

  const handleAdd = async () => {
    if (!newName.trim()) return
    if (newTransport === "stdio" && !newCommand.trim()) return
    if (newTransport === "http" && !newUrl.trim()) return

    setSaving(true)
    const env: Record<string, string> = {}
    for (const line of newEnvVars.split("\n")) {
      const eq = line.indexOf("=")
      if (eq > 0) {
        env[line.slice(0, eq).trim()] = line.slice(eq + 1).trim()
      }
    }

    let server: McpServerConfig
    if (newTransport === "http") {
      server = { transport: "http", url: newUrl.trim(), auth: newAuth }
    } else {
      const args = newArgs.trim()
        ? newArgs.split("\n").map((a) => a.trim()).filter(Boolean)
        : []
      server = { transport: "stdio", command: newCommand.trim(), args }
    }
    if (Object.keys(env).length > 0) server.env = env

    const updated: McpConfig = {
      mcpServers: {
        ...config.mcpServers,
        [newName.trim()]: server,
      },
    }
    const res = await fetch("/api/mcp", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updated),
    })
    if (res.ok) {
      setConfig(await res.json())
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

  const handleRemove = async (name: string) => {
    if (!confirm(`Remove "${name}" from default MCP servers?`)) return
    const res = await fetch(`/api/mcp/servers/${name}`, {
      method: "DELETE",
    })
    if (res.ok) {
      setConfig((prev) => {
        const { [name]: _, ...rest } = prev.mcpServers
        return { mcpServers: rest }
      })
    }
  }

  const startEdit = (name: string, srv: McpServerConfig) => {
    setEditing(name)
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
    const env: Record<string, string> = {}
    for (const line of editEnvVars.split("\n")) {
      const eq = line.indexOf("=")
      if (eq > 0) {
        env[line.slice(0, eq).trim()] = line.slice(eq + 1).trim()
      }
    }

    let server: McpServerConfig
    if (editTransport === "http") {
      server = { transport: "http", url: editUrl.trim(), auth: editAuth }
    } else {
      const args = editArgs.trim()
        ? editArgs.split("\n").map((a) => a.trim()).filter(Boolean)
        : []
      server = { transport: "stdio", command: editCommand.trim(), args }
    }
    if (Object.keys(env).length > 0) server.env = env

    const updated: McpConfig = {
      mcpServers: {
        ...config.mcpServers,
        [editing]: server,
      },
    }
    const res = await fetch("/api/mcp", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updated),
    })
    if (res.ok) {
      setConfig(await res.json())
      setEditing(null)
    }
    setSaving(false)
  }

  const servers = Object.entries(config.mcpServers)

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="sticky top-0 z-10 flex items-center gap-2 border-b bg-background px-4 py-1.5">
        <SidebarTrigger className="-ml-1" />
        <Separator orientation="vertical" className="mr-1 data-[orientation=vertical]:h-4" />
        <span className="text-sm font-medium">Default MCP Servers</span>
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
              They are included in each new agent's configuration at creation
              time. Changes here do not affect existing agents.
            </p>
          </div>

          {loading ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : (
            <div className="flex flex-col gap-3">
              {servers.length === 0 && !showAdd && (
                <p className="text-sm text-muted-foreground">
                  No default MCP servers configured. Add one to give new agents
                  external tool integrations out of the box.
                </p>
              )}

              {servers.map(([name, srv]) =>
                editing === name ? (
                  <div key={name} className="rounded-md border p-4">
                    <div className="mb-3 flex items-center justify-between">
                      <span className="text-sm font-medium">{name}</span>
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
                    key={name}
                    className="flex items-start justify-between rounded-md border px-4 py-3"
                  >
                    <div className="flex flex-col gap-1">
                      <span className="text-sm font-medium">{name}</span>
                      <code className="text-xs text-muted-foreground">
                        {srv.transport === "http"
                          ? `HTTP: ${srv.url}`
                          : `${srv.command || ""} ${(srv.args || []).join(" ")}`}
                      </code>
                      {srv.auth === "oauth" && (
                        <span
                          className={`text-xs ${oauthStatus[name] ? "text-green-500" : "text-yellow-500"}`}
                        >
                          {oauthStatus[name] ? "Authorized" : "Not authorized"}
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
                          disabled={authorizing === name}
                          onClick={() => handleAuthorize(name)}
                        >
                          {authorizing === name
                            ? "Authorizing..."
                            : oauthStatus[name]
                              ? "Re-authorize"
                              : "Authorize"}
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => startEdit(name, srv)}
                      >
                        <Pencil className="size-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => handleRemove(name)}
                      >
                        <Trash2 className="size-3.5 text-destructive" />
                      </Button>
                    </div>
                  </div>
                ),
              )}

              {showAdd && (
                <div className="rounded-md border p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <span className="text-sm font-medium">
                      Add Default MCP Server
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
                        placeholder="e.g. github"
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
                              "-y\n@modelcontextprotocol/server-github"
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
    </div>
  )
}
