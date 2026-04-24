import { useCallback, useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"

import { ArrowLeft, FileText, RefreshCw, Trash2 } from "lucide-react"

interface Container {
  id: string
  agent_id: string
  agent_name: string | null
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
  const [confirmKillId, setConfirmKillId] = useState<string | null>(null)
  const navigate = useNavigate()

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

  const handleKillConfirm = async () => {
    if (!confirmKillId) return
    const res = await fetch(`/api/containers/${confirmKillId}`, { method: "DELETE" })
    if (res.ok) fetchContainers()
  }

  const handleViewLogs = (c: Container) => {
    const name = `takopod-${c.agent_id.slice(0, 8)}`
    navigate(`/settings/containers/${name}/logs`)
  }

  const active = containers.filter((c) => ACTIVE_STATUSES.has(c.status))
  const stopped = containers.filter((c) => !ACTIVE_STATUSES.has(c.status))

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
                      onKill={(id) => setConfirmKillId(id)}
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
      <ConfirmDialog
        open={confirmKillId !== null}
        onOpenChange={(open) => { if (!open) setConfirmKillId(null) }}
        title="Kill container"
        description="Kill this container? The agent will need to restart it on the next message."
        confirmLabel="Kill"
        destructive
        onConfirm={handleKillConfirm}
      />
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
    </div>
  )
}
