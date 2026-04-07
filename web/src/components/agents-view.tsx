import { useCallback, useEffect, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { FileBrowser } from "@/components/file-browser"
import { SkillsPanel } from "@/components/skills-panel"
import type { Agent } from "@/lib/types"
import { ArrowLeft, Pencil, Plus, Square, Trash2, X } from "lucide-react"

interface AgentDetail extends Agent {
  claude_md: string
  soul_md: string
  memory_md: string
  slack_enabled?: boolean
}

type FileKey = "claude_md" | "soul_md" | "memory_md"

const FILE_MAP: { key: FileKey; label: string }[] = [
  { key: "claude_md", label: "CLAUDE.md" },
  { key: "soul_md", label: "SOUL.md" },
  { key: "memory_md", label: "MEMORY.md" },
]

interface McpServerConfig {
  command: string
  args: string[]
  env?: Record<string, string>
}

interface McpConfig {
  mcpServers: Record<string, McpServerConfig>
}

function McpConfigPanel({ agentId }: { agentId: string }) {
  const navigate = useNavigate()
  const [config, setConfig] = useState<McpConfig>({ mcpServers: {} })
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [newName, setNewName] = useState("")
  const [newCommand, setNewCommand] = useState("")
  const [newArgs, setNewArgs] = useState("")
  const [newEnvVars, setNewEnvVars] = useState("")
  const [saving, setSaving] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)
  const [editCommand, setEditCommand] = useState("")
  const [editArgs, setEditArgs] = useState("")
  const [editEnvVars, setEditEnvVars] = useState("")

  const handleStop = async () => {
    setStopping(true)
    try {
      const res = await fetch("/api/containers")
      if (res.ok) {
        const containers = await res.json()
        const active = containers.find(
          (c: { agent_id: string; status: string }) =>
            c.agent_id === agentId &&
            ["running", "idle", "starting"].includes(c.status),
        )
        if (active) {
          await fetch(`/api/containers/${active.id}`, { method: "DELETE" })
        }
      }
    } finally {
      setStopping(false)
    }
  }

  const fetchConfig = useCallback(async () => {
    const res = await fetch(`/api/agents/${agentId}/mcp`)
    if (res.ok) {
      setConfig(await res.json())
    }
    setLoading(false)
  }, [agentId])

  useEffect(() => {
    fetchConfig()
  }, [fetchConfig])

  const handleAdd = async () => {
    if (!newName.trim() || !newCommand.trim()) return
    setSaving(true)
    const args = newArgs.trim()
      ? newArgs.split("\n").map((a) => a.trim()).filter(Boolean)
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
    const res = await fetch(`/api/agents/${agentId}/mcp`, {
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
    const res = await fetch(`/api/agents/${agentId}/mcp/servers/${name}`, {
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
      ? editArgs.split("\n").map((a) => a.trim()).filter(Boolean)
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
    const res = await fetch(`/api/agents/${agentId}/mcp`, {
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
      <div className="flex items-center gap-3 border-b px-4 py-2">
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => navigate(`/agents/${agentId}`)}
        >
          <ArrowLeft className="size-4" />
        </Button>
        <span className="text-sm font-medium">MCP Servers</span>
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleStop}
            disabled={stopping}
          >
            <Square className="mr-1.5 size-3 fill-current" />
            {stopping ? "Stopping..." : "Stop Worker"}
          </Button>
          <Button size="sm" onClick={() => setShowAdd(true)} disabled={showAdd}>
            <Plus className="mr-1.5 size-3.5" />
            Add Server
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : (
          <div className="flex flex-col gap-3">
            {servers.length === 0 && !showAdd && (
              <p className="text-sm text-muted-foreground">
                No MCP servers configured. Add one to extend this agent's capabilities.
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
                      <Label className="text-xs">Arguments (one per line)</Label>
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
                        placeholder={"GITHUB_PERSONAL_ACCESS_TOKEN=ghp_..."}
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
                  <span className="text-sm font-medium">Add MCP Server</span>
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
                      placeholder={"GITHUB_PERSONAL_ACCESS_TOKEN=ghp_..."}
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

            {servers.length > 0 && (
              <p className="text-xs text-muted-foreground">
                Changes take effect after stopping and restarting the worker.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function SlackToggle({ agentId, initialEnabled }: { agentId: string; initialEnabled: boolean }) {
  const [enabled, setEnabled] = useState(initialEnabled)
  const [toggling, setToggling] = useState(false)

  useEffect(() => {
    setEnabled(initialEnabled)
  }, [initialEnabled])

  const handleToggle = async () => {
    setToggling(true)
    try {
      const res = await fetch(`/api/agents/${agentId}/slack`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !enabled }),
      })
      if (res.ok) setEnabled(!enabled)
    } finally {
      setToggling(false)
    }
  }

  return (
    <div className="mt-4 rounded-md border px-4 py-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">Slack</div>
          <div className="text-xs text-muted-foreground">
            {enabled ? "Agent can read channels and DM you" : "Slack tools disabled"}
          </div>
        </div>
        <button
          onClick={handleToggle}
          disabled={toggling}
          className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
            enabled ? "bg-primary" : "bg-muted"
          } ${toggling ? "opacity-50" : ""}`}
        >
          <span
            className={`pointer-events-none inline-block size-5 rounded-full bg-background shadow-sm ring-0 transition-transform ${
              enabled ? "translate-x-5" : "translate-x-0"
            }`}
          />
        </button>
      </div>
      {enabled && (
        <p className="mt-1 text-xs text-muted-foreground">
          Restart the worker for changes to take effect.
        </p>
      )}
    </div>
  )
}

function GitHubToggle({ agentId, initialEnabled }: { agentId: string; initialEnabled: boolean }) {
  const [enabled, setEnabled] = useState(initialEnabled)
  const [toggling, setToggling] = useState(false)

  useEffect(() => {
    setEnabled(initialEnabled)
  }, [initialEnabled])

  const handleToggle = async () => {
    setToggling(true)
    try {
      const res = await fetch(`/api/agents/${agentId}/github`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !enabled }),
      })
      if (res.ok) setEnabled(!enabled)
    } finally {
      setToggling(false)
    }
  }

  return (
    <div className="mt-4 rounded-md border px-4 py-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">GitHub</div>
          <div className="text-xs text-muted-foreground">
            {enabled ? "Agent can monitor PRs and CI" : "GitHub tools disabled"}
          </div>
        </div>
        <button
          onClick={handleToggle}
          disabled={toggling}
          className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
            enabled ? "bg-primary" : "bg-muted"
          } ${toggling ? "opacity-50" : ""}`}
        >
          <span
            className={`pointer-events-none inline-block size-5 rounded-full bg-background shadow-sm ring-0 transition-transform ${
              enabled ? "translate-x-5" : "translate-x-0"
            }`}
          />
        </button>
      </div>
      {enabled && (
        <p className="mt-1 text-xs text-muted-foreground">
          Restart the worker for changes to take effect.
        </p>
      )}
    </div>
  )
}

interface AgentsViewProps {
  agents: Agent[]
  onSelectAgent: (id: string) => void
  onDeleteAgent: (id: string) => void
}

export function AgentsView({ agents, onSelectAgent, onDeleteAgent }: AgentsViewProps) {
  const { agentId, file } = useParams<{ agentId?: string; file?: string }>()
  const navigate = useNavigate()
  const [detail, setDetail] = useState<AgentDetail | null>(null)
  const [content, setContent] = useState("")
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)

  const showFileBrowser = file === "files"
  const showMcpConfig = file === "mcp"
  const showSkills = file === "skills"
  const openFile =
    !showFileBrowser && !showMcpConfig && !showSkills && FILE_MAP.find((f) => f.key === file)
      ? (file as FileKey)
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
    fetchDetail(agentId).then((data) => {
      if (data && openFile) {
        setContent(data[openFile])
        setDirty(false)
      }
    })
  }, [agentId, openFile, fetchDetail])

  const handleSave = async () => {
    if (!agentId || !openFile) return
    setSaving(true)
    const res = await fetch(`/api/agents/${agentId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [openFile]: content }),
    })
    if (res.ok) {
      const data: AgentDetail = await res.json()
      setDetail(data)
      setDirty(false)
    }
    setSaving(false)
  }

  const lineCount = content.split("\n").length

  return (
    <div className="flex flex-1 overflow-hidden">
      <div className="w-56 shrink-0 overflow-y-auto border-r p-3">
        <div className="mb-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Agents
        </div>
        <div className="flex flex-col gap-1">
          {agents.map((agent) => (
            <Link
              key={agent.id}
              to={`/agents/${agent.id}`}
              className={`rounded-md px-3 py-1.5 text-left text-sm ${
                agentId === agent.id
                  ? "bg-muted font-medium text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {agent.name}
            </Link>
          ))}
        </div>
      </div>

      <div className="flex flex-1 flex-col overflow-hidden">
        {!agentId || !detail ? (
          <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
            Select an agent to view and edit its files.
          </div>
        ) : showMcpConfig ? (
          <McpConfigPanel agentId={agentId} />
        ) : showSkills ? (
          <SkillsPanel agentId={agentId} />
        ) : showFileBrowser ? (
          <FileBrowser agentId={agentId} />
        ) : !openFile ? (
          <div className="p-6">
            <div className="mb-6 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-medium">{detail.name}</h2>
                <p className="text-xs text-muted-foreground">
                  Type: {detail.agent_type}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onSelectAgent(detail.id)}
                >
                  Chat
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => {
                    if (confirm(`Delete agent "${detail.name}"?`)) {
                      onDeleteAgent(detail.id)
                    }
                  }}
                >
                  <Trash2 className="mr-1.5 size-3.5" />
                  Delete
                </Button>
              </div>
            </div>
            <div className="flex flex-col gap-1">
              {FILE_MAP.map(({ key, label }) => (
                <Link
                  key={key}
                  to={`/agents/${agentId}/${key}`}
                  className="rounded-md px-3 py-2 text-sm text-primary underline-offset-4 hover:underline"
                >
                  {label}
                </Link>
              ))}
              <Link
                to={`/agents/${agentId}/files`}
                className="rounded-md px-3 py-2 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
              >
                Browse All Files
              </Link>
              <Link
                to={`/agents/${agentId}/mcp`}
                className="rounded-md px-3 py-2 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
              >
                MCP Servers
              </Link>
              <Link
                to={`/agents/${agentId}/skills`}
                className="rounded-md px-3 py-2 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
              >
                Skills
              </Link>
            </div>
            <SlackToggle agentId={agentId} initialEnabled={detail.slack_enabled ?? false} />
            <GitHubToggle agentId={agentId} initialEnabled={detail.github_enabled ?? false} />
          </div>
        ) : (
          <div className="flex flex-1 flex-col overflow-hidden">
            <div className="flex items-center gap-3 border-b px-4 py-2">
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => navigate(`/agents/${agentId}`)}
              >
                <ArrowLeft className="size-4" />
              </Button>
              <span className="text-sm font-medium">
                {FILE_MAP.find((f) => f.key === openFile)?.label}
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
            <div className="flex flex-1 overflow-hidden font-mono text-xs">
              <div
                className="shrink-0 select-none border-r bg-muted/50 px-3 py-3 text-right text-muted-foreground"
                aria-hidden
              >
                {Array.from({ length: lineCount }, (_, i) => (
                  <div key={i} className="leading-5">
                    {i + 1}
                  </div>
                ))}
              </div>
              <Textarea
                value={content}
                onChange={(e) => {
                  setContent(e.target.value)
                  setDirty(true)
                }}
                className="flex-1 resize-none rounded-none border-0 p-3 leading-5 shadow-none focus-visible:ring-0"
                spellCheck={false}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
