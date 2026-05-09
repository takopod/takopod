import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { ArrowLeft, Check, Pencil, Plus, RefreshCw, Trash2, X, MessageSquare } from "lucide-react"

interface SlackConfig {
  configured: boolean
  xoxc_token?: string
  d_cookie?: string
  member_id?: string
}

interface SlackStatus {
  connected: boolean
  team?: string
  user?: string
  url?: string
  error?: string
}

interface SlackChannel {
  id: string
  name: string
  is_private: boolean
}

interface PollingChannel {
  id: string
  channel_id: string
  channel_name: string
  interval_seconds: number
  enabled: boolean
}

interface MonitoredThread {
  id: string
  channel_id: string
  channel_name?: string
  thread_ts: string
  agent_id: string
  agent_name: string | null
  last_ts: string
  created_at: string
  poll_interval?: number
  last_activity_at?: string
}

interface PollingState {
  channels: PollingChannel[]
}

function formatThreadTs(ts: string): string {
  const epoch = parseFloat(ts)
  if (!epoch) return ts
  const d = new Date(epoch * 1000)
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  })
}

function slackThreadUrl(
  teamUrl: string,
  channelId: string,
  threadTs: string,
): string {
  const base = teamUrl.replace(/\/$/, "")
  const ts = threadTs.replace(".", "")
  return `${base}/archives/${channelId}/p${ts}`
}

function formatRelativeTime(iso: string): string {
  if (!iso || iso === "1970-01-01T00:00:00Z") return "never"
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

function formatPollInterval(seconds: number | undefined): string {
  if (seconds == null) return "--"
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  return `${(seconds / 3600).toFixed(1)}h`
}

function MonitoredThreadsSection({
  threads,
  deletingThread,
  slackTeamUrl,
  onDelete,
  onUpdateInterval,
  onRefresh,
}: {
  threads: MonitoredThread[]
  deletingThread: string | null
  slackTeamUrl: string
  onDelete: (id: string) => void
  onUpdateInterval: (id: string, interval: number) => void
  onRefresh: () => void
}) {
  const [filterAgent, setFilterAgent] = useState<string | null>(null)
  const [editingThread, setEditingThread] = useState<string | null>(null)
  const [editValue, setEditValue] = useState(0)

  const agentGroups = threads.reduce<
    Record<string, { name: string; count: number }>
  >((acc, t) => {
    const key = t.agent_id
    if (!acc[key]) acc[key] = { name: t.agent_name || t.agent_id, count: 0 }
    acc[key].count++
    return acc
  }, {})

  const filtered = filterAgent
    ? threads.filter((t) => t.agent_id === filterAgent)
    : threads

  return (
    <TooltipProvider>
      <div className="rounded-md border px-4 py-3">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MessageSquare className="size-3.5 text-muted-foreground" />
            <span className="text-sm font-medium">Monitored Threads</span>
            {threads.length > 0 && (
              <Badge variant="secondary" className="text-xs">
                {threads.length}
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon-sm" onClick={onRefresh}>
              <RefreshCw className="size-3" />
            </Button>
          </div>
        </div>

        {/* Agent filter chips */}
        {Object.keys(agentGroups).length > 1 && (
          <div className="mb-3 flex flex-wrap gap-1.5">
            <Badge
              variant={filterAgent === null ? "default" : "outline"}
              className="cursor-pointer text-xs"
              onClick={() => setFilterAgent(null)}
            >
              All ({threads.length})
            </Badge>
            {Object.entries(agentGroups).map(
              ([agentId, { name, count }]) => (
                <Badge
                  key={agentId}
                  variant={filterAgent === agentId ? "default" : "outline"}
                  className="cursor-pointer text-xs"
                  onClick={() =>
                    setFilterAgent(
                      filterAgent === agentId ? null : agentId,
                    )
                  }
                >
                  {name} ({count})
                </Badge>
              ),
            )}
          </div>
        )}

        {/* Thread table */}
        {filtered.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">Thread</TableHead>
                <TableHead className="text-xs">Agent</TableHead>
                <TableHead className="text-xs">Activity</TableHead>
                <TableHead className="text-xs">Polling</TableHead>
                <TableHead className="w-8" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((t) => (
                <TableRow key={t.id}>
                  <TableCell className="text-xs py-2">
                    {slackTeamUrl ? (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <a
                            href={slackThreadUrl(
                              slackTeamUrl,
                              t.channel_id,
                              t.thread_ts,
                            )}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="hover:underline"
                          >
                            {formatThreadTs(t.thread_ts)}
                          </a>
                        </TooltipTrigger>
                        <TooltipContent side="top" className="text-xs">
                          Open thread in Slack
                        </TooltipContent>
                      </Tooltip>
                    ) : (
                      <span>{formatThreadTs(t.thread_ts)}</span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs py-2 text-muted-foreground">
                    {t.agent_name || t.agent_id}
                  </TableCell>
                  <TableCell className="text-xs py-2">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span className="text-muted-foreground">
                          {formatRelativeTime(
                            t.last_activity_at || t.created_at,
                          )}
                        </span>
                      </TooltipTrigger>
                      <TooltipContent side="top" className="text-xs">
                        <div>Started: {t.created_at}</div>
                        {t.last_activity_at && (
                          <div>Last activity: {t.last_activity_at}</div>
                        )}
                      </TooltipContent>
                    </Tooltip>
                  </TableCell>
                  <TableCell className="text-xs py-2">
                    {editingThread === t.id ? (
                      <div className="flex items-center gap-1">
                        <Input
                          type="number"
                          min={10}
                          max={21600}
                          value={editValue}
                          onChange={(e) =>
                            setEditValue(parseInt(e.target.value) || 10)
                          }
                          className="w-16 h-7 text-xs text-center"
                          title="Poll interval (seconds)"
                          autoFocus
                        />
                        <span className="text-xs text-muted-foreground">
                          s
                        </span>
                      </div>
                    ) : (
                      <Badge
                        variant={
                          !t.poll_interval || t.poll_interval <= 10
                            ? "default"
                            : "secondary"
                        }
                        className="text-xs"
                      >
                        {formatPollInterval(t.poll_interval)}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="py-2">
                    <div className="flex items-center gap-0.5">
                      {editingThread === t.id ? (
                        <>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => {
                              const clamped = Math.max(
                                10,
                                Math.min(21600, editValue),
                              )
                              onUpdateInterval(t.id, clamped)
                              setEditingThread(null)
                            }}
                            className="text-muted-foreground hover:text-foreground"
                          >
                            <Check className="size-3" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => setEditingThread(null)}
                            className="text-muted-foreground hover:text-foreground"
                          >
                            <X className="size-3" />
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => {
                              setEditingThread(t.id)
                              setEditValue(t.poll_interval ?? 10)
                            }}
                            className="text-muted-foreground hover:text-foreground"
                          >
                            <Pencil className="size-3" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => onDelete(t.id)}
                            disabled={deletingThread === t.id}
                            className="text-muted-foreground hover:text-destructive"
                          >
                            <X className="size-3" />
                          </Button>
                        </>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <p className="py-2 text-xs text-muted-foreground">
            {threads.length === 0
              ? "No threads being monitored."
              : "No threads match the selected filter."}
          </p>
        )}
      </div>
    </TooltipProvider>
  )
}

export function SlackView() {
  const [config, setConfig] = useState<SlackConfig>({ configured: false })
  const [status, setStatus] = useState<SlackStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)

  // Polling state
  const [polling, setPolling] = useState<PollingState>({ channels: [] })
  const [slackChannels, setSlackChannels] = useState<SlackChannel[]>([])
  const [loadingChannels, setLoadingChannels] = useState(false)
  const [savingChannel, setSavingChannel] = useState(false)
  const [addingChannel, setAddingChannel] = useState(false)
  const [manualChannelId, setManualChannelId] = useState("")
  const [manualInterval, setManualInterval] = useState(30)
  const [threadTtlDays, setThreadTtlDays] = useState(7)

  // Monitored threads state
  const [threads, setThreads] = useState<MonitoredThread[]>([])
  const [deletingThread, setDeletingThread] = useState<string | null>(null)

  const [token, setToken] = useState("")
  const [cookie, setCookie] = useState("")
  const [memberId, setMemberId] = useState("")

  const fetchConfig = useCallback(async () => {
    const res = await fetch("/api/slack/config")
    if (res.ok) {
      const data = await res.json()
      setConfig(data)
      if (data.configured) {
        setMemberId(data.member_id || "")
      }
    }
  }, [])

  const fetchStatus = useCallback(async () => {
    setTesting(true)
    try {
      const res = await fetch("/api/slack/status")
      if (res.ok) setStatus(await res.json())
    } finally {
      setTesting(false)
    }
  }, [])

  const fetchPolling = useCallback(async () => {
    const res = await fetch("/api/slack/polling")
    if (res.ok) {
      setPolling(await res.json())
    }
  }, [])

  const fetchSlackChannels = useCallback(async () => {
    setLoadingChannels(true)
    try {
      const res = await fetch("/api/slack/channels")
      if (res.ok) {
        const data = await res.json()
        setSlackChannels(data.channels || [])
      }
    } finally {
      setLoadingChannels(false)
    }
  }, [])

  const fetchThreadTtl = useCallback(async () => {
    const res = await fetch("/api/settings")
    if (res.ok) {
      const data = await res.json()
      if (data.slack_thread_ttl_days !== undefined) {
        setThreadTtlDays(parseInt(data.slack_thread_ttl_days) || 7)
      }
    }
  }, [])

  const fetchThreads = useCallback(async () => {
    const res = await fetch("/api/slack/threads")
    if (res.ok) {
      const data = await res.json()
      setThreads(data.threads || [])
    }
  }, [])

  const handleDeleteThread = async (threadId: string) => {
    setDeletingThread(threadId)
    try {
      const res = await fetch(`/api/slack/threads/${threadId}`, {
        method: "DELETE",
      })
      if (res.ok) {
        const data = await res.json()
        setThreads(data.threads || [])
      }
    } finally {
      setDeletingThread(null)
    }
  }

  const handleUpdateThreadInterval = async (
    threadId: string,
    interval: number,
  ) => {
    const prev = threads
    setThreads((cur) =>
      cur.map((t) =>
        t.id === threadId ? { ...t, poll_interval: interval } : t,
      ),
    )
    try {
      const res = await fetch(`/api/slack/threads/${threadId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ poll_interval: interval }),
      })
      if (res.ok) {
        const data = await res.json()
        setThreads(data.threads || [])
      } else {
        setThreads(prev)
      }
    } catch {
      setThreads(prev)
    }
  }

  const handleSaveThreadTtl = async (days: number) => {
    setThreadTtlDays(days)
    await fetch("/api/settings/slack_thread_ttl_days", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value: String(days) }),
    })
  }

  const loadAll = useCallback(async () => {
    setLoading(true)
    try {
      await Promise.all([
        fetchConfig(),
        fetchPolling(),
        fetchThreadTtl(),
        fetchThreads(),
      ])
    } finally {
      setLoading(false)
    }
  }, [fetchConfig, fetchPolling, fetchThreadTtl, fetchThreads])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  useEffect(() => {
    if (config.configured) {
      fetchStatus()
      fetchSlackChannels()
    }
  }, [config.configured, fetchStatus, fetchSlackChannels])

  const handleSave = async () => {
    setSaving(true)
    try {
      const res = await fetch("/api/slack/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          xoxc_token: token,
          d_cookie: cookie,
          member_id: memberId,
        }),
      })
      if (res.ok) {
        setConfig(await res.json())
        setToken("")
        setCookie("")
        fetchStatus()
      }
    } finally {
      setSaving(false)
    }
  }

  const handleDisconnect = async () => {
    await fetch("/api/slack/config", { method: "DELETE" })
    setConfig({ configured: false })
    setStatus(null)
    setToken("")
    setCookie("")
    setMemberId("")
  }

  const handleAddChannel = async (channelId: string, channelName: string) => {
    setSavingChannel(true)
    try {
      const res = await fetch("/api/slack/polling/channels", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          channel_id: channelId,
          channel_name: channelName,
          interval_seconds: manualInterval,
        }),
      })
      if (res.ok) {
        setPolling(await res.json())
        setAddingChannel(false)
        setManualChannelId("")
        setManualInterval(30)
      }
    } finally {
      setSavingChannel(false)
    }
  }

  const handleUpdateChannelInterval = async (
    rowId: string,
    intervalSeconds: number,
  ) => {
    const res = await fetch(`/api/slack/polling/channels/${rowId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ interval_seconds: intervalSeconds }),
    })
    if (res.ok) setPolling(await res.json())
  }

  const handleToggleChannel = async (rowId: string, enabled: boolean) => {
    const prev = polling
    setPolling((p) => ({
      ...p,
      channels: p.channels.map((c) =>
        c.id === rowId ? { ...c, enabled } : c,
      ),
    }))
    try {
      const res = await fetch(`/api/slack/polling/channels/${rowId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      })
      if (res.ok) setPolling(await res.json())
      else setPolling(prev)
    } catch {
      setPolling(prev)
    }
  }

  const handleDeleteChannel = async (rowId: string) => {
    const res = await fetch(`/api/slack/polling/channels/${rowId}`, {
      method: "DELETE",
    })
    if (res.ok) setPolling(await res.json())
  }

  // Channels available to add (not already added)
  const addedChannelIds = new Set(polling.channels.map((c) => c.channel_id))
  const availableChannels = slackChannels.filter(
    (ch) => !addedChannelIds.has(ch.id),
  )

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b px-4 py-2">
        <div className="flex items-center gap-2">
          <Link to="/settings">
            <Button variant="ghost" size="icon-sm">
              <ArrowLeft className="size-3.5" />
            </Button>
          </Link>
          <span className="text-sm font-medium">Slack Integration</span>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={loadAll}
          disabled={loading}
        >
          <RefreshCw
            className={`size-3.5 ${loading ? "animate-spin" : ""}`}
          />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        <div className="mx-auto max-w-lg space-y-6">
          {/* Connection Status */}
          {config.configured && (
            <div className="rounded-md border px-4 py-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">Connection</span>
                <div className="flex items-center gap-2">
                  {status ? (
                    <Badge
                      variant={status.connected ? "default" : "destructive"}
                    >
                      {status.connected
                        ? `Connected as ${status.user}`
                        : "Disconnected"}
                    </Badge>
                  ) : (
                    <Badge variant="secondary">Checking...</Badge>
                  )}
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={fetchStatus}
                    disabled={testing}
                  >
                    <RefreshCw
                      className={`size-3 ${testing ? "animate-spin" : ""}`}
                    />
                  </Button>
                </div>
              </div>
              {status?.connected && status.team && (
                <div className="mt-1 text-xs text-muted-foreground">
                  Workspace: {status.team}
                </div>
              )}
              {status && !status.connected && status.error && (
                <div className="mt-1 text-xs text-destructive">
                  {status.error}
                </div>
              )}
              <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                <div>Token: {config.xoxc_token}</div>
                <div>Cookie: {config.d_cookie}</div>
                <div>Member ID: {config.member_id}</div>
              </div>
              <div className="mt-3 flex justify-end">
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={handleDisconnect}
                >
                  <Trash2 className="mr-1.5 size-3" />
                  Disconnect
                </Button>
              </div>
            </div>
          )}

          {/* Setup Form */}
          {!config.configured && (
            <div className="rounded-md border px-4 py-3">
              <div className="mb-3 text-sm font-medium">
                Connect Slack
              </div>
              <div className="space-y-3">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="slack-token" className="text-xs">
                    xoxc Token
                  </Label>
                  <Input
                    id="slack-token"
                    type="password"
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    placeholder="xoxc-..."
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="slack-cookie" className="text-xs">
                    d Cookie
                  </Label>
                  <Input
                    id="slack-cookie"
                    type="password"
                    value={cookie}
                    onChange={(e) => setCookie(e.target.value)}
                    placeholder="xoxd-..."
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="slack-member" className="text-xs">
                    Your Member ID
                  </Label>
                  <Input
                    id="slack-member"
                    value={memberId}
                    onChange={(e) => setMemberId(e.target.value)}
                    placeholder="U01234567"
                  />
                </div>
                <div className="text-xs text-muted-foreground">
                  To find these values: Open Slack in your browser, open
                  DevTools (F12), go to Application &gt; Cookies, copy the
                  &quot;d&quot; cookie value. For the token, look in Network
                  tab for any API call and find the &quot;token&quot; form
                  parameter starting with &quot;xoxc-&quot;. Your Member ID
                  is in your Slack profile.
                </div>
                <div className="flex justify-end">
                  <Button
                    size="sm"
                    onClick={handleSave}
                    disabled={saving || !token || !cookie || !memberId}
                  >
                    {saving ? "Saving..." : "Save & Connect"}
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* Channel Polling */}
          <div className="rounded-md border px-4 py-3">
            <div className="mb-3">
              <span className="text-sm font-medium">Channel Polling</span>
            </div>

            {/* Added channels list */}
            <div className="space-y-2">
              {polling.channels.map((ch) => (
                <div
                  key={ch.id}
                  className={`flex items-center gap-3 rounded-md border px-3 py-2 ${!ch.enabled ? "opacity-50" : ""}`}
                >
                  <button
                    type="button"
                    role="switch"
                    aria-checked={ch.enabled}
                    onClick={() => handleToggleChannel(ch.id, !ch.enabled)}
                    className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
                      ch.enabled ? "bg-primary" : "bg-muted"
                    }`}
                  >
                    <span
                      className={`pointer-events-none inline-block size-4 rounded-full bg-background shadow-sm ring-0 transition-transform ${
                        ch.enabled ? "translate-x-4" : "translate-x-0"
                      }`}
                    />
                  </button>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm truncate">
                      # {ch.channel_name || ch.channel_id}
                    </div>
                    {ch.channel_name && (
                      <div className="text-xs text-muted-foreground truncate">
                        {ch.channel_id}
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Input
                      type="number"
                      min={10}
                      max={300}
                      value={ch.interval_seconds}
                      onChange={(e) => {
                        const val = Math.max(10, Math.min(300, parseInt(e.target.value) || 30))
                        setPolling((prev) => ({
                          ...prev,
                          channels: prev.channels.map((c) =>
                            c.id === ch.id ? { ...c, interval_seconds: val } : c,
                          ),
                        }))
                      }}
                      onBlur={(e) => {
                        const val = Math.max(10, Math.min(300, parseInt(e.target.value) || 30))
                        handleUpdateChannelInterval(ch.id, val)
                      }}
                      className="w-16 h-7 text-xs text-center"
                      title="Polling interval (seconds)"
                    />
                    <span className="text-xs text-muted-foreground">sec</span>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => handleDeleteChannel(ch.id)}
                      className="text-muted-foreground hover:text-destructive"
                    >
                      <X className="size-3" />
                    </Button>
                  </div>
                </div>
              ))}

              {polling.channels.length === 0 && !addingChannel && (
                <p className="text-xs text-muted-foreground py-1">
                  No channels configured for polling.
                </p>
              )}
            </div>

            {/* Add channel form */}
            {addingChannel ? (
              <div className="mt-3 rounded-md border px-3 py-3 space-y-3">
                {/* Slack channel dropdown (only when configured) */}
                {config.configured && availableChannels.length > 0 && (
                  <div className="flex flex-col gap-1.5">
                    <Label className="text-xs">From Slack</Label>
                    <select
                      onChange={(e) => {
                        const ch = availableChannels.find(
                          (c) => c.id === e.target.value,
                        )
                        if (ch) handleAddChannel(ch.id, ch.name)
                      }}
                      disabled={loadingChannels || savingChannel}
                      className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                      value=""
                    >
                      <option value="">
                        {loadingChannels
                          ? "Loading channels..."
                          : "Select a channel"}
                      </option>
                      {availableChannels.map((ch) => (
                        <option key={ch.id} value={ch.id}>
                          # {ch.name}
                          {ch.is_private ? " (private)" : ""}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                {/* Divider when both options available */}
                {config.configured && availableChannels.length > 0 && (
                  <div className="flex items-center gap-3">
                    <div className="flex-1 border-t" />
                    <span className="text-xs text-muted-foreground">or</span>
                    <div className="flex-1 border-t" />
                  </div>
                )}

                {/* Manual channel ID input */}
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs">Channel ID</Label>
                  <div className="flex gap-2">
                    <Input
                      value={manualChannelId}
                      onChange={(e) => setManualChannelId(e.target.value)}
                      placeholder="C01234567"
                      className="flex-1"
                    />
                    <Input
                      type="number"
                      min={10}
                      max={300}
                      value={manualInterval}
                      onChange={(e) =>
                        setManualInterval(
                          Math.max(10, Math.min(300, parseInt(e.target.value) || 30)),
                        )
                      }
                      className="w-20"
                      title="Polling interval (seconds)"
                      placeholder="30"
                    />
                    <span className="flex items-center text-xs text-muted-foreground">
                      sec
                    </span>
                  </div>
                </div>

                <div className="flex justify-end gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setAddingChannel(false)
                      setManualChannelId("")
                      setManualInterval(30)
                    }}
                  >
                    Cancel
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => handleAddChannel(manualChannelId.trim(), "")}
                    disabled={savingChannel || !manualChannelId.trim()}
                  >
                    {savingChannel ? "Adding..." : "Add"}
                  </Button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setAddingChannel(true)}
                className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors"
              >
                <Plus className="size-3" />
                Add Channel
              </button>
            )}

            <p className="mt-3 text-xs text-muted-foreground">
              The orchestrator polls enabled channels for messages mentioning
              agents by name (e.g., Agent-Name: message). The agent processes
              the message and replies in a Slack thread.
            </p>

            {/* Thread expiry */}
            <div className="mt-3 flex items-center justify-between pt-3 border-t">
              <div>
                <div className="text-xs font-medium">Thread expiry</div>
                <div className="text-xs text-muted-foreground">
                  Auto-remove monitored threads with no activity
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Input
                  type="number"
                  min={0}
                  max={90}
                  value={threadTtlDays}
                  onChange={(e) => {
                    const val = Math.max(0, Math.min(90, parseInt(e.target.value) || 0))
                    handleSaveThreadTtl(val)
                  }}
                  className="w-16 h-7 text-xs text-center"
                  title="Thread TTL in days (0 = never expire)"
                />
                <span className="text-xs text-muted-foreground">days</span>
              </div>
            </div>
          </div>

          {/* Monitored Threads */}
          <MonitoredThreadsSection
            threads={threads}
            deletingThread={deletingThread}
            slackTeamUrl={status?.url || ""}
            onDelete={handleDeleteThread}
            onUpdateInterval={handleUpdateThreadInterval}
            onRefresh={fetchThreads}
          />
        </div>
      </div>
    </div>
  )
}
