import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { ArrowLeft, Plus, RefreshCw, Trash2, X } from "lucide-react"
import type { Agent } from "@/lib/types"

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
  error?: string
}

interface AgentSlack {
  agent: Agent
  enabled: boolean
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

interface PollingState {
  enabled: boolean
  channels: PollingChannel[]
}

export function SlackView() {
  const [config, setConfig] = useState<SlackConfig>({ configured: false })
  const [status, setStatus] = useState<SlackStatus | null>(null)
  const [agents, setAgents] = useState<AgentSlack[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [toggling, setToggling] = useState<string | null>(null)

  // Polling state
  const [polling, setPolling] = useState<PollingState>({ enabled: false, channels: [] })
  const [slackChannels, setSlackChannels] = useState<SlackChannel[]>([])
  const [loadingChannels, setLoadingChannels] = useState(false)
  const [savingPolling, setSavingPolling] = useState(false)
  const [addingChannel, setAddingChannel] = useState(false)
  const [manualChannelId, setManualChannelId] = useState("")
  const [manualInterval, setManualInterval] = useState(30)
  const [threadTtlDays, setThreadTtlDays] = useState(7)

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

  const fetchAgents = useCallback(async () => {
    const res = await fetch("/api/agents")
    if (!res.ok) return
    const agentList: Agent[] = await res.json()
    setAgents(
      agentList.map((agent) => ({
        agent,
        enabled: agent.slack_enabled ?? false,
      })),
    )
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
      await Promise.all([fetchConfig(), fetchAgents(), fetchPolling(), fetchThreadTtl()])
    } finally {
      setLoading(false)
    }
  }, [fetchConfig, fetchAgents, fetchPolling, fetchThreadTtl])

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

  const handleTogglePolling = async () => {
    setSavingPolling(true)
    try {
      const res = await fetch("/api/slack/polling", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !polling.enabled }),
      })
      if (res.ok) setPolling(await res.json())
    } finally {
      setSavingPolling(false)
    }
  }

  const handleAddChannel = async (channelId: string, channelName: string) => {
    setSavingPolling(true)
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
      setSavingPolling(false)
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

  const handleDeleteChannel = async (rowId: string) => {
    const res = await fetch(`/api/slack/polling/channels/${rowId}`, {
      method: "DELETE",
    })
    if (res.ok) setPolling(await res.json())
  }

  const handleToggleAgent = async (agentId: string, currentEnabled: boolean) => {
    setToggling(agentId)
    try {
      const res = await fetch(`/api/agents/${agentId}/slack`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !currentEnabled }),
      })
      if (res.ok) {
        setAgents((prev) =>
          prev.map((a) =>
            a.agent.id === agentId ? { ...a, enabled: !currentEnabled } : a,
          ),
        )
      }
    } finally {
      setToggling(null)
    }
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

          {/* Per-Agent Toggle */}
          <div className="rounded-md border px-4 py-3">
            <div className="mb-3 text-sm font-medium">Agent Access</div>
            {agents.length === 0 && !loading && (
              <p className="text-xs text-muted-foreground">
                No agents found.
              </p>
            )}
            <div className="space-y-2">
              {agents.map(({ agent, enabled }) => (
                <div
                  key={agent.id}
                  className="flex items-center justify-between rounded-md border px-3 py-2"
                >
                  <div>
                    <div className="text-sm">{agent.name}</div>
                    <div className="text-xs text-muted-foreground">
                      {agent.agent_type}
                    </div>
                  </div>
                  <button
                    onClick={() => handleToggleAgent(agent.id, enabled)}
                    disabled={
                      !config.configured || toggling === agent.id
                    }
                    className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
                      enabled ? "bg-primary" : "bg-muted"
                    } ${!config.configured || toggling === agent.id ? "opacity-50 cursor-not-allowed" : ""}`}
                    title={
                      !config.configured
                        ? "Configure Slack credentials first"
                        : enabled
                          ? "Disable Slack for this agent"
                          : "Enable Slack for this agent"
                    }
                  >
                    <span
                      className={`pointer-events-none inline-block size-5 rounded-full bg-background shadow-sm ring-0 transition-transform ${
                        enabled ? "translate-x-5" : "translate-x-0"
                      }`}
                    />
                  </button>
                </div>
              ))}
            </div>
            {config.configured && agents.length > 0 && (
              <p className="mt-2 text-xs text-muted-foreground">
                Agents with Slack enabled will have access to read channels
                and send notes to yourself. Restart the agent&apos;s worker
                after toggling for changes to take effect.
              </p>
            )}
          </div>

          {/* Channel Polling */}
          <div className="rounded-md border px-4 py-3">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-medium">Channel Polling</span>
              <button
                onClick={handleTogglePolling}
                disabled={savingPolling}
                className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
                  polling.enabled ? "bg-primary" : "bg-muted"
                } ${savingPolling ? "opacity-50" : ""}`}
              >
                <span
                  className={`pointer-events-none inline-block size-5 rounded-full bg-background shadow-sm ring-0 transition-transform ${
                    polling.enabled ? "translate-x-5" : "translate-x-0"
                  }`}
                />
              </button>
            </div>

            {/* Added channels list */}
            <div className="space-y-2">
              {polling.channels.map((ch) => (
                <div
                  key={ch.id}
                  className="flex items-center gap-3 rounded-md border px-3 py-2"
                >
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
                        // Optimistic update
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
                      disabled={loadingChannels || savingPolling}
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
                    disabled={savingPolling || !manualChannelId.trim()}
                  >
                    {savingPolling ? "Adding..." : "Add"}
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
              When enabled, the orchestrator polls added channels for messages
              mentioning agents by name (e.g., @Agent-Name). The agent
              processes the message and replies in a Slack thread.
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
        </div>
      </div>
    </div>
  )
}
