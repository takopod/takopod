import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { AlertCircle, Clock, RefreshCw } from "lucide-react"
import type { ErrorFrame, SystemErrorFrame } from "@/lib/types"

export function ErrorNotification({ error }: { error: ErrorFrame | null }) {
  if (!error) return null

  const message =
    error.code === "RATE_LIMITED"
      ? `Too many messages. Retry in ${error.retry_after_seconds}s.`
      : "Message queue is full. Try again later."

  return (
    <div className="px-4">
      <Alert variant="destructive">
        <AlertCircle className="size-4" />
        <AlertTitle>{error.code === "RATE_LIMITED" ? "Rate Limited" : "Queue Full"}</AlertTitle>
        <AlertDescription>{message}</AlertDescription>
      </Alert>
    </div>
  )
}

export function SystemErrorNotification({ error }: { error: SystemErrorFrame | null }) {
  if (!error) return null

  return (
    <div className="px-4">
      <Alert variant={error.fatal ? "destructive" : "default"}>
        {error.fatal ? (
          <AlertCircle className="size-4" />
        ) : (
          <RefreshCw className="size-4 animate-spin" />
        )}
        <AlertTitle>{error.fatal ? "Agent Unavailable" : "Agent Restarting"}</AlertTitle>
        <AlertDescription>{error.error}</AlertDescription>
      </Alert>
    </div>
  )
}

export function SessionEndedBanner({
  reason,
  onReconnect,
}: {
  reason: string | null
  onReconnect: () => void
}) {
  if (!reason) return null

  return (
    <div className="px-4">
      <Alert>
        <Clock className="size-4" />
        <AlertTitle>Session Ended</AlertTitle>
        <AlertDescription className="flex items-center justify-between">
          <span>{reason}</span>
          <Button variant="outline" size="sm" onClick={onReconnect}>
            <RefreshCw className="mr-1.5 size-3.5" />
            Reconnect
          </Button>
        </AlertDescription>
      </Alert>
    </div>
  )
}
