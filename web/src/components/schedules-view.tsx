import { Fragment, useCallback, useEffect, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
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
  Copy,
  Pause,
  Pencil,
  Play,
  Plus,
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
  trigger_type: string
  last_executed_at: string | null
  last_result: string | null
  status: string
  created_at: string
}

interface Agent {
  id: string
  name: string
}

interface WebhookInfo {
  webhook_url: string
  webhook_secret: string
}

function formatInterval(seconds: number): string {
  if (seconds <= 0) return "-"
  const mins = Math.floor(seconds / 60)
  if (mins < 60) return `${mins}m`
  const hours = Math.floor(mins / 60)
  const rem = mins % 60
  return rem > 0 ? `${hours}h ${rem}m` : `${hours}h`
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

  const [showCreate, setShowCreate] = useState(false)
  const [saving, setSaving] = useState(false)
  const [createError, setCreateError] = useState("")
  const [newAgentId, setNewAgentId] = useState("")
  const [newTriggerType, setNewTriggerType] = useState("interval")
  const [newPrompt, setNewPrompt] = useState("")
  const [newIntervalMinutes, setNewIntervalMinutes] = useState("10")
  const [newWatchDir, setNewWatchDir] = useState("")
  const [newAllowedTools, setNewAllowedTools] = useState("")
  const [newBaseInterval, setNewBaseInterval] = useState("")
  const [newMaxInterval, setNewMaxInterval] = useState("")
  const [webhookInfo, setWebhookInfo] = useState<WebhookInfo | null>(null)

  const fetchSchedules = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch("/api/schedules")
      if (res.ok) {
        setSchedules(await res.json())
      }
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchAgents = useCallback(async () => {
    try {
      const res = await fetch("/api/agents")
      if (res.ok) {
        setAgents(await res.json())
      }
    } catch {
      // network error
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

  const resetCreateForm = () => {
    setNewAgentId("")
    setNewTriggerType("interval")
    setNewPrompt("")
    setNewIntervalMinutes("10")
    setNewWatchDir("")
    setNewAllowedTools("")
    setNewBaseInterval("")
    setNewMaxInterval("")
    setWebhookInfo(null)
    setCreateError("")
  }

  const handleCreate = async () => {
    if (!newAgentId || !newPrompt.trim()) return
    setSaving(true)
    setCreateError("")

    try {
      const body: Record<string, unknown> = {
        agent_id: newAgentId,
        prompt: newPrompt.trim(),
        trigger_type: newTriggerType,
      }

      if (newTriggerType === "interval") {
        body.interval_minutes = parseInt(newIntervalMinutes) || 10
      }
      if (newTriggerType === "file_watch") {
        body.watch_dir = newWatchDir.trim()
      }

      const tools = newAllowedTools
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean)
      if (tools.length > 0) body.allowed_tools = tools

      const base = parseInt(newBaseInterval)
      const max = parseInt(newMaxInterval)
      if (!isNaN(base) && !isNaN(max) && base > 0 && max > 0) {
        body.base_interval_minutes = base
        body.max_interval_minutes = max
      }

      const res = await fetch("/api/schedules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })

      if (res.ok) {
        const data = await res.json()
        if (data.webhook_url && data.webhook_secret) {
          setWebhookInfo({
            webhook_url: data.webhook_url,
            webhook_secret: data.webhook_secret,
          })
        } else {
          setShowCreate(false)
          resetCreateForm()
        }
        fetchSchedules()
      } else {
        const err = await res.json().catch(() => ({ detail: "Unknown error" }))
        setCreateError(err.detail || JSON.stringify(err))
      }
    } finally {
      setSaving(false)
    }
  }

  const triggerLabel = (t: string) => {
    if (t === "file_watch") return "file watch"
    return t
  }

  const hasPartialBackoff = Boolean(newBaseInterval) !== Boolean(newMaxInterval)
  const backoffValid =
    !newBaseInterval ||
    !newMaxInterval ||
    parseInt(newBaseInterval) < parseInt(newMaxInterval)

  const canSubmit =
    newAgentId &&
    newPrompt.trim() &&
    (newTriggerType !== "interval" || parseInt(newIntervalMinutes) >= 5) &&
    (newTriggerType !== "file_watch" || newWatchDir.trim()) &&
    !hasPartialBackoff &&
    backoffValid

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b px-4 py-2">
        <span className="text-sm font-medium">Schedules</span>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={fetchSchedules} disabled={loading}>
            <RefreshCw className={`mr-1.5 size-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
          <Button size="sm" onClick={() => { setShowCreate(true); setWebhookInfo(null) }} disabled={showCreate}>
            <Plus className="mr-1.5 size-3.5" />
            New Schedule
          </Button>
        </div>
      </div>
      <div className="flex-1 overflow-auto">
        {showCreate && (
          <div className="border-b bg-muted/10 p-4">
            <div className="mx-auto max-w-2xl">
              {webhookInfo ? (
                <div className="rounded-md border p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <span className="text-sm font-medium">Webhook Created</span>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => { setShowCreate(false); resetCreateForm() }}
                    >
                      <X className="size-4" />
                    </Button>
                  </div>
                  <p className="mb-3 text-xs text-muted-foreground">
                    Save the secret now -- it won't be shown again.
                  </p>
                  <div className="flex flex-col gap-3">
                    <div className="flex flex-col gap-1.5">
                      <Label className="text-xs">Webhook URL</Label>
                      <div className="flex items-center gap-2">
                        <code className="flex-1 rounded bg-muted px-2 py-1.5 text-xs break-all">
                          {webhookInfo.webhook_url}
                        </code>
                        <Button
                          variant="outline"
                          size="icon-sm"
                          onClick={() => navigator.clipboard.writeText(webhookInfo.webhook_url)}
                        >
                          <Copy className="size-3.5" />
                        </Button>
                      </div>
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label className="text-xs">Bearer Token</Label>
                      <div className="flex items-center gap-2">
                        <code className="flex-1 rounded bg-muted px-2 py-1.5 text-xs break-all">
                          {webhookInfo.webhook_secret}
                        </code>
                        <Button
                          variant="outline"
                          size="icon-sm"
                          onClick={() => navigator.clipboard.writeText(webhookInfo.webhook_secret)}
                        >
                          <Copy className="size-3.5" />
                        </Button>
                      </div>
                    </div>
                    <div className="flex justify-end pt-1">
                      <Button
                        size="sm"
                        onClick={() => { setShowCreate(false); resetCreateForm() }}
                      >
                        Done
                      </Button>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="rounded-md border p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <span className="text-sm font-medium">New Schedule</span>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => { setShowCreate(false); resetCreateForm() }}
                    >
                      <X className="size-4" />
                    </Button>
                  </div>
                  <div className="flex flex-col gap-3">
                    <div className="flex flex-col gap-1.5">
                      <Label className="text-xs">Agent</Label>
                      <Select value={newAgentId} onValueChange={setNewAgentId}>
                        <SelectTrigger className="h-9 text-sm">
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
                    </div>

                    <div className="flex flex-col gap-1.5">
                      <Label className="text-xs">Trigger Type</Label>
                      <Select value={newTriggerType} onValueChange={setNewTriggerType}>
                        <SelectTrigger className="h-9 text-sm">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="interval">Interval (recurring)</SelectItem>
                          <SelectItem value="file_watch">File Watch</SelectItem>
                          <SelectItem value="webhook">Webhook (HTTP POST)</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="flex flex-col gap-1.5">
                      <Label className="text-xs">Prompt</Label>
                      <Textarea
                        value={newPrompt}
                        onChange={(e) => setNewPrompt(e.target.value)}
                        placeholder="What should the agent do on each trigger?"
                        className="min-h-20 resize-none text-sm"
                      />
                    </div>

                    {newTriggerType === "interval" && (
                      <div className="flex flex-col gap-1.5">
                        <Label className="text-xs">Interval (minutes, min 5)</Label>
                        <Input
                          type="number"
                          min={5}
                          value={newIntervalMinutes}
                          onChange={(e) => setNewIntervalMinutes(e.target.value)}
                        />
                      </div>
                    )}

                    {newTriggerType === "file_watch" && (
                      <div className="flex flex-col gap-1.5">
                        <Label className="text-xs">Watch Directory (relative to workspace)</Label>
                        <Input
                          value={newWatchDir}
                          onChange={(e) => setNewWatchDir(e.target.value)}
                          placeholder="e.g. incoming/"
                        />
                      </div>
                    )}

                    {newTriggerType === "webhook" && (
                      <p className="text-xs text-muted-foreground">
                        A webhook URL and bearer token will be generated after creation.
                        Payload (up to 5000 chars) is appended to the prompt.
                      </p>
                    )}

                    <div className="flex flex-col gap-1.5">
                      <Label className="text-xs">Allowed Tools (comma-separated, optional)</Label>
                      <Input
                        value={newAllowedTools}
                        onChange={(e) => setNewAllowedTools(e.target.value)}
                        placeholder="e.g. read_file, web_search"
                      />
                    </div>

                    {newTriggerType === "interval" && (
                      <div className="flex flex-col gap-1.5">
                        <Label className="text-xs">Idle Backoff (optional)</Label>
                        <div className="flex items-center gap-2">
                          <Input
                            type="number"
                            min={5}
                            value={newBaseInterval}
                            onChange={(e) => setNewBaseInterval(e.target.value)}
                            placeholder="Base (min)"
                            className="flex-1"
                          />
                          <span className="text-xs text-muted-foreground">to</span>
                          <Input
                            type="number"
                            min={5}
                            value={newMaxInterval}
                            onChange={(e) => setNewMaxInterval(e.target.value)}
                            placeholder="Max (min)"
                            className="flex-1"
                          />
                        </div>
                        <p className="text-xs text-muted-foreground">
                          If idle, interval doubles up to max. signal_activity resets to base.
                        </p>
                      </div>
                    )}

                    {createError && (
                      <p className="text-xs text-destructive">{createError}</p>
                    )}

                    <div className="flex justify-end gap-2 pt-1">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => { setShowCreate(false); resetCreateForm() }}
                      >
                        Cancel
                      </Button>
                      <Button
                        size="sm"
                        onClick={handleCreate}
                        disabled={!canSubmit || saving}
                      >
                        {saving ? "Creating..." : "Create"}
                      </Button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {schedules.length === 0 && !showCreate ? (
          <p className="p-4 text-sm text-muted-foreground">
            {loading
              ? "Loading..."
              : "No scheduled tasks. Click \"New Schedule\" or ask an agent to create one."}
          </p>
        ) : (
          schedules.length > 0 && (
            <table className="w-full table-fixed text-sm">
              <thead>
                <tr className="border-b bg-muted/50 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  <th className="w-6 px-1 py-2" />
                  <th className="w-[7%] px-2 py-2">ID</th>
                  <th className="w-[10%] px-2 py-2">Agent</th>
                  <th className="w-[8%] px-2 py-2">Type</th>
                  <th className="px-2 py-2">Prompt</th>
                  <th className="w-[8%] px-2 py-2">Tools</th>
                  <th className="w-[6%] px-2 py-2">Interval</th>
                  <th className="w-[12%] px-2 py-2">Last Executed</th>
                  <th className="w-[6%] px-2 py-2">Status</th>
                  <th className="w-[10%] px-2 py-2">Created</th>
                  <th className="w-[10%] px-2 py-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {schedules.map((s) => (
                  <Fragment key={s.id}>
                    <tr
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
                      <td className="px-2 py-2">
                        <Badge variant="outline" className="text-[10px]">
                          {triggerLabel(s.trigger_type)}
                        </Badge>
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
                          formatInterval(s.interval_seconds)
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
                      <tr className="border-b bg-muted/20">
                        <td colSpan={11} className="px-4 py-3">
                          <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-1">
                            Last Result
                          </div>
                          <pre className="whitespace-pre-wrap break-words text-sm leading-relaxed">
                            {s.last_result}
                          </pre>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          )
        )}
      </div>
    </div>
  )
}
