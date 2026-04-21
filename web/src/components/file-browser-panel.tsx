import { useCallback, useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { ChevronRight, File, Folder, ArrowLeft } from "lucide-react"
import type { FileEntry } from "@/lib/types"

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function FileBrowserPanel({ agentId, agentName }: { agentId: string; agentName: string }) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [currentPath, setCurrentPath] = useState("")
  const [entries, setEntries] = useState<FileEntry[]>([])
  const [loading, setLoading] = useState(false)

  const fetchEntries = useCallback(async (path: string) => {
    setLoading(true)
    try {
      const query = path ? `?path=${encodeURIComponent(path)}` : ""
      const res = await fetch(`/api/agents/${agentId}/files${query}`)
      if (res.ok) {
        setEntries(await res.json())
      }
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [agentId])

  useEffect(() => {
    setOpen(false)
    setCurrentPath("")
  }, [agentId])

  useEffect(() => {
    if (open) fetchEntries(currentPath)
  }, [open, currentPath, fetchEntries])

  const navigateToDir = (path: string) => {
    setCurrentPath(path)
  }

  const navigateUp = () => {
    if (!currentPath) {
      setOpen(false)
      return
    }
    const parts = currentPath.split("/").filter(Boolean)
    parts.pop()
    navigateToDir(parts.join("/"))
  }

  const openFile = (entry: FileEntry) => {
    const encodedName = encodeURIComponent(agentName)
    navigate(`/a/${encodedName}/settings/files/${entry.path}`)
  }

  const pathParts = currentPath.split("/").filter(Boolean)
  const dirName = pathParts.length > 0 ? pathParts[pathParts.length - 1] : "workspace"

  if (!open) {
    return (
      <div className="flex flex-col gap-1 px-3 py-2">
        <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mb-0.5">
          Files
        </span>
        <button
          onClick={() => setOpen(true)}
          className="flex items-center gap-1.5 py-0.5 text-left group hover:text-foreground"
        >
          <Folder className="size-3 shrink-0 text-muted-foreground" />
          <span className="text-xs text-muted-foreground truncate group-hover:text-foreground">
            workspace
          </span>
          <ChevronRight className="size-3 shrink-0 ml-auto text-muted-foreground/40" />
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1 px-3 py-2">
      <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mb-0.5">
        Files
      </span>
      <button
        onClick={navigateUp}
        className="flex items-center gap-1.5 py-0.5 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3" />
        <span className="truncate">{dirName}</span>
      </button>
      {loading ? (
        <span className="text-[11px] text-muted-foreground/60 italic py-0.5">Loading...</span>
      ) : entries.length === 0 ? (
        <span className="text-[11px] text-muted-foreground/60 italic py-0.5">Empty</span>
      ) : (
        entries.map((entry) => (
          <button
            key={entry.path}
            onClick={() =>
              entry.type === "directory"
                ? navigateToDir(entry.path)
                : openFile(entry)
            }
            className="flex items-center gap-1.5 py-0.5 text-left group hover:text-foreground"
          >
            {entry.type === "directory" ? (
              <Folder className="size-3 shrink-0 text-muted-foreground" />
            ) : (
              <File className="size-3 shrink-0 text-muted-foreground" />
            )}
            <span className="text-xs text-muted-foreground truncate group-hover:text-foreground">
              {entry.name}
            </span>
            {entry.type === "directory" && (
              <ChevronRight className="size-3 shrink-0 ml-auto text-muted-foreground/40" />
            )}
            {entry.type === "file" && entry.size != null && (
              <span className="text-[10px] text-muted-foreground/40 ml-auto shrink-0">
                {formatSize(entry.size)}
              </span>
            )}
          </button>
        ))
      )}
    </div>
  )
}
