import { useCallback, useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { ArrowLeft, RefreshCw } from "lucide-react"

export function ContainerLogsView() {
  const { containerName } = useParams<{ containerName: string }>()
  const [logs, setLogs] = useState("")
  const [loading, setLoading] = useState(false)

  const fetchLogs = useCallback(async () => {
    if (!containerName) return
    setLoading(true)
    try {
      const res = await fetch(`/api/containers/name/${containerName}/logs?tail=200`)
      if (res.ok) {
        setLogs(await res.text())
      } else {
        setLogs("Failed to fetch logs.")
      }
    } catch {
      setLogs("Failed to fetch logs.")
    } finally {
      setLoading(false)
    }
  }, [containerName])

  useEffect(() => {
    fetchLogs()
  }, [fetchLogs])

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b px-4 py-2">
        <div className="flex items-center gap-2">
          <Link to="/settings/containers">
            <Button variant="ghost" size="icon-sm">
              <ArrowLeft className="size-3.5" />
            </Button>
          </Link>
          <span className="text-sm font-medium">Logs: {containerName}</span>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={fetchLogs}
          disabled={loading}
        >
          <RefreshCw className={`mr-1.5 size-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>
      <div className="flex-1 overflow-auto bg-muted/30">
        <pre className="whitespace-pre-wrap break-all p-4 font-mono text-xs leading-relaxed text-muted-foreground select-text">
          {loading && !logs ? "Loading..." : logs || "No logs available."}
        </pre>
      </div>
    </div>
  )
}
