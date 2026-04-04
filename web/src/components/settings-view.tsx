import { useCallback, useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { RefreshCw } from "lucide-react"

export function SettingsView() {
  const [settings, setSettings] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState<string | null>(null)

  const fetchSettings = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch("/api/settings")
      if (res.ok) setSettings(await res.json())
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchSettings()
  }, [fetchSettings])

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
      }
    } finally {
      setSaving(null)
    }
  }

  const isBoolean = (value: string) => value === "true" || value === "false"

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b px-4 py-2">
        <span className="text-sm font-medium">Settings</span>
        <Button variant="ghost" size="icon-sm" onClick={fetchSettings} disabled={loading}>
          <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        <div className="mx-auto max-w-lg space-y-4">
          {Object.entries(settings).map(([key, value]) => (
            <div
              key={key}
              className="flex items-center justify-between rounded-md border px-4 py-3"
            >
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
          ))}
          {Object.keys(settings).length === 0 && !loading && (
            <p className="text-center text-sm text-muted-foreground">No settings found.</p>
          )}
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
