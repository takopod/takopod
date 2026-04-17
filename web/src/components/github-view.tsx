import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { ArrowLeft, RefreshCw, Terminal } from "lucide-react"

interface GitHubConfig {
  configured: boolean
  gh_installed?: boolean
  username?: string
  status_output?: string
  error?: string
}

export function GitHubView() {
  const [config, setConfig] = useState<GitHubConfig>({ configured: false })
  const [loading, setLoading] = useState(true)

  const fetchConfig = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch("/api/github/config")
      if (res.ok) setConfig(await res.json())
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchConfig()
  }, [fetchConfig])

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b px-4 py-2">
        <div className="flex items-center gap-2">
          <Link to="/settings">
            <Button variant="ghost" size="icon-sm">
              <ArrowLeft className="size-3.5" />
            </Button>
          </Link>
          <span className="text-sm font-medium">GitHub Integration</span>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={fetchConfig}
          disabled={loading}
        >
          <RefreshCw
            className={`size-3.5 ${loading ? "animate-spin" : ""}`}
          />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        <div className="mx-auto max-w-lg space-y-6">

          {config.gh_installed === false && (
            <div className="rounded-md border border-destructive/30 px-4 py-3">
              <div className="mb-2 text-sm font-medium">gh CLI Not Found</div>
              <p className="text-xs text-muted-foreground">
                The GitHub CLI (<code>gh</code>) is not installed on this system.
                Install it to enable the GitHub integration.
              </p>
              <div className="mt-3 rounded bg-muted px-3 py-2 text-xs font-mono">
                brew install gh
              </div>
            </div>
          )}

          {config.gh_installed && config.configured && (
            <div className="rounded-md border px-4 py-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">Connection</span>
                <Badge variant="default">
                  Connected{config.username ? ` as ${config.username}` : ""}
                </Badge>
              </div>
              {config.status_output && (
                <pre className="mt-3 rounded bg-muted px-3 py-2 text-xs overflow-x-auto whitespace-pre-wrap">
                  {config.status_output}
                </pre>
              )}
            </div>
          )}

          {config.gh_installed && !config.configured && (
            <div className="rounded-md border border-amber-500/30 px-4 py-3">
              <div className="mb-2 text-sm font-medium">Not Authenticated</div>
              <p className="text-xs text-muted-foreground mb-3">
                The GitHub CLI is installed but not authenticated.
                Run the following command in your terminal to log in:
              </p>
              <div className="flex items-center gap-2 rounded bg-muted px-3 py-2 text-xs font-mono">
                <Terminal className="size-3 shrink-0 text-muted-foreground" />
                gh auth login
              </div>
              {config.error && (
                <div className="mt-2 text-xs text-destructive">
                  {config.error}
                </div>
              )}
              {config.status_output && (
                <pre className="mt-3 rounded bg-muted px-3 py-2 text-xs overflow-x-auto whitespace-pre-wrap text-muted-foreground">
                  {config.status_output}
                </pre>
              )}
            </div>
          )}

          <div className="text-xs text-muted-foreground space-y-1">
            <p>
              GitHub tools use a three-tier permission system: read-only commands
              run automatically, mutating commands require your approval in chat,
              and dangerous commands are blocked.
            </p>
          </div>

        </div>
      </div>
    </div>
  )
}
