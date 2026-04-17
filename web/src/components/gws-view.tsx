import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { ArrowLeft, RefreshCw, Trash2 } from "lucide-react"

interface GWSConfig {
  configured: boolean
  user_email?: string
  credentials?: string
}

interface GWSStatus {
  connected: boolean
  user_email?: string
  error?: string
}

export function GWSView() {
  const [config, setConfig] = useState<GWSConfig>({ configured: false })
  const [status, setStatus] = useState<GWSStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)

  const [credentials, setCredentials] = useState("")

  const fetchConfig = useCallback(async () => {
    const res = await fetch("/api/gws/config")
    if (res.ok) {
      const data = await res.json()
      setConfig(data)
    }
  }, [])

  const fetchStatus = useCallback(async () => {
    setTesting(true)
    try {
      const res = await fetch("/api/gws/status")
      if (res.ok) setStatus(await res.json())
    } finally {
      setTesting(false)
    }
  }, [])

  const loadAll = useCallback(async () => {
    setLoading(true)
    try {
      await fetchConfig()
    } finally {
      setLoading(false)
    }
  }, [fetchConfig])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  useEffect(() => {
    if (config.configured) fetchStatus()
  }, [config.configured, fetchStatus])

  const handleSave = async () => {
    setSaving(true)
    try {
      const res = await fetch("/api/gws/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credentials_json: credentials }),
      })
      if (res.ok) {
        setConfig(await res.json())
        setCredentials("")
        fetchStatus()
      }
    } finally {
      setSaving(false)
    }
  }

  const handleDisconnect = async () => {
    await fetch("/api/gws/config", { method: "DELETE" })
    setConfig({ configured: false })
    setStatus(null)
    setCredentials("")
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
          <span className="text-sm font-medium">Google Workspace Integration</span>
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
                        ? `Connected as ${status.user_email}`
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
              {status && !status.connected && status.error && (
                <div className="mt-1 text-xs text-destructive">
                  {status.error}
                </div>
              )}
              {config.user_email && (
                <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                  <div>Account: {config.user_email}</div>
                </div>
              )}
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
                Connect Google Workspace
              </div>
              <div className="space-y-3">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="gws-credentials" className="text-xs">
                    Credentials JSON
                  </Label>
                  <textarea
                    id="gws-credentials"
                    value={credentials}
                    onChange={(e) => setCredentials(e.target.value)}
                    placeholder="Paste output of: gws auth export --unmasked"
                    rows={6}
                    className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 font-mono"
                  />
                </div>
                <div className="text-xs text-muted-foreground">
                  Run <code>gws auth export --unmasked</code> on your machine
                  and paste the JSON output above.
                </div>
                <div className="flex justify-end">
                  <Button
                    size="sm"
                    onClick={handleSave}
                    disabled={saving || !credentials}
                  >
                    {saving ? "Saving..." : "Save & Connect"}
                  </Button>
                </div>
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  )
}
