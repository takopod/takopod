import { useCallback, useEffect, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
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
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  ChevronDown,
  ChevronRight,
  Copy,
  Info,
  Pause,
  Pencil,
  Play,
  Plus,
  Trash2,
  X,
} from "lucide-react"

interface Schedule {
  id: string
  agent_id: string
  agent_name: string
  prompt: string
  interval_seconds: number
  trigger_type: string
  base_interval_seconds: number | null
  max_interval_seconds: number | null
  last_executed_at: string | null
  last_checked_at: string | null
  last_result: string | null
  status: string
  created_at: string
  model: string | null
}

interface TriggerTypeOption {
  value: string
  label: string
}

interface ModelOption {
  value: string
  label: string
  model_id: string
  effort: string
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

function triggerLabel(t: string): string {
  const labels: Record<string, string> = {
    file_watch: "file watch",
    github_pr: "github pr",
    github_issues: "github issues",
    slack_channel: "slack channel",
  }
  return labels[t] || t
}

export function SchedulesView() {
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTriggerType, setEditTriggerType] = useState("")
  const [editPrompt, setEditPrompt] = useState("")
  const [editAgentId, setEditAgentId] = useState("")
  const [editInterval, setEditInterval] = useState("")
  const [editBaseInterval, setEditBaseInterval] = useState("")
  const [editMaxInterval, setEditMaxInterval] = useState("")
  const [editModel, setEditModel] = useState("")

  const [showCreate, setShowCreate] = useState(false)
  const [saving, setSaving] = useState(false)
  const [createError, setCreateError] = useState("")
  const [newAgentId, setNewAgentId] = useState("")
  const [newTriggerType, setNewTriggerType] = useState("interval")
  const [newPrompt, setNewPrompt] = useState("")
  const [newIntervalMinutes, setNewIntervalMinutes] = useState("10")
  const [newWatchDir, setNewWatchDir] = useState("")
  const [newBaseInterval, setNewBaseInterval] = useState("")
  const [newMaxInterval, setNewMaxInterval] = useState("")
  const [newModel, setNewModel] = useState("")
  const [newGithubRepo, setNewGithubRepo] = useState("")
  const [newGithubPrNumber, setNewGithubPrNumber] = useState("")
  const [newGithubLabels, setNewGithubLabels] = useState("")
  const [newGithubState, setNewGithubState] = useState("open")
  const [newSlackChannelId, setNewSlackChannelId] = useState("")
  const [newSlackChannelName, setNewSlackChannelName] = useState("")
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([])
  const [triggerTypes, setTriggerTypes] = useState<TriggerTypeOption[]>([])
  const [webhookInfo, setWebhookInfo] = useState<WebhookInfo | null>(null)
  const [showTriggerInfo, setShowTriggerInfo] = useState(false)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

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
    fetch("/api/models").then(r => r.ok ? r.json() : []).then(setModelOptions)
    fetch("/api/schedules/trigger-types").then(r => r.ok ? r.json() : []).then(setTriggerTypes)
  }, [fetchSchedules, fetchAgents])

  const handleToggle = async (id: string, currentStatus: string) => {
    const action = currentStatus === "active" ? "pause" : "resume"
    const res = await fetch(`/api/schedules/${id}/${action}`, { method: "POST" })
    if (res.ok) fetchSchedules()
  }

  const handleDeleteConfirm = async () => {
    if (!confirmDeleteId) return
    const res = await fetch(`/api/schedules/${confirmDeleteId}`, { method: "DELETE" })
    if (res.ok) fetchSchedules()
  }

  const startEditing = (s: Schedule) => {
    setEditingId(s.id)
    setEditTriggerType(s.trigger_type)
    setEditPrompt(s.prompt)
    setEditAgentId(s.agent_id)
    setEditInterval(String(Math.floor(s.interval_seconds / 60)))
    setEditBaseInterval(s.base_interval_seconds ? String(Math.floor(s.base_interval_seconds / 60)) : "")
    setEditMaxInterval(s.max_interval_seconds ? String(Math.floor(s.max_interval_seconds / 60)) : "")
    setEditModel(s.model || "")
  }

  const cancelEditing = () => {
    setEditingId(null)
  }

  const saveEditing = async (id: string) => {
    const body: Record<string, unknown> = {
      prompt: editPrompt,
      agent_id: editAgentId,
      model: editModel || null,
    }

    if (editTriggerType === "interval") {
      body.interval_seconds = (parseInt(editInterval) || 1) * 60

      const base = parseInt(editBaseInterval)
      const max = parseInt(editMaxInterval)
      body.base_interval_seconds = !isNaN(base) && base > 0 ? base * 60 : null
      body.max_interval_seconds = !isNaN(max) && max > 0 ? max * 60 : null
    }

    const res = await fetch(`/api/schedules/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
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
    setNewBaseInterval("")
    setNewMaxInterval("")
    setNewModel("")
    setNewGithubRepo("")
    setNewGithubPrNumber("")
    setNewGithubLabels("")
    setNewGithubState("open")
    setNewSlackChannelId("")
    setNewSlackChannelName("")
    setWebhookInfo(null)
    setCreateError("")
    setShowTriggerInfo(false)
  }

  const closeCreateDialog = () => {
    setShowCreate(false)
    resetCreateForm()
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
        model: newModel || null,
      }

      const isChecker = ["file_watch", "github_pr", "github_issues", "slack_channel"].includes(newTriggerType)

      if (newTriggerType === "interval" || isChecker) {
        body.interval_minutes = parseInt(newIntervalMinutes) || (isChecker ? 5 : 10)
      }
      if (newTriggerType === "file_watch") {
        body.watch_dir = newWatchDir.trim()
      }
      if (newTriggerType === "github_pr") {
        body.github_repo = newGithubRepo.trim()
        if (newGithubPrNumber) {
          body.github_pr_number = parseInt(newGithubPrNumber)
        } else {
          if (newGithubLabels.trim()) {
            body.github_labels = newGithubLabels.split(",").map((l: string) => l.trim()).filter(Boolean)
          }
          if (newGithubState !== "open") {
            body.github_state = newGithubState
          }
        }
      }
      if (newTriggerType === "github_issues") {
        body.github_repo = newGithubRepo.trim()
        if (newGithubLabels.trim()) {
          body.github_labels = newGithubLabels.split(",").map((l: string) => l.trim()).filter(Boolean)
        }
        if (newGithubState !== "open") {
          body.github_state = newGithubState
        }
      }
      if (newTriggerType === "slack_channel") {
        body.slack_channel_id = newSlackChannelId.trim()
        if (newSlackChannelName.trim()) {
          body.slack_channel_name = newSlackChannelName.trim()
        }
      }

      if (!isChecker) {
        const base = parseInt(newBaseInterval)
        const max = parseInt(newMaxInterval)
        if (!isNaN(base) && !isNaN(max) && base > 0 && max > 0) {
          body.base_interval_minutes = base
          body.max_interval_minutes = max
        }
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
          closeCreateDialog()
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

  const hasPartialBackoff = Boolean(newBaseInterval) !== Boolean(newMaxInterval)
  const backoffValid =
    !newBaseInterval ||
    !newMaxInterval ||
    parseInt(newBaseInterval) < parseInt(newMaxInterval)

  const needsInterval = newTriggerType !== "webhook"
  const canSubmit =
    newAgentId &&
    newPrompt.trim() &&
    (!needsInterval || parseInt(newIntervalMinutes) >= 5) &&
    (newTriggerType !== "file_watch" || newWatchDir.trim()) &&
    (newTriggerType !== "github_pr" || newGithubRepo.trim()) &&
    (newTriggerType !== "github_issues" || newGithubRepo.trim()) &&
    (newTriggerType !== "slack_channel" || newSlackChannelId.trim()) &&
    !hasPartialBackoff &&
    backoffValid

  const editingSchedule = schedules.find((s) => s.id === editingId)

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b px-4 py-2">
        <span className="text-sm font-medium">Schedules</span>
        <Button size="sm" onClick={() => setShowCreate(true)}>
          <Plus className="mr-1.5 size-3.5" />
          New Schedule
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        <div className="mx-auto max-w-3xl flex flex-col gap-3">
          {schedules.length === 0 && (
            <p className="text-sm text-muted-foreground">
              {loading
                ? "Loading..."
                : "No scheduled tasks. Click \"New Schedule\" or ask an agent to create one."}
            </p>
          )}

          {schedules.map((s) => (
            <div key={s.id} className="rounded-md border px-4 py-3">
              <div className="flex items-start justify-between gap-3">
                <div className="flex flex-col gap-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium">{s.agent_name}</span>
                    <Badge variant="outline" className="text-[10px]">
                      {triggerLabel(s.trigger_type)}
                    </Badge>
                    <Badge variant={s.status === "active" ? "default" : "secondary"}>
                      {s.status}
                    </Badge>
                    {s.interval_seconds > 0 && (
                      <span className="text-xs text-muted-foreground font-mono">
                        every {formatInterval(s.interval_seconds)}
                      </span>
                    )}
                    {s.model && (
                      <span className="text-xs text-muted-foreground font-mono">
                        {s.model}
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-muted-foreground line-clamp-2">{s.prompt}</p>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    <span className="font-mono">{s.id.slice(0, 8)}</span>
                    {s.last_checked_at && (
                      <span>last checked: {s.last_checked_at}</span>
                    )}
                    {s.last_executed_at && (
                      <span>last run: {s.last_executed_at}</span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => startEditing(s)}
                  >
                    <Pencil className="size-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => handleToggle(s.id, s.status)}
                  >
                    {s.status === "active" ? (
                      <Pause className="size-3.5" />
                    ) : (
                      <Play className="size-3.5" />
                    )}
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => setConfirmDeleteId(s.id)}
                  >
                    <Trash2 className="size-3.5 text-destructive" />
                  </Button>
                  {s.last_result && (
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => setExpandedId(expandedId === s.id ? null : s.id)}
                    >
                      {expandedId === s.id ? (
                        <ChevronDown className="size-3.5" />
                      ) : (
                        <ChevronRight className="size-3.5" />
                      )}
                    </Button>
                  )}
                </div>
              </div>
              {expandedId === s.id && s.last_result && (
                <div className="mt-3 border-t pt-3">
                  <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-1">
                    Last Result
                  </div>
                  <pre className="whitespace-pre-wrap break-words text-sm leading-relaxed">
                    {s.last_result}
                  </pre>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Create Schedule Dialog */}
      <Dialog open={showCreate} onOpenChange={(open) => { if (!open) closeCreateDialog() }}>
        <DialogContent className="sm:max-w-lg">
          {webhookInfo ? (
            <>
              <DialogHeader>
                <DialogTitle>Webhook Created</DialogTitle>
              </DialogHeader>
              <p className="text-xs text-muted-foreground">
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
              </div>
              <DialogFooter>
                <Button size="sm" onClick={closeCreateDialog}>
                  Done
                </Button>
              </DialogFooter>
            </>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle>New Schedule</DialogTitle>
              </DialogHeader>
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
                  <div className="flex items-center gap-1">
                    <Label className="text-xs">Trigger Type</Label>
                    <button
                      type="button"
                      onClick={() => setShowTriggerInfo(!showTriggerInfo)}
                      className="inline-flex cursor-pointer"
                    >
                      <Info className="size-3 text-muted-foreground" />
                    </button>
                  </div>
                  {showTriggerInfo && (
                    <div className="rounded-md border bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
                      <div className="flex items-start justify-between gap-2">
                        <ul className="flex flex-col gap-1 list-disc pl-3.5">
                          <li><strong>Interval</strong> -- runs on a timer, always invokes the agent</li>
                          <li><strong>Webhook</strong> -- triggered by HTTP POST, always invokes the agent</li>
                          <li><strong>File Watch</strong> -- checks for new files, invokes agent only when changes detected</li>
                          <li><strong>GitHub PR</strong> -- watches a single PR or all PRs in a repo, invokes agent only on new activity</li>
                          <li><strong>GitHub Issues</strong> -- polls issues by label/state, invokes agent only for new matches</li>
                          <li><strong>Slack Channel</strong> -- reads new messages, invokes agent only when messages found</li>
                        </ul>
                        <button type="button" onClick={() => setShowTriggerInfo(false)} className="shrink-0 mt-0.5">
                          <X className="size-3 text-muted-foreground" />
                        </button>
                      </div>
                    </div>
                  )}
                  <Select value={newTriggerType} onValueChange={setNewTriggerType}>
                    <SelectTrigger className="h-9 text-sm">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {triggerTypes.map((tt) => (
                        <SelectItem key={tt.value} value={tt.value}>
                          {tt.label}
                        </SelectItem>
                      ))}
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

                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs">Model</Label>
                  <Select value={newModel || "__default__"} onValueChange={(v) => setNewModel(v === "__default__" ? "" : v)}>
                    <SelectTrigger className="h-9 text-sm">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__default__">Default (agent default)</SelectItem>
                      {modelOptions.map((m) => (
                        <SelectItem key={m.value} value={m.value}>
                          {m.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {newTriggerType !== "webhook" && (
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

                {newTriggerType === "github_pr" && (
                  <>
                    <div className="flex flex-col gap-1.5">
                      <Label className="text-xs">Repository (owner/repo)</Label>
                      <Input
                        value={newGithubRepo}
                        onChange={(e) => setNewGithubRepo(e.target.value)}
                        placeholder="e.g. octocat/hello-world"
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label className="text-xs">PR Number (optional -- leave empty to watch all PRs)</Label>
                      <Input
                        type="number"
                        min={1}
                        value={newGithubPrNumber}
                        onChange={(e) => setNewGithubPrNumber(e.target.value)}
                        placeholder="e.g. 42"
                      />
                    </div>
                    {!newGithubPrNumber && (
                      <>
                        <div className="flex flex-col gap-1.5">
                          <Label className="text-xs">Labels (comma-separated, optional)</Label>
                          <Input
                            value={newGithubLabels}
                            onChange={(e) => setNewGithubLabels(e.target.value)}
                            placeholder="e.g. bug, needs-review"
                          />
                        </div>
                        <div className="flex flex-col gap-1.5">
                          <Label className="text-xs">State</Label>
                          <Select value={newGithubState} onValueChange={setNewGithubState}>
                            <SelectTrigger className="h-9 text-sm">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="open">Open</SelectItem>
                              <SelectItem value="closed">Closed</SelectItem>
                              <SelectItem value="all">All</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                      </>
                    )}
                  </>
                )}

                {newTriggerType === "github_issues" && (
                  <>
                    <div className="flex flex-col gap-1.5">
                      <Label className="text-xs">Repository (owner/repo)</Label>
                      <Input
                        value={newGithubRepo}
                        onChange={(e) => setNewGithubRepo(e.target.value)}
                        placeholder="e.g. octocat/hello-world"
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label className="text-xs">Labels (comma-separated, optional)</Label>
                      <Input
                        value={newGithubLabels}
                        onChange={(e) => setNewGithubLabels(e.target.value)}
                        placeholder="e.g. bug, critical"
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label className="text-xs">State</Label>
                      <Select value={newGithubState} onValueChange={setNewGithubState}>
                        <SelectTrigger className="h-9 text-sm">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="open">Open</SelectItem>
                          <SelectItem value="closed">Closed</SelectItem>
                          <SelectItem value="all">All</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </>
                )}

                {newTriggerType === "slack_channel" && (
                  <>
                    <div className="flex flex-col gap-1.5">
                      <Label className="text-xs">Channel ID</Label>
                      <Input
                        value={newSlackChannelId}
                        onChange={(e) => setNewSlackChannelId(e.target.value)}
                        placeholder="e.g. C1234567890"
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label className="text-xs">Channel Name (optional)</Label>
                      <Input
                        value={newSlackChannelName}
                        onChange={(e) => setNewSlackChannelName(e.target.value)}
                        placeholder="e.g. engineering"
                      />
                    </div>
                  </>
                )}

                {newTriggerType === "webhook" && (
                  <p className="text-xs text-muted-foreground">
                    A webhook URL and bearer token will be generated after creation.
                    Payload (up to 5000 chars) is appended to the prompt.
                  </p>
                )}

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
              </div>
              <DialogFooter>
                <Button variant="outline" size="sm" onClick={closeCreateDialog}>
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={handleCreate}
                  disabled={!canSubmit || saving}
                >
                  {saving ? "Creating..." : "Create"}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* Edit Schedule Dialog */}
      {editingSchedule && (
        <Dialog open onOpenChange={(open) => { if (!open) cancelEditing() }}>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <div className="flex items-center gap-2">
                <DialogTitle>Edit Schedule</DialogTitle>
                <Badge variant="outline" className="text-[10px]">
                  {triggerLabel(editingSchedule.trigger_type)}
                </Badge>
              </div>
            </DialogHeader>
            <div className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs">Agent</Label>
                <Select value={editAgentId} onValueChange={setEditAgentId}>
                  <SelectTrigger className="h-9 text-sm">
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
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs">Prompt</Label>
                <Textarea
                  value={editPrompt}
                  onChange={(e) => setEditPrompt(e.target.value)}
                  className="min-h-20 resize-none text-sm"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs">Model</Label>
                <Select value={editModel || "__default__"} onValueChange={(v) => setEditModel(v === "__default__" ? "" : v)}>
                  <SelectTrigger className="h-9 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__default__">Default (agent default)</SelectItem>
                    {modelOptions.map((m) => (
                      <SelectItem key={m.value} value={m.value}>
                        {m.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {editTriggerType !== "webhook" && (
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs">Interval (minutes, min 5)</Label>
                  <Input
                    type="number"
                    min={5}
                    value={editInterval}
                    onChange={(e) => setEditInterval(e.target.value)}
                  />
                </div>
              )}
              {editTriggerType === "interval" && (
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs">Idle Backoff (optional, minutes)</Label>
                  <div className="flex items-center gap-2">
                    <Input
                      type="number"
                      value={editBaseInterval}
                      onChange={(e) => setEditBaseInterval(e.target.value)}
                      placeholder="Base"
                      className="flex-1"
                    />
                    <span className="text-xs text-muted-foreground">to</span>
                    <Input
                      type="number"
                      value={editMaxInterval}
                      onChange={(e) => setEditMaxInterval(e.target.value)}
                      placeholder="Max"
                      className="flex-1"
                    />
                  </div>
                  <p className="text-xs text-muted-foreground">
                    If idle, interval doubles up to max. signal_activity resets to base.
                  </p>
                </div>
              )}
            </div>
            <DialogFooter>
              <Button variant="outline" size="sm" onClick={cancelEditing}>
                Cancel
              </Button>
              <Button size="sm" onClick={() => saveEditing(editingSchedule.id)}>
                Save
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}

      <ConfirmDialog
        open={confirmDeleteId !== null}
        onOpenChange={(open) => { if (!open) setConfirmDeleteId(null) }}
        title="Delete schedule"
        description="Delete this scheduled task? This cannot be undone."
        confirmLabel="Delete"
        destructive
        onConfirm={handleDeleteConfirm}
      />
    </div>
  )
}
