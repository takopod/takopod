import { useCallback, useEffect, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { FileBrowser } from "@/components/file-browser"
import type { Agent } from "@/lib/types"
import { ArrowLeft } from "lucide-react"

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

interface AgentsViewProps {
  agents: Agent[]
  onSelectAgent: (id: string) => void
}

export function AgentsView({ agents, onSelectAgent }: AgentsViewProps) {
  const { agentId, file } = useParams<{ agentId?: string; file?: string }>()
  const navigate = useNavigate()
  const [detail, setDetail] = useState<AgentDetail | null>(null)
  const [content, setContent] = useState("")
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)

  const showFileBrowser = file === "files"
  const openFile =
    !showFileBrowser && FILE_MAP.find((f) => f.key === file)
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
              <Button
                variant="outline"
                size="sm"
                onClick={() => onSelectAgent(detail.id)}
              >
                Chat
              </Button>
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
