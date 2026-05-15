import { Fragment, useCallback, useEffect, useMemo, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  Activity,
  Clock,
  Copy,
  Eye,
  EyeOff,
  Info,
  Loader2,
  MoreHorizontal,
  Pause,
  Pencil,
  Play,
  Plus,
  Search,
  Timer,
  Trash2,
  X,
  Zap,
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
  full_context: boolean
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
  if (seconds <= 0) return "--"
  const mins = Math.floor(seconds / 60)
  if (mins < 60) return `${mins}m`
  const hours = Math.floor(mins / 60)
  const rem = mins % 60
  return rem > 0 ? `${hours}h ${rem}m` : `${hours}h`
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  if (diff < 0) return "just now"
  const secs = Math.floor(diff / 1000)
  if (secs < 60) return `${secs}s ago`
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
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

function triggerBadgeClass(type: string): string {
  switch (type) {
    case "interval":
      return "border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-400"
    case "webhook":
      return "border-orange-500/30 bg-orange-500/10 text-orange-700 dark:text-orange-400"
    case "file_watch":
      return "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400"
    case "github_pr":
    case "github_issues":
      return "border-purple-500/30 bg-purple-500/10 text-purple-700 dark:text-purple-400"
    case "slack_channel":
      return "border-green-500/30 bg-green-500/10 text-green-700 dark:text-green-400"
    default:
      return ""
  }
}

export function SchedulesView() {
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTriggerType, setEditTriggerType] = useState("")
  const [editPrompt, setEditPrompt] = useState("")
  const [editAgentId, setEditAgentId] = useState("")
  const [editInterval, setEditInterval] = useState("")
  const [editBaseInterval, setEditBaseInterval] = useState("")
  const [editMaxInterval, setEditMaxInterval] = useState("")
  const [editModel, setEditModel] = useState("")
  const [editFullContext, setEditFullContext] = useState(false)

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
  const [newFullContext, setNewFullContext] = useState(false)
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([])
  const [triggerTypes, setTriggerTypes] = useState<TriggerTypeOption[]>([])
  const [webhookInfo, setWebhookInfo] = useState<WebhookInfo | null>(null)
  const [showTriggerInfo, setShowTriggerInfo] = useState(false)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [triggeringId, setTriggeringId] = useState<string | null>(null)

  const [activeTab, setActiveTab] = useState("all")
  const [searchQuery, setSearchQuery] = useState("")

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
    const action = currentStatus === "enabled" ? "pause" : "resume"
    const res = await fetch(`/api/schedules/${id}/${action}`, { method: "POST" })
    if (res.ok) fetchSchedules()
  }

  const handleDeleteConfirm = async () => {
    if (!confirmDeleteId) return
    const res = await fetch(`/api/schedules/${confirmDeleteId}`, { method: "DELETE" })
    if (res.ok) fetchSchedules()
  }

  const handleRunNow = async (id: string) => {
    setTriggeringId(id)
    try {
      const res = await fetch(`/api/schedules/${id}/run`, { method: "POST" })
      if (res.ok) {
        setTimeout(fetchSchedules, 2000)
      }
    } finally {
      setTriggeringId(null)
    }
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
    setEditFullContext(s.full_context)
  }

  const cancelEditing = () => {
    setEditingId(null)
  }

  const saveEditing = async (id: string) => {
    const body: Record<string, unknown> = {
      prompt: editPrompt,
      agent_id: editAgentId,
      model: editModel || null,
      full_context: editFullContext,
    }

    body.interval_seconds = (parseInt(editInterval) || 1) * 60

    if (editTriggerType === "interval") {
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
    setNewFullContext(false)
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
        full_context: newFullContext,
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

  const activeCount = schedules.filter((s) => s.status === "enabled").length
  const pausedCount = schedules.filter((s) => s.status !== "enabled").length
  const recentRunCount = schedules.filter((s) => {
    if (!s.last_executed_at) return false
    return Date.now() - new Date(s.last_executed_at).getTime() < 24 * 60 * 60 * 1000
  }).length

  const filteredSchedules = useMemo(() => {
    let result = [...schedules].sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )
    if (activeTab === "active") result = result.filter((s) => s.status === "enabled")
    if (activeTab === "paused") result = result.filter((s) => s.status !== "enabled")
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      result = result.filter(
        (s) =>
          s.agent_name.toLowerCase().includes(q) ||
          s.prompt.toLowerCase().includes(q) ||
          triggerLabel(s.trigger_type).includes(q)
      )
    }
    return result
  }, [schedules, activeTab, searchQuery])

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">Schedules</h2>
            <p className="text-xs text-muted-foreground">
              Manage automated agent tasks and triggers
            </p>
          </div>
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <Plus className="mr-1 size-3.5" />
            New Schedule
          </Button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl space-y-5 p-5">
          {/* Stat Cards */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Card size="sm" className="gap-0">
              <CardContent className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-lg bg-muted">
                  <Timer className="size-4 text-muted-foreground" />
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Total</p>
                  <p className="text-xl font-semibold tracking-tight">{schedules.length}</p>
                </div>
              </CardContent>
            </Card>
            <Card size="sm" className="gap-0">
              <CardContent className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-lg bg-emerald-500/10">
                  <Activity className="size-4 text-emerald-600 dark:text-emerald-400" />
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Active</p>
                  <p className="text-xl font-semibold tracking-tight">{activeCount}</p>
                </div>
              </CardContent>
            </Card>
            <Card size="sm" className="gap-0">
              <CardContent className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-lg bg-muted">
                  <Pause className="size-4 text-muted-foreground" />
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Paused</p>
                  <p className="text-xl font-semibold tracking-tight">{pausedCount}</p>
                </div>
              </CardContent>
            </Card>
            <Card size="sm" className="gap-0">
              <CardContent className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-lg bg-blue-500/10">
                  <Clock className="size-4 text-blue-600 dark:text-blue-400" />
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Ran Today</p>
                  <p className="text-xl font-semibold tracking-tight">{recentRunCount}</p>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Tabs + Search */}
          <div className="flex items-center justify-between gap-4">
            <Tabs value={activeTab} onValueChange={setActiveTab}>
              <TabsList>
                <TabsTrigger value="all">
                  All
                  <Badge variant="secondary" className="ml-1 h-4 min-w-5 px-1 text-[10px]">
                    {schedules.length}
                  </Badge>
                </TabsTrigger>
                <TabsTrigger value="active">
                  Active
                  <Badge variant="secondary" className="ml-1 h-4 min-w-5 px-1 text-[10px]">
                    {activeCount}
                  </Badge>
                </TabsTrigger>
                <TabsTrigger value="paused">
                  Paused
                  <Badge variant="secondary" className="ml-1 h-4 min-w-5 px-1 text-[10px]">
                    {pausedCount}
                  </Badge>
                </TabsTrigger>
              </TabsList>
            </Tabs>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Search schedules..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-8 w-56 pl-8 text-sm"
              />
            </div>
          </div>

          {/* Data Table */}
          <div className="rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="pl-4">Agent</TableHead>
                  <TableHead>Trigger</TableHead>
                  <TableHead className="min-w-[180px]">Prompt</TableHead>
                  <TableHead>Every</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Last Activity</TableHead>
                  <TableHead className="w-10 pr-4"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading && schedules.length === 0 && (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={7} className="h-32 text-center">
                      <div className="flex items-center justify-center gap-2 text-muted-foreground">
                        <Loader2 className="size-4 animate-spin" />
                        <span className="text-sm">Loading schedules...</span>
                      </div>
                    </TableCell>
                  </TableRow>
                )}
                {!loading && filteredSchedules.length === 0 && (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={7} className="h-32 text-center">
                      <div className="flex flex-col items-center gap-1.5 text-muted-foreground">
                        <Timer className="size-8 opacity-30" />
                        <p className="text-sm">
                          {schedules.length === 0
                            ? "No scheduled tasks yet"
                            : "No schedules match your filters"}
                        </p>
                        {schedules.length === 0 && (
                          <p className="text-xs">
                            Click "New Schedule" or ask an agent to create one.
                          </p>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                )}
                {filteredSchedules.map((s) => (
                  <Fragment key={s.id}>
                    <TableRow>
                      {/* Agent */}
                      <TableCell className="pl-4">
                        <TooltipProvider>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <div className="flex flex-col gap-0.5">
                                <span className="text-sm font-medium">{s.agent_name}</span>
                                <div className="flex items-center gap-1.5">
                                  <span className="font-mono text-[10px] text-muted-foreground">
                                    {s.id.slice(0, 8)}
                                  </span>
                                  {s.model && (
                                    <Badge variant="outline" className="h-4 px-1 text-[10px] font-normal">
                                      {s.model}
                                    </Badge>
                                  )}
                                  {s.full_context && (
                                    <Badge variant="outline" className="h-4 px-1 text-[10px] font-normal">
                                      full ctx
                                    </Badge>
                                  )}
                                </div>
                              </div>
                            </TooltipTrigger>
                            <TooltipContent side="right">
                              <span>ID: {s.id}</span>
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      </TableCell>

                      {/* Trigger */}
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={`text-[11px] font-normal ${triggerBadgeClass(s.trigger_type)}`}
                        >
                          {triggerLabel(s.trigger_type)}
                        </Badge>
                      </TableCell>

                      {/* Prompt */}
                      <TableCell>
                        <TooltipProvider>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <p className="max-w-[280px] truncate text-sm text-muted-foreground">
                                {s.prompt}
                              </p>
                            </TooltipTrigger>
                            <TooltipContent side="bottom" className="max-w-sm">
                              <span className="whitespace-pre-wrap">{s.prompt}</span>
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      </TableCell>

                      {/* Interval */}
                      <TableCell>
                        <span className="font-mono text-xs text-muted-foreground">
                          {formatInterval(s.interval_seconds)}
                        </span>
                      </TableCell>

                      {/* Status */}
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <div
                            className={`size-2 rounded-full ${
                              s.status === "enabled"
                                ? "bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.4)]"
                                : "bg-muted-foreground/40"
                            }`}
                          />
                          <span className="text-xs">
                            {s.status === "enabled" ? "Active" : "Paused"}
                          </span>
                        </div>
                      </TableCell>

                      {/* Last Activity */}
                      <TableCell>
                        <div className="flex flex-col gap-0.5 text-xs text-muted-foreground">
                          {s.last_executed_at && (
                            <span>Ran {timeAgo(s.last_executed_at)}</span>
                          )}
                          {s.last_checked_at && (
                            <span>Checked {timeAgo(s.last_checked_at)}</span>
                          )}
                          {!s.last_executed_at && !s.last_checked_at && (
                            <span className="italic">Never</span>
                          )}
                        </div>
                      </TableCell>

                      {/* Actions */}
                      <TableCell className="pr-4">
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon-xs">
                              <MoreHorizontal className="size-3.5" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem
                              onClick={() => handleRunNow(s.id)}
                              disabled={triggeringId === s.id}
                            >
                              {triggeringId === s.id ? (
                                <Loader2 className="size-4 animate-spin" />
                              ) : (
                                <Zap className="size-4" />
                              )}
                              Run Now
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => startEditing(s)}>
                              <Pencil className="size-4" />
                              Edit
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => handleToggle(s.id, s.status)}>
                              {s.status === "enabled" ? (
                                <Pause className="size-4" />
                              ) : (
                                <Play className="size-4" />
                              )}
                              {s.status === "enabled" ? "Pause" : "Resume"}
                            </DropdownMenuItem>
                            {s.last_result && (
                              <DropdownMenuItem
                                onClick={() => setExpandedId(expandedId === s.id ? null : s.id)}
                              >
                                {expandedId === s.id ? (
                                  <EyeOff className="size-4" />
                                ) : (
                                  <Eye className="size-4" />
                                )}
                                {expandedId === s.id ? "Hide Result" : "View Result"}
                              </DropdownMenuItem>
                            )}
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              variant="destructive"
                              onClick={() => setConfirmDeleteId(s.id)}
                            >
                              <Trash2 className="size-4" />
                              Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </TableCell>
                    </TableRow>

                    {/* Expanded Result Row */}
                    {expandedId === s.id && s.last_result && (
                      <TableRow className="hover:bg-transparent">
                        <TableCell colSpan={7} className="bg-muted/30 px-6 py-4">
                          <div className="mb-2 flex items-center justify-between">
                            <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                              Last Result
                            </span>
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              onClick={() => setExpandedId(null)}
                            >
                              <X className="size-3" />
                            </Button>
                          </div>
                          <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-muted/50 p-3 text-sm leading-relaxed">
                            {s.last_result}
                          </pre>
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                ))}
              </TableBody>
            </Table>
          </div>

          {/* Footer stats */}
          {filteredSchedules.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Showing {filteredSchedules.length} of {schedules.length} schedule{schedules.length !== 1 ? "s" : ""}
            </p>
          )}
        </div>
      </div>

      {/* ── Create Schedule Dialog ── */}
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

                <div className="flex items-center gap-2.5">
                  <Switch
                    id="new-full-context"
                    size="sm"
                    checked={newFullContext}
                    onCheckedChange={setNewFullContext}
                  />
                  <Label htmlFor="new-full-context" className="text-xs cursor-pointer">
                    Full context (include memory, personality, and search results)
                  </Label>
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

      {/* ── Edit Schedule Dialog ── */}
      {editingSchedule && (
        <Dialog open onOpenChange={(open) => { if (!open) cancelEditing() }}>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <div className="flex items-center gap-2">
                <DialogTitle>Edit Schedule</DialogTitle>
                <Badge
                  variant="outline"
                  className={`text-[10px] ${triggerBadgeClass(editingSchedule.trigger_type)}`}
                >
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
              <div className="flex items-center gap-2.5">
                <Switch
                  id="edit-full-context"
                  size="sm"
                  checked={editFullContext}
                  onCheckedChange={setEditFullContext}
                />
                <Label htmlFor="edit-full-context" className="text-xs cursor-pointer">
                  Full context (include memory, personality, and search results)
                </Label>
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
