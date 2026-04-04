import { useCallback, useEffect, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Pause, Play, RefreshCw, Trash2 } from "lucide-react"

interface Schedule {
  id: string
  agent_id: string
  agent_name: string
  prompt: string
  allowed_tools: string[]
  interval_seconds: number
  last_executed_at: string | null
  status: string
  created_at: string
}

export function SchedulesView() {
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [loading, setLoading] = useState(false)

  const fetchSchedules = useCallback(async () => {
    setLoading(true)
    const res = await fetch("/api/schedules")
    if (res.ok) {
      setSchedules(await res.json())
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    fetchSchedules()
  }, [fetchSchedules])

  const handleToggle = async (id: string, currentStatus: string) => {
    const action = currentStatus === "active" ? "pause" : "resume"
    const res = await fetch(`/api/schedules/${id}/${action}`, { method: "POST" })
    if (res.ok) fetchSchedules()
  }

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this scheduled task? This cannot be undone.")) return
    const res = await fetch(`/api/schedules/${id}`, { method: "DELETE" })
    if (res.ok) fetchSchedules()
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b px-4 py-2">
        <span className="text-sm font-medium">Schedules</span>
        <Button variant="outline" size="sm" onClick={fetchSchedules} disabled={loading}>
          <RefreshCw className={`mr-1.5 size-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>
      <div className="flex-1 overflow-auto">
        {schedules.length === 0 ? (
          <p className="p-4 text-sm text-muted-foreground">
            {loading
              ? "Loading..."
              : "No scheduled tasks. Ask an agent to monitor something to get started."}
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                <th className="px-4 py-2">ID</th>
                <th className="px-4 py-2">Agent</th>
                <th className="px-4 py-2">Prompt</th>
                <th className="px-4 py-2">Allowed Tools</th>
                <th className="px-4 py-2">Interval (s)</th>
                <th className="px-4 py-2">Last Executed</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Created</th>
                <th className="px-4 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {schedules.map((s) => (
                <tr key={s.id} className="border-b last:border-b-0 hover:bg-muted/30">
                  <td className="px-4 py-2 font-mono text-xs text-muted-foreground" title={s.id}>
                    {s.id.slice(0, 8)}...
                  </td>
                  <td className="px-4 py-2">{s.agent_name}</td>
                  <td className="max-w-xs truncate px-4 py-2" title={s.prompt}>
                    {s.prompt}
                  </td>
                  <td className="px-4 py-2 font-mono text-xs">
                    {s.allowed_tools.length > 0 ? s.allowed_tools.join(", ") : "-"}
                  </td>
                  <td className="px-4 py-2 text-right font-mono">{s.interval_seconds}</td>
                  <td className="px-4 py-2 text-xs">
                    {s.last_executed_at ?? "-"}
                  </td>
                  <td className="px-4 py-2">
                    <Badge variant={s.status === "active" ? "default" : "secondary"}>
                      {s.status}
                    </Badge>
                  </td>
                  <td className="px-4 py-2 text-xs">{s.created_at}</td>
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-1">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleToggle(s.id, s.status)}
                      >
                        {s.status === "active" ? (
                          <Pause className="size-3.5" />
                        ) : (
                          <Play className="size-3.5" />
                        )}
                      </Button>
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => handleDelete(s.id)}
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
