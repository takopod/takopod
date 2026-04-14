import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { ArrowLeft, RefreshCw, Trash2 } from "lucide-react"
import type { Agent } from "@/lib/types"

interface GitHubConfig {
  configured: boolean
  personal_access_token?: string
}

interface GitHubStatus {
  connected: boolean
  username?: string
  scopes?: string
  error?: string
}

interface AgentGitHub {
  agent: Agent
  enabled: boolean
}

export function GitHubView() {
  const [config, setConfig] = useState<GitHubConfig>({ configured: false })
  const [status, setStatus] = useState<GitHubStatus | null>(null)
  const [agents, setAgents] = useState<AgentGitHub[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [toggling, setToggling] = useState<string | null>(null)

  const [token, setToken] = useState("")

  const fetchConfig = useCallback(async () => {
    const res = await fetch("/api/github/config")
    if (res.ok) {
      const data = await res.json()
      setConfig(data)
    }
  }, [])

  const fetchStatus = useCallback(async () => {
    setTesting(true)
    try {
      const res = await fetch("/api/github/status")
      if (res.ok) setStatus(await res.json())
    } finally {
      setTesting(false)
    }
  }, [])

  const fetchAgents = useCallback(async () => {
    const res = await fetch("/api/agents")
    if (!res.ok) return
    const agentList: Agent[] = await res.json()
    const withStatus = await Promise.all(
      agentList.map(async (agent) => {
        try {
          const r = await fetch(`/api/agents/${agent.id}/github`)
          if (r.ok) {
            const data = await r.json()
            return { agent, enabled: data.enabled as boolean }
          }
        } catch { /* ignore */ }
        return { agent, enabled: false }
      }),
    )
    setAgents(withStatus)
  }, [])

  const loadAll = useCallback(async () => {
    setLoading(true)
    try {
      await Promise.all([fetchConfig(), fetchAgents()])
    } finally {
      setLoading(false)
    }
  }, [fetchConfig, fetchAgents])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  useEffect(() => {
    if (config.configured) fetchStatus()
  }, [config.configured, fetchStatus])

  const handleSave = async () => {
    setSaving(true)
    try {
      const res = await fetch("/api/github/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ personal_access_token: token }),
      })
      if (res.ok) {
        setConfig(await res.json())
        setToken("")
        fetchStatus()
      }
    } finally {
      setSaving(false)
    }
  }

  const handleDisconnect = async () => {
    await fetch("/api/github/config", { method: "DELETE" })
    setConfig({ configured: false })
    setStatus(null)
    setToken("")
  }

  const handleToggleAgent = async (agentId: string, currentEnabled: boolean) => {
    setToggling(agentId)
    try {
      const res = await fetch(`/api/agents/${agentId}/github`, {
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

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b px-4 py-2">
        <div className="flex items-center gap-2">
          <Link to="/settings">
            <Button variant="ghost" size="icon-sm">
              <ArrowLeft className="size-3.5" />
            </Button>
          </Link>
          <span className="text-sm font-medium">GitHub Integration</span>
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
                        ? `Connected as ${status.username}`
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
              {status?.connected && status.scopes && (
                <div className="mt-1 text-xs text-muted-foreground">
                  Scopes: {status.scopes}
                </div>
              )}
              {status && !status.connected && status.error && (
                <div className="mt-1 text-xs text-destructive">
                  {status.error}
                </div>
              )}
              <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                <div>Token: {config.personal_access_token}</div>
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
                Connect GitHub
              </div>
              <div className="space-y-3">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="github-token" className="text-xs">
                    Personal Access Token
                  </Label>
                  <Input
                    id="github-token"
                    type="password"
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    placeholder="ghp_..."
                  />
                </div>
                <div className="text-xs text-muted-foreground">
                  Create a token at GitHub &gt; Settings &gt; Developer
                  settings &gt; Personal access tokens. Required scopes:
                  &nbsp;<code>repo</code> (for private repos) and
                  &nbsp;<code>actions</code> (for CI restarts).
                </div>
                <div className="flex justify-end">
                  <Button
                    size="sm"
                    onClick={handleSave}
                    disabled={saving || !token}
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
                        ? "Configure GitHub token first"
                        : enabled
                          ? "Disable GitHub for this agent"
                          : "Enable GitHub for this agent"
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
                Agents with GitHub enabled can monitor PRs, inspect CI
                failures, and restart workflows. Restart the
                agent&apos;s worker after toggling for changes to take
                effect.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
