import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Trash2 } from "lucide-react"

const ACTIVE_STATUSES = new Set(["running", "starting", "idle"])

const STATUS_COLOR: Record<string, string> = {
  running: "bg-green-500",
  starting: "bg-yellow-500",
  idle: "bg-yellow-500",
}

interface ContainerInfo {
  id: string
  status: string
}

export function ContainerStatusPanel({
  agentId,
}: {
  agentId: string
}) {
  const [killing, setKilling] = useState(false)
  const [container, setContainer] = useState<ContainerInfo | null>(null)
  const [confirmKill, setConfirmKill] = useState(false)

  const containerName = `takopod-${agentId.slice(0, 8)}`

  useEffect(() => {
    let cancelled = false

    async function fetchContainer() {
      try {
        const res = await fetch("/api/containers")
        if (cancelled || !res.ok) return
        const containers: { id: string; agent_id: string; status: string }[] =
          await res.json()
        const match = containers.find(
          (c) => c.agent_id === agentId && ACTIVE_STATUSES.has(c.status),
        )
        setContainer(match ? { id: match.id, status: match.status } : null)
      } catch {
        // ignore
      }
    }

    fetchContainer()
    const interval = setInterval(fetchContainer, 5000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [agentId])

  const handleKill = async () => {
    setKilling(true)
    try {
      const res = await fetch(`/api/agents/${agentId}/kill`, { method: "POST" })
      if (res.ok) setContainer(null)
    } finally {
      setKilling(false)
    }
  }

  return (
    <div className="flex flex-col gap-1 px-3 py-2">
      <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mb-0.5">
        Container
      </span>
      {container ? (
        <>
          <div className="flex items-center gap-2 py-0.5">
            <span
              className={`inline-block size-1.5 shrink-0 rounded-full ${
                STATUS_COLOR[container.status] ?? "bg-muted-foreground/40"
              }`}
            />
            <span className="text-xs text-muted-foreground truncate">
              {containerName}
            </span>
          </div>
          <div className="flex items-center gap-2 pl-3.5 py-0.5">
            <Link
              to={`/settings/containers/${containerName}/logs`}
              className="text-[11px] text-muted-foreground hover:underline"
            >
              Logs
            </Link>
            <button
              onClick={() => setConfirmKill(true)}
              disabled={killing}
              className="text-muted-foreground/60 hover:text-destructive disabled:opacity-50"
              title="Kill container"
            >
              <Trash2 className="size-3" />
            </button>
          </div>
        </>
      ) : (
        <span className="text-[11px] text-muted-foreground/60 italic py-0.5">
          Not running
        </span>
      )}
      <ConfirmDialog
        open={confirmKill}
        onOpenChange={setConfirmKill}
        title="Kill container"
        description="Kill this container? The agent will need to restart it on the next message."
        confirmLabel="Kill"
        destructive
        onConfirm={handleKill}
      />
    </div>
  )
}
