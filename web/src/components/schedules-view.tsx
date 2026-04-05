import { useCallback, useEffect, useState } from "react"
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
  Pause,
  Pencil,
  Play,
  RefreshCw,
  Save,
  Trash2,
  X,
} from "lucide-react"

interface Schedule {
  id: string
  agent_id: string
  agent_name: string
  prompt: string
  allowed_tools: string[]
  interval_seconds: number
  last_executed_at: string | null
  last_result: string | null
  status: string
  created_at: string
}

interface Agent {
  id: string
  name: string
}

export function SchedulesView() {
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editPrompt, setEditPrompt] = useState("")
  const [editAgentId, setEditAgentId] = useState("")
  const [editInterval, setEditInterval] = useState("")

  const fetchSchedules = useCallback(async () => {
    setLoading(true)
    const res = await fetch("/api/schedules")
    if (res.ok) {
      setSchedules(await res.json())
    }
    setLoading(false)
  }, [])

  const fetchAgents = useCallback(async () => {
    const res = await fetch("/api/agents")
    if (res.ok) {
      setAgents(await res.json())
    }
  }, [])

  useEffect(() => {
    fetchSchedules()
    fetchAgents()
  }, [fetchSchedules, fetchAgents])

  const handleToggle = async (id: string, currentStatus: string) => {
    const action = currentStatus === "active" ? "pause" : "resume"
    const res = await fetch(`/api/schedules/${id}/${action}`, { method: "POST" })
    if (res.ok) fetchSchedules()
  }

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this scheduled task? This cannot be undone.")) return
    const res = await fetch(`/api/schedules/${id}`, { method: "DELETE" })
    if (res.ok) fetchSchedules()
  }

  const startEditing = (s: Schedule) => {
    setEditingId(s.id)
    setEditPrompt(s.prompt)
    setEditAgentId(s.agent_id)
    setEditInterval(String(s.interval_seconds))
  }

  const cancelEditing = () => {
    setEditingId(null)
  }

  const saveEditing = async (id: string) => {
    const res = await fetch(`/api/schedules/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: editPrompt,
        agent_id: editAgentId,
        interval_seconds: parseInt(editInterval) || 60,
      }),
    })
    if (res.ok) {
      setEditingId(null)
      fetchSchedules()
    }
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b px-4 py-2">
        <span className="text-sm font-medium">Schedules</span>
        <Button variant="outline" size="sm" onClick={fetchSchedules} disabled={loading}>
          <RefreshCw className={`mr-1.5 size-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>
      <div className="flex-1 overflow-auto">
        {schedules.length === 0 ? (
          <p className="p-4 text-sm text-muted-foreground">
            {loading
              ? "Loading..."
              : "No scheduled tasks. Ask an agent to monitor something to get started."}
          </p>
        ) : (
          <table className="w-full table-fixed text-sm">
            <thead>
              <tr className="border-b bg-muted/50 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                <th className="w-6 px-1 py-2" />
                <th className="w-[7%] px-2 py-2">ID</th>
                <th className="w-[10%] px-2 py-2">Agent</th>
                <th className="px-2 py-2">Prompt</th>
                <th className="w-[8%] px-2 py-2">Tools</th>
                <th className="w-[6%] px-2 py-2">Interval</th>
                <th className="w-[12%] px-2 py-2">Last Executed</th>
                <th className="w-[6%] px-2 py-2">Status</th>
                <th className="w-[12%] px-2 py-2">Created</th>
                <th className="w-[12%] px-2 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {schedules.map((s) => (
                <>
                  <tr
                    key={s.id}
                    className="border-b last:border-b-0 hover:bg-muted/30 cursor-pointer"
                    onClick={() =>
                      editingId !== s.id &&
                      setExpandedId(expandedId === s.id ? null : s.id)
                    }
                  >
                    <td className="px-1 py-2 text-muted-foreground">
                      {s.last_result ? (
                        expandedId === s.id ? (
                          <ChevronDown className="size-3.5" />
                        ) : (
                          <ChevronRight className="size-3.5" />
                        )
                      ) : null}
                    </td>
                    <td
                      className="truncate px-2 py-2 font-mono text-xs text-muted-foreground"
                      title={s.id}
                    >
                      {s.id.slice(0, 8)}
                    </td>
                    <td className="truncate px-2 py-2">
                      {editingId === s.id ? (
                        <Select value={editAgentId} onValueChange={setEditAgentId}>
                          <SelectTrigger className="h-7 text-xs">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {agents.map((a) => (
                              <SelectItem key={a.id} value={a.id}>
                                {a.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      ) : (
                        s.agent_name
                      )}
                    </td>
                    <td className="truncate px-2 py-2" title={s.prompt}>
                      {editingId === s.id ? (
                        <Input
                          value={editPrompt}
                          onChange={(e) => setEditPrompt(e.target.value)}
                          className="h-7 text-xs"
                          onClick={(e) => e.stopPropagation()}
                        />
                      ) : (
                        <span className="block truncate">{s.prompt}</span>
                      )}
                    </td>
                    <td className="truncate px-2 py-2 font-mono text-xs">
                      {s.allowed_tools.length > 0
                        ? s.allowed_tools.join(", ")
                        : "-"}
                    </td>
                    <td className="px-2 py-2 text-right font-mono">
                      {editingId === s.id ? (
                        <Input
                          value={editInterval}
                          onChange={(e) => setEditInterval(e.target.value)}
                          className="h-7 w-full text-xs text-right"
                          type="number"
                          onClick={(e) => e.stopPropagation()}
                        />
                      ) : (
                        s.interval_seconds
                      )}
                    </td>
                    <td className="truncate px-2 py-2 text-xs">
                      {s.last_executed_at ?? "-"}
                    </td>
                    <td className="px-2 py-2">
                      <Badge
                        variant={
                          s.status === "active" ? "default" : "secondary"
                        }
                      >
                        {s.status}
                      </Badge>
                    </td>
                    <td className="truncate px-2 py-2 text-xs">{s.created_at}</td>
                    <td
                      className="px-2 py-2"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <div className="flex items-center gap-1">
                        {editingId === s.id ? (
                          <>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => saveEditing(s.id)}
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
                              onClick={() => startEditing(s)}
                            >
                              <Pencil className="size-3.5" />
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => handleToggle(s.id, s.status)}
                            >
                              {s.status === "active" ? (
                                <Pause className="size-3.5" />
                              ) : (
                                <Play className="size-3.5" />
                              )}
                            </Button>
                            <Button
                              variant="destructive"
                              size="sm"
                              onClick={() => handleDelete(s.id)}
                            >
                              <Trash2 className="size-3.5" />
                            </Button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                  {expandedId === s.id && s.last_result && (
                    <tr key={`${s.id}-result`} className="border-b bg-muted/20">
                      <td colSpan={10} className="px-4 py-3">
                        <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-1">
                          Last Result
                        </div>
                        <pre className="whitespace-pre-wrap break-words text-sm leading-relaxed">
                          {s.last_result}
                        </pre>
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
