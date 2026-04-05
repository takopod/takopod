import { useCallback, useEffect, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { FileBrowser } from "@/components/file-browser"
import type { Agent } from "@/lib/types"
import { ArrowLeft, Plus, Trash2, X } from "lucide-react"

interface AgentDetail extends Agent {
  claude_md: string
  soul_md: string
  memory_md: string
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
  const [saving, setSaving] = useState(false)

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
    const updated: McpConfig = {
      mcpServers: {
        ...config.mcpServers,
        [newName.trim()]: { command: newCommand.trim(), args },
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
        <div className="ml-auto">
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

            {servers.map(([name, srv]) => (
              <div
                key={name}
                className="flex items-start justify-between rounded-md border px-4 py-3"
              >
                <div className="flex flex-col gap-1">
                  <span className="text-sm font-medium">{name}</span>
                  <code className="text-xs text-muted-foreground">
                    {srv.command} {srv.args.join(" ")}
                  </code>
                </div>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => handleRemove(name)}
                >
                  <Trash2 className="size-3.5 text-destructive" />
                </Button>
              </div>
            ))}

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
                      placeholder="e.g. filesystem"
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
                      placeholder="e.g. npx"
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
                      placeholder={"-y\n@modelcontextprotocol/server-filesystem\n/workspace"}
                      className="min-h-20 resize-none font-mono text-xs"
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
                Changes take effect after clearing context (restarting the agent container).
              </p>
            )}
          </div>
        )}
      </div>
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
  const openFile =
    !showFileBrowser && !showMcpConfig && FILE_MAP.find((f) => f.key === file)
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
            </div>
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
