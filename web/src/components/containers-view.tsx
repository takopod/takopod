import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

import { ArrowLeft, FileText, RefreshCw, Trash2, X } from "lucide-react"

interface Container {
  id: string
  agent_id: string
  agent_name: string | null
  session_id: string | null
  container_type: string
  status: string
  started_at: string
  stopped_at: string | null
  last_activity: string
  pid: number | null
}

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  running: "default",
  starting: "secondary",
  idle: "outline",
  stopped: "secondary",
  error: "destructive",
  stopping: "outline",
}

const ACTIVE_STATUSES = new Set(["running", "starting", "idle"])

export function ContainersView() {
  const [containers, setContainers] = useState<Container[]>([])
  const [loading, setLoading] = useState(false)
  const [logsContainerId, setLogsContainerId] = useState<string | null>(null)
  const [logsContent, setLogsContent] = useState("")
  const [logsLoading, setLogsLoading] = useState(false)
  const [logsName, setLogsName] = useState("")

  const fetchContainers = useCallback(async () => {
    setLoading(true)
    const res = await fetch("/api/containers")
    if (res.ok) {
      setContainers(await res.json())
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    fetchContainers()
  }, [fetchContainers])

  const handleKill = async (id: string) => {
    if (!confirm("Kill this container?")) return
    const res = await fetch(`/api/containers/${id}`, { method: "DELETE" })
    if (res.ok) {
      if (logsContainerId === id) setLogsContainerId(null)
      fetchContainers()
    }
  }

  const handleViewLogs = async (c: Container) => {
    setLogsContainerId(c.id)
    setLogsName(c.agent_name ?? c.agent_id.slice(0, 8))
    setLogsLoading(true)
    const res = await fetch(`/api/containers/${c.id}/logs?tail=200`)
    if (res.ok) {
      setLogsContent(await res.text())
    } else {
      setLogsContent("Failed to fetch logs.")
    }
    setLogsLoading(false)
  }

  const handleRefreshLogs = async () => {
    if (!logsContainerId) return
    setLogsLoading(true)
    const res = await fetch(`/api/containers/${logsContainerId}/logs?tail=200`)
    if (res.ok) {
      setLogsContent(await res.text())
    }
    setLogsLoading(false)
  }

  const active = containers.filter((c) => ACTIVE_STATUSES.has(c.status))
  const stopped = containers.filter((c) => !ACTIVE_STATUSES.has(c.status))

  if (logsContainerId) {
    return (
      <div className="flex flex-1 flex-col overflow-hidden">
        <div className="flex items-center justify-between border-b px-4 py-2">
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => setLogsContainerId(null)}
            >
              <X className="size-4" />
            </Button>
            <span className="text-sm font-medium">Logs: {logsName}</span>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefreshLogs}
            disabled={logsLoading}
          >
            <RefreshCw className={`mr-1.5 size-3.5 ${logsLoading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
        <div className="flex-1 overflow-auto bg-muted/30">
          <pre className="whitespace-pre-wrap break-all p-4 font-mono text-xs leading-relaxed text-muted-foreground select-text">
            {logsLoading ? "Loading..." : logsContent || "No logs available."}
          </pre>
        </div>
      </div>
    )
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
          <span className="text-sm font-medium">Containers</span>
        </div>
        <Button variant="outline" size="sm" onClick={fetchContainers} disabled={loading}>
          <RefreshCw className={`mr-1.5 size-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {containers.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {loading ? "Loading..." : "No containers found."}
          </p>
        ) : (
          <>
            {active.length > 0 && (
              <div className="mb-6">
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Active ({active.length})
                </h3>
                <div className="flex flex-col gap-2">
                  {active.map((c) => (
                    <ContainerCard
                      key={c.id}
                      container={c}
                      onKill={handleKill}
                      onViewLogs={handleViewLogs}
                    />
                  ))}
                </div>
              </div>
            )}
            {stopped.length > 0 && (
              <div>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Stopped ({stopped.length})
                </h3>
                <div className="flex flex-col gap-2">
                  {stopped.map((c) => (
                    <ContainerCard
                      key={c.id}
                      container={c}
                      onViewLogs={handleViewLogs}
                    />
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function ContainerCard({
  container: c,
  onKill,
  onViewLogs,
}: {
  container: Container
  onKill?: (id: string) => void
  onViewLogs: (c: Container) => void
}) {
  const isActive = ACTIVE_STATUSES.has(c.status)

  return (
    <div className="rounded-lg border px-4 py-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">
            {c.agent_name ?? c.agent_id.slice(0, 8)}
          </span>
          <Badge variant={STATUS_VARIANT[c.status] ?? "secondary"}>
            {c.status}
          </Badge>
          <Badge variant="outline">{c.container_type}</Badge>
        </div>
        <div className="flex items-center gap-2">
          {c.pid && (
            <span className="text-xs text-muted-foreground">PID {c.pid}</span>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => onViewLogs(c)}
          >
            <FileText className="mr-1.5 size-3.5" />
            Logs
          </Button>
          {isActive && onKill && (
            <Button
              variant="destructive"
              size="sm"
              onClick={() => onKill(c.id)}
            >
              <Trash2 className="mr-1.5 size-3.5" />
              Kill
            </Button>
          )}
        </div>
      </div>
      <div className="mt-1.5 flex gap-4 text-xs text-muted-foreground">
        <span>Started: {new Date(c.started_at).toLocaleString()}</span>
        <span>Last activity: {new Date(c.last_activity).toLocaleString()}</span>
        {c.stopped_at && (
          <span>Stopped: {new Date(c.stopped_at).toLocaleString()}</span>
        )}
      </div>
      <div className="mt-1 text-xs text-muted-foreground">
        Session: {c.session_id ? `${c.session_id.slice(0, 8)}...` : "—"}
      </div>
    </div>
  )
}
