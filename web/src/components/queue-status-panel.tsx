import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { QueueStatusFrame } from "@/lib/types"

interface QueueStatusPanelProps {
  status: QueueStatusFrame
  connected: boolean
}

export function QueueStatusPanel({ status, connected: _connected }: QueueStatusPanelProps) {
  return (
    <div className="flex flex-1 items-start justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">Queue Status</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Queued</span>
            <Badge variant="secondary">{status.queued}</Badge>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">In-Flight</span>
            <Badge variant="secondary">{status.in_flight}</Badge>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Processed</span>
            <Badge variant="secondary">{status.processed}</Badge>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
