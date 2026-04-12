import { useCallback, useEffect, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import type { FileEntry } from "@/lib/types"
import { ArrowLeft, File, Folder, Save, Trash2 } from "lucide-react"

interface FileBrowserProps {
  agentId: string
}

export function FileBrowser({ agentId }: FileBrowserProps) {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [entries, setEntries] = useState<FileEntry[]>([])
  const [content, setContent] = useState("")
  const [originalContent, setOriginalContent] = useState("")
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(false)

  const currentPath = searchParams.get("dir") ?? ""
  const openFile = searchParams.get("file") ?? null

  const IDENTITY_FILES = new Set(["CLAUDE.md", "SOUL.md", "MEMORY.md"])
  const dirty = content !== originalContent

  const setCurrentPath = useCallback(
    (path: string) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev)
        if (path) next.set("dir", path)
        else next.delete("dir")
        next.delete("file")
        return next
      })
    },
    [setSearchParams],
  )

  const setOpenFile = useCallback(
    (filePath: string | null) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev)
        if (filePath) next.set("file", filePath)
        else next.delete("file")
        return next
      })
    },
    [setSearchParams],
  )

  const fetchEntries = useCallback(
    async (path: string) => {
      setLoading(true)
      const params = path ? `?path=${encodeURIComponent(path)}` : ""
      const res = await fetch(`/api/agents/${agentId}/files${params}`)
      if (res.ok) {
        const data: FileEntry[] = await res.json()
        setEntries(data)
      }
      setLoading(false)
    },
    [agentId],
  )

  useEffect(() => {
    fetchEntries(currentPath)
  }, [currentPath, fetchEntries])

  // Load file content when openFile changes
  useEffect(() => {
    if (!openFile) return
    const load = async () => {
      const res = await fetch(
        `/api/agents/${agentId}/files/${encodeURIComponent(openFile)}`,
      )
      if (res.ok) {
        const text = await res.text()
        setContent(text)
        setOriginalContent(text)
      }
    }
    load()
  }, [agentId, openFile])

  const handleOpenFile = (entry: FileEntry) => {
    if (entry.type === "directory") {
      setCurrentPath(entry.path)
      return
    }
    // Set dir to the file's parent so back button works
    const dir = entry.path.includes("/")
      ? entry.path.substring(0, entry.path.lastIndexOf("/"))
      : ""
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (dir) next.set("dir", dir)
      else next.delete("dir")
      next.set("file", entry.path)
      return next
    })
  }

  const handleSave = async () => {
    if (!openFile) return
    setSaving(true)
    await fetch(`/api/agents/${agentId}/files/${encodeURIComponent(openFile)}`, {
      method: "PUT",
      body: content,
    })
    setOriginalContent(content)
    setSaving(false)
  }

  const handleDelete = async (entry: FileEntry) => {
    if (!confirm(`Delete ${entry.name}?`)) return
    const res = await fetch(
      `/api/agents/${agentId}/files/${encodeURIComponent(entry.path)}`,
      { method: "DELETE" },
    )
    if (res.ok) {
      fetchEntries(currentPath)
    }
  }

  const goUp = () => {
    const parts = currentPath.split("/").filter(Boolean)
    parts.pop()
    setCurrentPath(parts.join("/"))
  }

  if (openFile) {
    const fileName = openFile.split("/").pop() ?? openFile
    const lineCount = content.split("\n").length

    return (
      <div className="flex flex-1 flex-col overflow-hidden">
        <div className="flex items-center gap-3 border-b px-4 py-2">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setOpenFile(null)}
          >
            <ArrowLeft className="size-4" />
          </Button>
          <span className="text-sm font-medium">{fileName}</span>
          <span className="text-xs text-muted-foreground">{openFile}</span>
          <div className="ml-auto">
            <Button size="sm" onClick={handleSave} disabled={!dirty || saving}>
              <Save className="mr-1.5 size-3.5" />
              {saving ? "Saving..." : "Save"}
            </Button>
          </div>
        </div>
        <div className="flex flex-1 overflow-hidden font-mono text-xs">
          <div
            className="shrink-0 select-none border-r bg-muted/50 px-3 py-3 text-right text-muted-foreground"
            aria-hidden
          >
            {Array.from({ length: lineCount }, (_, i) => (
              <div key={i} className="leading-5">
                {i + 1}
              </div>
            ))}
          </div>
          <Textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            className="flex-1 resize-none rounded-none border-0 p-3 leading-5 shadow-none focus-visible:ring-0"
            spellCheck={false}
          />
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center gap-2 border-b px-4 py-2">
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={currentPath ? goUp : () => navigate(`/agents/${agentId}`)}
        >
          <ArrowLeft className="size-4" />
        </Button>
        <span className="text-sm font-medium">
          {currentPath ? `/${currentPath}` : "Workspace"}
        </span>
      </div>
      <div className="flex-1 overflow-y-auto p-3">
        {loading ? (
          <p className="text-xs text-muted-foreground">Loading...</p>
        ) : entries.length === 0 ? (
          <p className="text-xs text-muted-foreground">Empty directory</p>
        ) : (
          <div className="flex flex-col gap-0.5">
            {entries.map((entry) => (
              <div
                key={entry.path}
                className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted"
              >
                <button
                  type="button"
                  onClick={() => handleOpenFile(entry)}
                  className="flex flex-1 items-center gap-2 text-left"
                >
                  {entry.type === "directory" ? (
                    <Folder className="size-4 text-muted-foreground" />
                  ) : (
                    <File className="size-4 text-muted-foreground" />
                  )}
                  <span>{entry.name}</span>
                  {entry.size != null && (
                    <span className="text-xs text-muted-foreground">
                      {entry.size} B
                    </span>
                  )}
                </button>
                {entry.type === "file" && !IDENTITY_FILES.has(entry.name) && (
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => handleDelete(entry)}
                  >
                    <Trash2 className="size-3.5 text-muted-foreground" />
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
