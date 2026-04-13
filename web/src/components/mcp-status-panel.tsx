import { useEffect, useState } from "react"

interface McpServer {
  name: string
  enabled: boolean
}

interface McpServerStatus {
  name: string
  connected: boolean
  tool_count: number
}

interface McpStatusResponse {
  running: boolean
  servers: McpServerStatus[]
}

export function McpStatusPanel({ agentId }: { agentId: string }) {
  const [servers, setServers] = useState<McpServer[]>([])
  const [status, setStatus] = useState<McpStatusResponse | null>(null)

  useEffect(() => {
    let cancelled = false

    async function fetchData() {
      try {
        const [configRes, statusRes] = await Promise.all([
          fetch(`/api/agents/${agentId}/mcp`),
          fetch(`/api/agents/${agentId}/mcp/status`),
        ])
        if (cancelled) return
        if (configRes.ok) {
          const data = await configRes.json()
          setServers(data.servers ?? [])
        }
        if (statusRes.ok) {
          setStatus(await statusRes.json())
        }
      } catch {
        // ignore fetch errors
      }
    }

    fetchData()
    const interval = setInterval(fetchData, 5000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [agentId])

  const statusMap = new Map(
    (status?.servers ?? []).map((s) => [s.name, s]),
  )

  // Merge config servers with any running servers not in config
  // (e.g. builtin MCP servers injected at runtime from DB flags)
  const configNames = new Set(servers.map((s) => s.name))
  const merged: McpServer[] = [
    ...servers,
    ...(status?.servers ?? [])
      .filter((s) => !configNames.has(s.name))
      .map((s) => ({ name: s.name, enabled: true })),
  ]

  return (
    <div className="flex flex-col gap-1 px-3 py-2">
      <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mb-0.5">
        MCP Servers
      </span>
      {merged.length === 0 ? (
        <span className="text-[11px] text-muted-foreground/60 italic">
          Empty
        </span>
      ) : merged.map((srv) => {
        const live = statusMap.get(srv.name)
        const running = !!live?.connected
        return (
          <div key={srv.name} className="flex items-center gap-2 py-0.5">
            <span
              className={`inline-block size-1.5 shrink-0 rounded-full ${
                srv.enabled
                  ? "bg-green-500"
                  : "bg-muted-foreground/40"
              }`}
            />
            <span className="text-xs text-muted-foreground truncate">
              {srv.name}
            </span>
            {live && running && (
              <span className="ml-auto text-[10px] text-muted-foreground/60 tabular-nums">
                {live.tool_count}
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}

