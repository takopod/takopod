import { useCallback, useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { ChevronRight, RefreshCw } from "lucide-react"

interface OllamaStatus {
  status: string
  model?: string
}

interface IntegrationState {
  configured: boolean
  connected: boolean
  label: string
  disconnecting: boolean
}

export function SettingsView() {
  const navigate = useNavigate()
  const [settings, setSettings] = useState<Record<string, string>>({})
  const [ollamaStatus, setOllamaStatus] = useState<OllamaStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState<string | null>(null)
  const [checkingOllama, setCheckingOllama] = useState(false)
  const [slack, setSlack] = useState<IntegrationState>({ configured: false, connected: false, label: "", disconnecting: false })
  const [github, setGithub] = useState<IntegrationState>({ configured: false, connected: false, label: "", disconnecting: false })

  const fetchSettings = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch("/api/settings")
      if (res.ok) setSettings(await res.json())
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchOllamaStatus = useCallback(async () => {
    setCheckingOllama(true)
    try {
      const res = await fetch("/api/health")
      if (res.ok) {
        const data = await res.json()
        setOllamaStatus(data.ollama)
      }
    } finally {
      setCheckingOllama(false)
    }
  }, [])

  const fetchSlack = useCallback(async () => {
    const [configRes, statusRes] = await Promise.all([
      fetch("/api/slack/config"),
      fetch("/api/slack/status"),
    ])
    const config = configRes.ok ? await configRes.json() : { configured: false }
    const status = statusRes.ok ? await statusRes.json() : { connected: false }
    setSlack({
      configured: config.configured,
      connected: status.connected,
      label: status.connected ? `Connected as ${status.user}` : "",
      disconnecting: false,
    })
  }, [])

  const fetchGithub = useCallback(async () => {
    const [configRes, statusRes] = await Promise.all([
      fetch("/api/github/config"),
      fetch("/api/github/status"),
    ])
    const config = configRes.ok ? await configRes.json() : { configured: false }
    const status = statusRes.ok ? await statusRes.json() : { connected: false }
    setGithub({
      configured: config.configured,
      connected: status.connected,
      label: status.connected ? `Connected as ${status.username}` : "",
      disconnecting: false,
    })
  }, [])

  useEffect(() => {
    fetchSettings()
    fetchOllamaStatus()
    fetchSlack()
    fetchGithub()
  }, [fetchSettings, fetchOllamaStatus, fetchSlack, fetchGithub])

  const toggleSetting = async (key: string, current: string) => {
    const newValue = current === "true" ? "false" : "true"
    setSaving(key)
    try {
      const res = await fetch(`/api/settings/${key}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: newValue }),
      })
      if (res.ok) {
        setSettings((prev) => ({ ...prev, [key]: newValue }))
        if (key === "ollama_enabled") fetchOllamaStatus()
      }
    } finally {
      setSaving(null)
    }
  }

  const handleSlackToggle = async () => {
    if (!slack.configured) {
      navigate("/settings/slack")
      return
    }
    setSlack((prev) => ({ ...prev, disconnecting: true }))
    await fetch("/api/slack/config", { method: "DELETE" })
    setSlack({ configured: false, connected: false, label: "", disconnecting: false })
  }

  const handleGithubToggle = async () => {
    if (!github.configured) {
      navigate("/settings/github")
      return
    }
    setGithub((prev) => ({ ...prev, disconnecting: true }))
    await fetch("/api/github/config", { method: "DELETE" })
    setGithub({ configured: false, connected: false, label: "", disconnecting: false })
  }

  const isBoolean = (value: string) => value === "true" || value === "false"

  const ollamaValue = settings["ollama_enabled"]
  const filteredSettings = Object.entries(settings).filter(([key]) => key !== "ollama_enabled")

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b px-4 py-2">
        <span className="text-sm font-medium">Settings</span>
        <Button variant="ghost" size="icon-sm" onClick={() => { fetchSettings(); fetchOllamaStatus(); fetchSlack(); fetchGithub() }} disabled={loading}>
          <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        <div className="mx-auto max-w-lg space-y-4">
          {filteredSettings.map(([key, value]) => (
            <div
              key={key}
              className="rounded-md border px-4 py-3"
            >
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium">{formatLabel(key)}</div>
                  <div className="text-xs text-muted-foreground">{key}</div>
                </div>
                {isBoolean(value) ? (
                  <button
                    onClick={() => toggleSetting(key, value)}
                    disabled={saving === key}
                    className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
                      value === "true" ? "bg-primary" : "bg-muted"
                    } ${saving === key ? "opacity-50" : ""}`}
                  >
                    <span
                      className={`pointer-events-none inline-block size-5 rounded-full bg-background shadow-sm ring-0 transition-transform ${
                        value === "true" ? "translate-x-5" : "translate-x-0"
                      }`}
                    />
                  </button>
                ) : (
                  <span className="text-sm text-muted-foreground">{value}</span>
                )}
              </div>
            </div>
          ))}
          {filteredSettings.length === 0 && !ollamaValue && !loading && (
            <p className="text-center text-sm text-muted-foreground">No settings found.</p>
          )}

          {/* Integrations */}
          <div className="pt-4">
            <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground pb-2">Integrations</div>
            <div className="space-y-3">
              {/* Slack */}
              <div className="flex items-center justify-between rounded-md border px-4 py-3">
                <Link to="/settings/slack" className="flex flex-1 items-center gap-3 min-w-0">
                  <div className="min-w-0">
                    <div className="text-sm font-medium">Slack</div>
                    {slack.configured && slack.label && (
                      <div className="text-xs text-muted-foreground truncate">{slack.label}</div>
                    )}
                    {slack.configured && !slack.connected && (
                      <div className="text-xs text-destructive">Disconnected</div>
                    )}
                    {!slack.configured && (
                      <div className="text-xs text-muted-foreground">Not configured</div>
                    )}
                  </div>
                </Link>
                <div className="flex items-center gap-3 shrink-0">
                  {slack.configured && (
                    <Badge variant={slack.connected ? "default" : "destructive"} className="text-[10px]">
                      {slack.connected ? "Connected" : "Error"}
                    </Badge>
                  )}
                  <button
                    onClick={handleSlackToggle}
                    disabled={slack.disconnecting}
                    className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
                      slack.configured ? "bg-primary" : "bg-muted"
                    } ${slack.disconnecting ? "opacity-50" : ""}`}
                  >
                    <span
                      className={`pointer-events-none inline-block size-5 rounded-full bg-background shadow-sm ring-0 transition-transform ${
                        slack.configured ? "translate-x-5" : "translate-x-0"
                      }`}
                    />
                  </button>
                  <Link to="/settings/slack">
                    <ChevronRight className="size-4 text-muted-foreground" />
                  </Link>
                </div>
              </div>

              {/* GitHub */}
              <div className="flex items-center justify-between rounded-md border px-4 py-3">
                <Link to="/settings/github" className="flex flex-1 items-center gap-3 min-w-0">
                  <div className="min-w-0">
                    <div className="text-sm font-medium">GitHub</div>
                    {github.configured && github.label && (
                      <div className="text-xs text-muted-foreground truncate">{github.label}</div>
                    )}
                    {github.configured && !github.connected && (
                      <div className="text-xs text-destructive">Disconnected</div>
                    )}
                    {!github.configured && (
                      <div className="text-xs text-muted-foreground">Not configured</div>
                    )}
                  </div>
                </Link>
                <div className="flex items-center gap-3 shrink-0">
                  {github.configured && (
                    <Badge variant={github.connected ? "default" : "destructive"} className="text-[10px]">
                      {github.connected ? "Connected" : "Error"}
                    </Badge>
                  )}
                  <button
                    onClick={handleGithubToggle}
                    disabled={github.disconnecting}
                    className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
                      github.configured ? "bg-primary" : "bg-muted"
                    } ${github.disconnecting ? "opacity-50" : ""}`}
                  >
                    <span
                      className={`pointer-events-none inline-block size-5 rounded-full bg-background shadow-sm ring-0 transition-transform ${
                        github.configured ? "translate-x-5" : "translate-x-0"
                      }`}
                    />
                  </button>
                  <Link to="/settings/github">
                    <ChevronRight className="size-4 text-muted-foreground" />
                  </Link>
                </div>
              </div>
            </div>
          </div>

          {/* Search */}
          <div className="pt-4">
            <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground pb-2">Search</div>
            <div className="space-y-3">
              {/* Ollama Enabled */}
              {ollamaValue !== undefined && (
                <div className="rounded-md border px-4 py-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-sm font-medium">Ollama Enabled</div>
                      <div className="text-xs text-muted-foreground">ollama_enabled</div>
                    </div>
                    <button
                      onClick={() => toggleSetting("ollama_enabled", ollamaValue)}
                      disabled={saving === "ollama_enabled"}
                      className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
                        ollamaValue === "true" ? "bg-primary" : "bg-muted"
                      } ${saving === "ollama_enabled" ? "opacity-50" : ""}`}
                    >
                      <span
                        className={`pointer-events-none inline-block size-5 rounded-full bg-background shadow-sm ring-0 transition-transform ${
                          ollamaValue === "true" ? "translate-x-5" : "translate-x-0"
                        }`}
                      />
                    </button>
                  </div>
                  {ollamaStatus && (
                    <div className="mt-2 flex items-center gap-2">
                      <Badge variant={
                        ollamaStatus.status === "healthy" ? "default" :
                        ollamaStatus.status === "disabled" ? "secondary" :
                        "destructive"
                      }>
                        {ollamaStatus.status}
                      </Badge>
                      {ollamaStatus.model && (
                        <span className="text-xs text-muted-foreground">{ollamaStatus.model}</span>
                      )}
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={fetchOllamaStatus}
                        disabled={checkingOllama}
                        className="ml-auto"
                      >
                        <RefreshCw className={`size-3 ${checkingOllama ? "animate-spin" : ""}`} />
                      </Button>
                    </div>
                  )}
                </div>
              )}

              {/* Search Index */}
              <Link
                to="/settings/search-index"
                className="flex items-center justify-between rounded-md border px-4 py-3 text-sm font-medium hover:bg-muted transition-colors"
              >
                Search Index
                <ChevronRight className="size-4 text-muted-foreground" />
              </Link>
            </div>
          </div>

          {/* System */}
          <div className="pt-4">
            <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground pb-2">System</div>
            <div className="space-y-3">
              <Link
                to="/settings/containers"
                className="flex items-center justify-between rounded-md border px-4 py-3 text-sm font-medium hover:bg-muted transition-colors"
              >
                Containers
                <ChevronRight className="size-4 text-muted-foreground" />
              </Link>
              <Link
                to="/settings/queue"
                className="flex items-center justify-between rounded-md border px-4 py-3 text-sm font-medium hover:bg-muted transition-colors"
              >
                Queue Status
                <ChevronRight className="size-4 text-muted-foreground" />
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function formatLabel(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
}
