import { Fragment, useCallback, useEffect, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  ChevronDown,
  ChevronRight,
  Eye,
  Pencil,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Trash2,
  X,
} from "lucide-react"

interface IndexEntry {
  message_id: string
  content: string
  role: string
  session_id: string
  created_at: string
  rank: number
}

interface IndexStats {
  orchestrator_count: number
  fts_count: number
  vec_count: number
}

interface MemoryFile {
  name: string
  size: number
  modified_at: string
  content_preview: string
  content: string
}

interface Agent {
  id: string
  name: string
}

export function SearchIndexView() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [selectedAgentId, setSelectedAgentId] = useState<string>("")
  const [results, setResults] = useState<IndexEntry[]>([])
  const [query, setQuery] = useState("")
  const [loading, setLoading] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editContent, setEditContent] = useState("")
  const [stats, setStats] = useState<IndexStats | null>(null)
  const [memoryFiles, setMemoryFiles] = useState<MemoryFile[]>([])
  const [expandedMemory, setExpandedMemory] = useState<string | null>(null)
  const [rebuilding, setRebuilding] = useState(false)
  const [rebuildResult, setRebuildResult] = useState<string | null>(null)

  const fetchAgents = useCallback(async () => {
    const res = await fetch("/api/agents")
    if (res.ok) {
      const data: Agent[] = await res.json()
      setAgents(data)
      if (!selectedAgentId && data.length > 0) {
        setSelectedAgentId(data[0].id)
      }
    }
  }, [selectedAgentId])

  useEffect(() => {
    fetchAgents()
  }, [fetchAgents])

  const fetchStats = useCallback(async () => {
    if (!selectedAgentId) return
    const res = await fetch(`/api/agents/${selectedAgentId}/search-index/stats`)
    if (res.ok) setStats(await res.json())
  }, [selectedAgentId])

  const fetchMemoryFiles = useCallback(async () => {
    if (!selectedAgentId) return
    const res = await fetch(`/api/agents/${selectedAgentId}/memory-files`)
    if (res.ok) setMemoryFiles(await res.json())
  }, [selectedAgentId])

  useEffect(() => {
    if (selectedAgentId) {
      fetchStats()
      fetchMemoryFiles()
      setResults([])
      setQuery("")
      setExpandedId(null)
      setEditingId(null)
    }
  }, [selectedAgentId, fetchStats, fetchMemoryFiles])

  const handleSearch = async () => {
    if (!selectedAgentId) return
    setLoading(true)
    const params = new URLSearchParams()
    if (query.trim()) params.set("q", query.trim())
    params.set("limit", "100")
    const res = await fetch(
      `/api/agents/${selectedAgentId}/search-index?${params}`,
    )
    if (res.ok) setResults(await res.json())
    setLoading(false)
  }

  const handleDelete = async (messageId: string) => {
    if (!confirm("Delete this entry from the search index?")) return
    const res = await fetch(
      `/api/agents/${selectedAgentId}/search-index/${encodeURIComponent(messageId)}`,
      { method: "DELETE" },
    )
    if (res.ok) {
      setResults((prev) => prev.filter((r) => r.message_id !== messageId))
      fetchStats()
    }
  }

  const startEditing = (entry: IndexEntry) => {
    setEditingId(entry.message_id)
    setEditContent(entry.content)
    setExpandedId(entry.message_id)
  }

  const cancelEditing = () => {
    setEditingId(null)
    setEditContent("")
  }

  const saveEditing = async (messageId: string) => {
    const res = await fetch(
      `/api/agents/${selectedAgentId}/search-index/${encodeURIComponent(messageId)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: editContent }),
      },
    )
    if (res.ok) {
      const data = await res.json()
      setResults((prev) =>
        prev.map((r) =>
          r.message_id === messageId ? { ...r, content: editContent } : r,
        ),
      )
      setEditingId(null)
      setEditContent("")
      fetchStats()
      if (data.warning) alert(data.warning)
    }
  }

  const handleReindex = async (messageId: string) => {
    const res = await fetch(
      `/api/agents/${selectedAgentId}/search-index/reindex`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_ids: [messageId] }),
      },
    )
    if (res.ok) {
      fetchStats()
      handleSearch()
    }
  }

  const handleFullRebuild = async () => {
    if (
      !confirm(
        "Full rebuild will drop and recreate all search indexes from the orchestrator source of truth. Continue?",
      )
    )
      return
    setRebuilding(true)
    setRebuildResult(null)
    const res = await fetch(
      `/api/agents/${selectedAgentId}/search-index/reindex`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      },
    )
    if (res.ok) {
      const data = await res.json()
      setRebuildResult(
        `Indexed ${data.indexed} messages, ${data.errors} errors${data.skipped_vectors ? " (vectors skipped — Ollama unreachable)" : ""}`,
      )
      fetchStats()
      handleSearch()
    }
    setRebuilding(false)
  }

  const handleDeleteMemory = async (filename: string) => {
    if (!confirm(`Delete memory file "${filename}"?`)) return
    const res = await fetch(
      `/api/agents/${selectedAgentId}/memory-files/${encodeURIComponent(filename)}`,
      { method: "DELETE" },
    )
    if (res.ok) {
      setMemoryFiles((prev) => prev.filter((f) => f.name !== filename))
    }
  }

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes}B`
    return `${(bytes / 1024).toFixed(1)}KB`
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-4 py-2">
        <span className="text-sm font-medium">Search Index</span>
        <div className="flex items-center gap-2">
          {agents.length > 0 && (
            <Select value={selectedAgentId} onValueChange={setSelectedAgentId}>
              <SelectTrigger className="h-7 w-40 text-xs">
                <SelectValue placeholder="Select agent" />
              </SelectTrigger>
              <SelectContent>
                {agents.map((a) => (
                  <SelectItem key={a.id} value={a.id}>
                    {a.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              fetchStats()
              fetchMemoryFiles()
            }}
          >
            <RefreshCw className="mr-1.5 size-3.5" />
            Refresh
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        {!selectedAgentId ? (
          <p className="p-4 text-sm text-muted-foreground">
            Select an agent to view its search index.
          </p>
        ) : (
          <div className="flex flex-col gap-4 p-4">
            {/* Stats */}
            {stats && (
              <div className="flex items-center gap-4 rounded-md border px-4 py-2 text-sm">
                <span>
                  FTS:{" "}
                  <span className="font-mono font-medium">
                    {stats.fts_count}
                  </span>
                </span>
                <span>
                  Vec:{" "}
                  <span className="font-mono font-medium">
                    {stats.vec_count}
                  </span>
                </span>
                <span>
                  Source:{" "}
                  <span className="font-mono font-medium">
                    {stats.orchestrator_count}
                  </span>
                </span>
                {stats.fts_count !== stats.orchestrator_count && (
                  <Badge variant="secondary">
                    {Math.abs(stats.fts_count - stats.orchestrator_count)} drift
                  </Badge>
                )}
              </div>
            )}

            {/* Search bar */}
            <div className="flex items-center gap-2">
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search indexed messages..."
                className="flex-1"
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              />
              <Button onClick={handleSearch} disabled={loading}>
                <Search
                  className={`mr-1.5 size-3.5 ${loading ? "animate-spin" : ""}`}
                />
                Search
              </Button>
              <Button
                variant="outline"
                onClick={handleFullRebuild}
                disabled={rebuilding}
              >
                <RotateCcw
                  className={`mr-1.5 size-3.5 ${rebuilding ? "animate-spin" : ""}`}
                />
                Full Rebuild
              </Button>
            </div>

            {rebuildResult && (
              <div className="rounded-md border bg-muted/50 px-3 py-2 text-sm">
                {rebuildResult}
              </div>
            )}

            {/* Results table */}
            {results.length > 0 && (
              <table className="w-full table-fixed text-sm">
                <thead>
                  <tr className="border-b bg-muted/50 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                    <th className="w-6 px-1 py-2" />
                    <th className="w-[10%] px-2 py-2">ID</th>
                    <th className="w-[6%] px-2 py-2">Role</th>
                    <th className="w-[10%] px-2 py-2">Session</th>
                    <th className="px-2 py-2">Content</th>
                    <th className="w-[12%] px-2 py-2">Created</th>
                    <th className="w-[14%] px-2 py-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((entry) => (
                    <Fragment key={entry.message_id}>
                      <tr
                        className="border-b last:border-b-0 cursor-pointer hover:bg-muted/30"
                        onClick={() =>
                          editingId !== entry.message_id &&
                          setExpandedId(
                            expandedId === entry.message_id
                              ? null
                              : entry.message_id,
                          )
                        }
                      >
                        <td className="px-1 py-2 text-muted-foreground">
                          {expandedId === entry.message_id ? (
                            <ChevronDown className="size-3.5" />
                          ) : (
                            <ChevronRight className="size-3.5" />
                          )}
                        </td>
                        <td
                          className="truncate px-2 py-2 font-mono text-xs text-muted-foreground"
                          title={entry.message_id}
                        >
                          {entry.message_id.slice(0, 8)}
                        </td>
                        <td className="px-2 py-2">
                          <Badge
                            variant={
                              entry.role === "user" ? "default" : "secondary"
                            }
                          >
                            {entry.role}
                          </Badge>
                        </td>
                        <td
                          className="truncate px-2 py-2 font-mono text-xs text-muted-foreground"
                          title={entry.session_id}
                        >
                          {entry.session_id.slice(0, 8)}
                        </td>
                        <td className="truncate px-2 py-2" title={entry.content}>
                          <span className="block truncate">{entry.content}</span>
                        </td>
                        <td className="truncate px-2 py-2 text-xs">
                          {entry.created_at}
                        </td>
                        <td
                          className="px-2 py-2"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <div className="flex items-center gap-1">
                            {editingId === entry.message_id ? (
                              <>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => saveEditing(entry.message_id)}
                                >
                                  <Save className="size-3.5" />
                                </Button>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={cancelEditing}
                                >
                                  <X className="size-3.5" />
                                </Button>
                              </>
                            ) : (
                              <>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => startEditing(entry)}
                                  title="Edit content"
                                >
                                  <Pencil className="size-3.5" />
                                </Button>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => handleReindex(entry.message_id)}
                                  title="Reindex from source"
                                >
                                  <RotateCcw className="size-3.5" />
                                </Button>
                                <Button
                                  variant="destructive"
                                  size="sm"
                                  onClick={() => handleDelete(entry.message_id)}
                                  title="Delete from index"
                                >
                                  <Trash2 className="size-3.5" />
                                </Button>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                      {expandedId === entry.message_id && (
                        <tr
                          className="border-b bg-muted/20"
                        >
                          <td colSpan={7} className="px-4 py-3">
                            {editingId === entry.message_id ? (
                              <textarea
                                value={editContent}
                                onChange={(e) => setEditContent(e.target.value)}
                                className="w-full min-h-[120px] rounded-md border bg-background px-3 py-2 text-sm font-mono"
                              />
                            ) : (
                              <>
                                <div className="mb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                                  Full Content
                                </div>
                                <pre className="whitespace-pre-wrap break-words text-sm leading-relaxed">
                                  {entry.content}
                                </pre>
                              </>
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            )}

            {results.length === 0 && !loading && (
              <p className="text-sm text-muted-foreground">
                Enter a search query or press Search with an empty query to see
                recent entries.
              </p>
            )}

            {/* Memory Files Section */}
            <div className="mt-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium">Memory Files</span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={fetchMemoryFiles}
                >
                  <RefreshCw className="mr-1.5 size-3.5" />
                  Refresh
                </Button>
              </div>
              {memoryFiles.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No memory files for this agent.
                </p>
              ) : (
                <div className="flex flex-col rounded-md border">
                  {memoryFiles.map((f) => (
                    <div key={f.name}>
                      <div className="flex items-center justify-between border-b px-4 py-2 last:border-b-0">
                        <div className="flex items-center gap-3">
                          <span className="text-sm font-mono">{f.name}</span>
                          <span className="text-xs text-muted-foreground">
                            {formatSize(f.size)}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {f.modified_at.slice(0, 10)}
                          </span>
                        </div>
                        <div className="flex items-center gap-1">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() =>
                              setExpandedMemory(
                                expandedMemory === f.name ? null : f.name,
                              )
                            }
                            title="View content"
                          >
                            <Eye className="size-3.5" />
                          </Button>
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={() => handleDeleteMemory(f.name)}
                            title="Delete memory file"
                          >
                            <Trash2 className="size-3.5" />
                          </Button>
                        </div>
                      </div>
                      {expandedMemory === f.name && (
                        <div className="border-b bg-muted/20 px-4 py-3">
                          <pre className="whitespace-pre-wrap break-words text-sm leading-relaxed">
                            {f.content}
                          </pre>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
