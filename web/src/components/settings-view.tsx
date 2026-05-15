import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import {
  ChevronRight,
  Container,
  Database,
  ListChecks,
  MessageSquare,
  RefreshCw,
  Search,
  Server,
  Settings,
  Timer,
} from "lucide-react"

interface OllamaStatus {
  status: string
  model?: string
}

export function SettingsView() {
  const [settings, setSettings] = useState<Record<string, string>>({})
  const [ollamaStatus, setOllamaStatus] = useState<OllamaStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<string | null>(null)
  const [checkingOllama, setCheckingOllama] = useState(false)

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

  useEffect(() => {
    fetchSettings()
    fetchOllamaStatus()
  }, [fetchSettings, fetchOllamaStatus])

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

  const isBoolean = (value: string) => value === "true" || value === "false"

  const ollamaValue = settings["ollama_enabled"]
  const filteredSettings = Object.entries(settings).filter(
    ([key]) => key !== "ollama_enabled" && !key.startsWith("slack_polling_") && !key.startsWith("default_container_") && key !== "session_history_window_size" && key !== "idle_timeout_seconds" && key !== "inflight_hard_timeout",
  )

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">Settings</h2>
            <p className="text-xs text-muted-foreground">
              Configure platform defaults and integrations
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => { fetchSettings(); fetchOllamaStatus() }}
            disabled={loading}
          >
            <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-5 p-5">
          {/* General Settings */}
          {filteredSettings.length > 0 && (
            <Card size="sm">
              <CardHeader>
                <div className="flex items-center gap-2">
                  <Settings className="size-4 text-muted-foreground" />
                  <CardTitle>General</CardTitle>
                </div>
              </CardHeader>
              <CardContent className="space-y-1 pt-0">
                {filteredSettings.map(([key, value]) => (
                  <div
                    key={key}
                    className="flex items-center justify-between rounded-md px-3 py-2.5 hover:bg-muted/50 transition-colors"
                  >
                    <div>
                      <div className="text-sm font-medium">{formatLabel(key)}</div>
                      <div className="text-xs text-muted-foreground font-mono">{key}</div>
                    </div>
                    {isBoolean(value) ? (
                      <Switch
                        size="sm"
                        checked={value === "true"}
                        disabled={saving === key}
                        onCheckedChange={() => toggleSetting(key, value)}
                      />
                    ) : (
                      <span className="text-sm text-muted-foreground">{value}</span>
                    )}
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {/* Search & Embedding */}
          <Card size="sm">
            <CardHeader>
              <div className="flex items-center gap-2">
                <Search className="size-4 text-muted-foreground" />
                <CardTitle>Search & Embedding</CardTitle>
              </div>
              <CardDescription>
                Ollama provides local embedding for hybrid search (BM25 + vector)
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-1 pt-0">
              {ollamaValue !== undefined && (
                <div className="flex items-center justify-between rounded-md px-3 py-2.5 hover:bg-muted/50 transition-colors">
                  <div className="flex-1">
                    <div className="text-sm font-medium">Ollama Enabled</div>
                    <div className="flex items-center gap-2 mt-1">
                      {ollamaStatus && (
                        <>
                          <Badge variant={
                            ollamaStatus.status === "healthy" ? "default" :
                            ollamaStatus.status === "disabled" ? "secondary" :
                            "destructive"
                          }>
                            {ollamaStatus.status}
                          </Badge>
                          {ollamaStatus.model && (
                            <span className="text-xs text-muted-foreground font-mono">{ollamaStatus.model}</span>
                          )}
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            onClick={fetchOllamaStatus}
                            disabled={checkingOllama}
                          >
                            <RefreshCw className={`size-3 ${checkingOllama ? "animate-spin" : ""}`} />
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                  <Switch
                    size="sm"
                    checked={ollamaValue === "true"}
                    disabled={saving === "ollama_enabled"}
                    onCheckedChange={() => toggleSetting("ollama_enabled", ollamaValue)}
                  />
                </div>
              )}
              <NavLink to="/settings/search-index" icon={<Database className="size-4" />} label="Search Index" />
            </CardContent>
          </Card>

          {/* System */}
          <Card size="sm">
            <CardHeader>
              <div className="flex items-center gap-2">
                <Server className="size-4 text-muted-foreground" />
                <CardTitle>System</CardTitle>
              </div>
            </CardHeader>
            <CardContent className="space-y-1 pt-0">
              <NavLink to="/settings/containers" icon={<Container className="size-4" />} label="Containers" />
              <NavLink to="/settings/queue" icon={<ListChecks className="size-4" />} label="Queue Status" />
            </CardContent>
          </Card>

          {/* Conversation */}
          <Card size="sm">
            <CardHeader>
              <div className="flex items-center gap-2">
                <MessageSquare className="size-4 text-muted-foreground" />
                <CardTitle>Conversation</CardTitle>
              </div>
            </CardHeader>
            <CardContent className="pt-0">
              <SettingInput
                label="Session History Window"
                settingKey="session_history_window_size"
                placeholder="20"
                helpText="Number of recent messages to retain for context after container restart"
                value={settings["session_history_window_size"] ?? ""}
                onSaved={(v) => setSettings((prev) => ({ ...prev, session_history_window_size: v }))}
              />
            </CardContent>
          </Card>

          {/* Container Defaults */}
          <Card size="sm">
            <CardHeader>
              <div className="flex items-center gap-2">
                <Container className="size-4 text-muted-foreground" />
                <CardTitle>Container Defaults</CardTitle>
              </div>
              <CardDescription>
                Default CPU and memory limits for new agent containers. Existing agents are not affected.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-1 pt-0">
              <SettingInput
                label="Memory"
                settingKey="default_container_memory"
                placeholder="2g"
                helpText="e.g. 512m, 1g, 4g"
                value={settings["default_container_memory"] ?? ""}
                onSaved={(v) => setSettings((prev) => ({ ...prev, default_container_memory: v }))}
              />
              <SettingInput
                label="CPUs"
                settingKey="default_container_cpus"
                placeholder="2"
                helpText="e.g. 1, 2, 4"
                value={settings["default_container_cpus"] ?? ""}
                onSaved={(v) => setSettings((prev) => ({ ...prev, default_container_cpus: v }))}
              />
            </CardContent>
          </Card>

          {/* Container Lifecycle */}
          <Card size="sm">
            <CardHeader>
              <div className="flex items-center gap-2">
                <Timer className="size-4 text-muted-foreground" />
                <CardTitle>Container Lifecycle</CardTitle>
              </div>
              <CardDescription>
                Default timeout values for new agent containers. Per-agent overrides can be set in each agent's settings.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-1 pt-0">
              <SettingInput
                label="Idle Timeout (seconds)"
                settingKey="idle_timeout_seconds"
                placeholder="300"
                helpText="How long an idle container runs before shutdown"
                value={settings["idle_timeout_seconds"] ?? ""}
                onSaved={(v) => setSettings((prev) => ({ ...prev, idle_timeout_seconds: v }))}
              />
              <SettingInput
                label="Hard Timeout (seconds)"
                settingKey="inflight_hard_timeout"
                placeholder="600"
                helpText="Maximum time for in-flight messages before forced container reap"
                value={settings["inflight_hard_timeout"] ?? ""}
                onSaved={(v) => setSettings((prev) => ({ ...prev, inflight_hard_timeout: v }))}
              />
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

function NavLink({ to, icon, label }: { to: string; icon: React.ReactNode; label: string }) {
  return (
    <Link
      to={to}
      className="flex items-center justify-between rounded-md px-3 py-2.5 text-sm font-medium hover:bg-muted/50 transition-colors"
    >
      <div className="flex items-center gap-2.5 text-muted-foreground">
        {icon}
        <span className="text-foreground">{label}</span>
      </div>
      <ChevronRight className="size-4 text-muted-foreground" />
    </Link>
  )
}

function SettingInput({
  label,
  settingKey,
  placeholder,
  helpText,
  value,
  onSaved,
}: {
  label: string
  settingKey: string
  placeholder: string
  helpText: string
  value: string
  onSaved: (v: string) => void
}) {
  const [draft, setDraft] = useState(value)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const dirty = draft !== (value || "")

  useEffect(() => {
    setDraft(value || "")
  }, [value])

  const handleSave = async () => {
    if (!draft.trim()) return
    setSaving(true)
    setError("")
    try {
      const res = await fetch(`/api/settings/${settingKey}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: draft.trim() }),
      })
      if (res.ok) {
        onSaved(draft.trim())
      } else {
        setError("Failed to save")
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex items-center justify-between rounded-md px-3 py-2.5 hover:bg-muted/50 transition-colors">
      <div className="flex-1">
        <div className="text-sm font-medium">{label}</div>
        <div className="text-xs text-muted-foreground">{helpText}</div>
      </div>
      <div className="flex items-center gap-2">
        <Input
          value={draft}
          onChange={(e) => { setDraft(e.target.value); setError("") }}
          onKeyDown={(e) => { if (e.key === "Enter" && dirty) handleSave() }}
          placeholder={placeholder}
          className="h-8 w-24 text-sm"
        />
        {dirty && (
          <Button size="xs" onClick={handleSave} disabled={saving}>
            {saving ? "..." : "Save"}
          </Button>
        )}
        {error && <span className="text-xs text-destructive">{error}</span>}
      </div>
    </div>
  )
}

function formatLabel(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
}
