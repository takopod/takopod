import { useState } from "react"

const ACTIVE_STATUSES = new Set(["running", "starting", "idle"])

const STATUS_COLOR: Record<string, string> = {
  running: "bg-green-500",
  starting: "bg-yellow-500",
  idle: "bg-yellow-500",
}

export function ContainerStatusPanel({
  agentId,
  status,
  onKilled,
}: {
  agentId: string
  status: string | null | undefined
  onKilled?: () => void
}) {
  const [killing, setKilling] = useState(false)

  const active = !!status && ACTIVE_STATUSES.has(status)

  const handleKill = async () => {
    if (!confirm("Kill this container?")) return
    setKilling(true)
    try {
      const res = await fetch(`/api/agents/${agentId}/kill`, { method: "POST" })
      if (res.ok) onKilled?.()
    } finally {
      setKilling(false)
    }
  }

  return (
    <div className="flex flex-col gap-1 px-3 py-2">
      <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mb-0.5">
        Container
      </span>
      {active ? (
        <div className="flex items-center justify-between py-0.5">
          <div className="flex items-center gap-2">
            <span
              className={`inline-block size-1.5 shrink-0 rounded-full ${
                STATUS_COLOR[status!] ?? "bg-muted-foreground/40"
              }`}
            />
            <span className="text-xs text-muted-foreground">{status}</span>
          </div>
          <button
            onClick={handleKill}
            disabled={killing}
            className="text-[10px] text-destructive hover:underline disabled:opacity-50"
          >
            {killing ? "killing..." : "kill"}
          </button>
        </div>
      ) : (
        <span className="text-[11px] text-muted-foreground/60 italic py-0.5">
          Not running
        </span>
      )}
    </div>
  )
}
