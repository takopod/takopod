import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { ChevronRight, RefreshCw } from "lucide-react"

interface OllamaStatus {
  status: string
  model?: string
}

export function SettingsView() {
  const [settings, setSettings] = useState<Record<string, string>>({})
  const [ollamaStatus, setOllamaStatus] = useState<OllamaStatus | null>(null)
  const [loading, setLoading] = useState(false)
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
    ([key]) => key !== "ollama_enabled" && !key.startsWith("slack_polling_") && !key.startsWith("default_container_") && key !== "session_history_window_size",
  )

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b px-4 py-2">
        <span className="text-sm font-medium">Settings</span>
        <Button variant="ghost" size="icon-sm" onClick={() => { fetchSettings(); fetchOllamaStatus() }} disabled={loading}>
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

          {/* Conversation */}
          <div className="pt-4">
            <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground pb-2">Conversation</div>
            <div className="space-y-3">
              <ContainerDefaultInput
                label="Session History Window"
                settingKey="session_history_window_size"
                placeholder="20"
                helpText="Number of recent messages to retain for context after container restart"
                value={settings["session_history_window_size"] ?? ""}
                onSaved={(v) => setSettings((prev) => ({ ...prev, session_history_window_size: v }))}
              />
            </div>
          </div>

          {/* Container Defaults */}
          <div className="pt-4">
            <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground pb-2">Container Defaults</div>
            <p className="text-xs text-muted-foreground pb-3">
              Default CPU and memory limits for new agent containers. Existing agents are not affected.
            </p>
            <div className="space-y-3">
              <ContainerDefaultInput
                label="Memory"
                settingKey="default_container_memory"
                placeholder="2g"
                helpText="e.g. 512m, 1g, 4g"
                value={settings["default_container_memory"] ?? ""}
                onSaved={(v) => setSettings((prev) => ({ ...prev, default_container_memory: v }))}
              />
              <ContainerDefaultInput
                label="CPUs"
                settingKey="default_container_cpus"
                placeholder="2"
                helpText="e.g. 1, 2, 4"
                value={settings["default_container_cpus"] ?? ""}
                onSaved={(v) => setSettings((prev) => ({ ...prev, default_container_cpus: v }))}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function ContainerDefaultInput({
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
    <div className="rounded-md border px-4 py-3">
      <div className="flex items-center justify-between gap-3">
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
            <Button size="sm" onClick={handleSave} disabled={saving}>
              {saving ? "..." : "Save"}
            </Button>
          )}
        </div>
      </div>
      {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
    </div>
  )
}

function formatLabel(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
}
