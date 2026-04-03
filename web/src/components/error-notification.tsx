import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { AlertCircle } from "lucide-react"
import type { ErrorFrame } from "@/lib/types"

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
