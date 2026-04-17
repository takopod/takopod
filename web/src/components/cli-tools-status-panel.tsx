import { useEffect, useState } from "react"

interface ExternalTool {
  id: string
  name: string
  config_summary: Record<string, string>
  builtin: boolean
  enabled: boolean
}

export function CliToolsStatusPanel({ agentId }: { agentId: string }) {
  const [tools, setTools] = useState<ExternalTool[]>([])

  useEffect(() => {
    let cancelled = false

    async function fetchTools() {
      try {
        const res = await fetch(`/api/agents/${agentId}/external-tools`)
        if (cancelled || !res.ok) return
        const data = await res.json()
        setTools(data.tools ?? [])
      } catch {
        // ignore fetch errors
      }
    }

    fetchTools()
    const interval = setInterval(fetchTools, 10000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [agentId])

  return (
    <div className="flex flex-col gap-1 px-3 py-2">
      <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mb-0.5">
        CLI Tools
      </span>
      {tools.length === 0 ? (
        <span className="text-[11px] text-muted-foreground/60 italic">
          Empty
        </span>
      ) : (
        tools.map((tool) => (
          <div key={tool.id} className="flex items-center gap-2 py-0.5">
            <span
              className={`inline-block size-1.5 shrink-0 rounded-full ${
                tool.enabled
                  ? "bg-green-500"
                  : "bg-muted-foreground/40"
              }`}
            />
            <span className="text-xs text-muted-foreground truncate">
              {tool.name}
            </span>
          </div>
        ))
      )}
    </div>
  )
}
