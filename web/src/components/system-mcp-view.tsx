import { useCallback, useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { Separator } from "@/components/ui/separator"
import { Info, Pencil, Plus, Trash2, X } from "lucide-react"

interface McpServerConfig {
  command: string
  args: string[]
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
  const [newCommand, setNewCommand] = useState("")
  const [newArgs, setNewArgs] = useState("")
  const [newEnvVars, setNewEnvVars] = useState("")
  const [saving, setSaving] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)
  const [editCommand, setEditCommand] = useState("")
  const [editArgs, setEditArgs] = useState("")
  const [editEnvVars, setEditEnvVars] = useState("")

  const fetchConfig = useCallback(async () => {
    const res = await fetch("/api/mcp")
    if (res.ok) {
      setConfig(await res.json())
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    fetchConfig()
  }, [fetchConfig])

  const handleAdd = async () => {
    if (!newName.trim() || !newCommand.trim()) return
    setSaving(true)
    const args = newArgs.trim()
      ? newArgs
          .split("\n")
          .map((a) => a.trim())
          .filter(Boolean)
      : []
    const env: Record<string, string> = {}
    for (const line of newEnvVars.split("\n")) {
      const eq = line.indexOf("=")
      if (eq > 0) {
        env[line.slice(0, eq).trim()] = line.slice(eq + 1).trim()
      }
    }
    const server: McpServerConfig = { command: newCommand.trim(), args }
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
      setNewCommand("")
      setNewArgs("")
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
    setEditCommand(srv.command)
    setEditArgs(srv.args.join("\n"))
    setEditEnvVars(
      srv.env
        ? Object.entries(srv.env)
            .map(([k, v]) => `${k}=${v}`)
            .join("\n")
        : "",
    )
  }

  const handleSaveEdit = async () => {
    if (!editing || !editCommand.trim()) return
    setSaving(true)
    const args = editArgs.trim()
      ? editArgs
          .split("\n")
          .map((a) => a.trim())
          .filter(Boolean)
      : []
    const env: Record<string, string> = {}
    for (const line of editEnvVars.split("\n")) {
      const eq = line.indexOf("=")
      if (eq > 0) {
        env[line.slice(0, eq).trim()] = line.slice(eq + 1).trim()
      }
    }
    const server: McpServerConfig = { command: editCommand.trim(), args }
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
                      <div className="flex flex-col gap-1.5">
                        <Label className="text-xs">
                          Environment Variables (KEY=VALUE, one per line)
                        </Label>
                        <Textarea
                          value={editEnvVars}
                          onChange={(e) => setEditEnvVars(e.target.value)}
                          placeholder="GITHUB_PERSONAL_ACCESS_TOKEN=ghp_..."
                          className="min-h-16 resize-none font-mono text-xs"
                          spellCheck={false}
                        />
                      </div>
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
                          disabled={!editCommand.trim() || saving}
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
                        {srv.command} {srv.args.join(" ")}
                      </code>
                      {srv.env && Object.keys(srv.env).length > 0 && (
                        <span className="text-xs text-muted-foreground">
                          env: {Object.keys(srv.env).join(", ")}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1">
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
                        placeholder={"-y\n@modelcontextprotocol/server-github"}
                        className="min-h-20 resize-none font-mono text-xs"
                        spellCheck={false}
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="mcp-env" className="text-xs">
                        Environment Variables (KEY=VALUE, one per line)
                      </Label>
                      <Textarea
                        id="mcp-env"
                        value={newEnvVars}
                        onChange={(e) => setNewEnvVars(e.target.value)}
                        placeholder="GITHUB_PERSONAL_ACCESS_TOKEN=ghp_..."
                        className="min-h-16 resize-none font-mono text-xs"
                        spellCheck={false}
                      />
                    </div>
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
                        disabled={!newName.trim() || !newCommand.trim() || saving}
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
