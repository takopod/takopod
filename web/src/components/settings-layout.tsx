import { Outlet, useLocation, useNavigate } from "react-router-dom"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import type { QueueStatusFrame } from "@/lib/types"

export interface SettingsOutletContext {
  queueStatus: QueueStatusFrame
  connected: boolean
}

const TAB_ROUTES = [
  { value: "general", label: "General", path: "/settings" },
  { value: "slack", label: "Slack", path: "/settings/slack" },
  { value: "containers", label: "Containers", path: "/settings/containers" },
  { value: "search", label: "Search", path: "/settings/search-index" },
  { value: "queue", label: "Queue", path: "/settings/queue" },
] as const

export function SettingsLayout({
  queueStatus,
  connected,
}: {
  queueStatus: QueueStatusFrame
  connected: boolean
}) {
  const location = useLocation()
  const navigate = useNavigate()

  const activeTab =
    TAB_ROUTES.find((t) =>
      t.path === "/settings"
        ? location.pathname === "/settings"
        : location.pathname.startsWith(t.path),
    )?.value ?? "general"

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="border-b px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">Settings</h2>
            <p className="text-xs text-muted-foreground">
              Configure platform defaults and integrations
            </p>
          </div>
        </div>
        <Tabs
          value={activeTab}
          onValueChange={(v) => {
            const route = TAB_ROUTES.find((t) => t.value === v)
            if (route) navigate(route.path)
          }}
          className="mt-4"
        >
          <TabsList variant="line">
            {TAB_ROUTES.map((t) => (
              <TabsTrigger key={t.value} value={t.value}>
                {t.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>
      <div className="flex flex-1 flex-col overflow-hidden">
        <Outlet context={{ queueStatus, connected } satisfies SettingsOutletContext} />
      </div>
    </div>
  )
}
