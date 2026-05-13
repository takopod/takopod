import { useCallback, useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Button } from "@/components/ui/button"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Textarea } from "@/components/ui/textarea"
import type { FileEntry } from "@/lib/types"
import { ArrowLeft, Eye, File, Folder, Pencil, Save } from "lucide-react"

interface FileBrowserProps {
  agentId: string
  agentName?: string
  initialPath?: string
}

const IMAGE_RE = /\.(png|jpe?g|gif|webp|svg|bmp|ico)$/i
const MARKDOWN_RE = /\.md$/i

function formatSize(bytes: number): string {
  if (bytes === 0) return "0 B"
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function sortEntries(entries: FileEntry[]): FileEntry[] {
  const dirs = entries.filter((e) => e.type === "directory").sort((a, b) => a.name.localeCompare(b.name))
  const files = entries.filter((e) => e.type === "file").sort((a, b) => a.name.localeCompare(b.name))
  return [...dirs, ...files]
}

export function FileBrowser({ agentId, agentName, initialPath }: FileBrowserProps) {
  const navigate = useNavigate()
  const [entries, setEntries] = useState<FileEntry[]>([])
  const [content, setContent] = useState("")
  const [originalContent, setOriginalContent] = useState("")
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(false)
  const [openFile, setOpenFile] = useState<string | null>(null)
  const [currentPath, setCurrentPath] = useState("")

  const basePath = `/a/${encodeURIComponent(agentName ?? agentId)}/settings/files`

  const [previewMode, setPreviewMode] = useState(true)

  const isImage = openFile ? IMAGE_RE.test(openFile) : false
  const isMarkdown = openFile ? MARKDOWN_RE.test(openFile) : false
  const dirty = !isImage && content !== originalContent

  useEffect(() => {
    if (!initialPath) {
      setOpenFile(null)
      setCurrentPath("")
      return
    }
    const dir = initialPath.includes("/")
      ? initialPath.substring(0, initialPath.lastIndexOf("/"))
      : ""
    if (IMAGE_RE.test(initialPath)) {
      setOpenFile(initialPath)
      setCurrentPath(dir)
      setContent("")
      setOriginalContent("")
      setPreviewMode(true)
      return
    }
    fetch(`/api/agents/${agentId}/files/${encodeURIComponent(initialPath)}`, { cache: "no-store" })
      .then((res) => {
        if (res.ok) {
          res.text().then((text) => {
            setOpenFile(initialPath)
            setCurrentPath(dir)
            setContent(text)
            setOriginalContent(text)
            setPreviewMode(MARKDOWN_RE.test(initialPath))
          })
        } else {
          setOpenFile(null)
          setCurrentPath(initialPath)
        }
      })
  }, [agentId, initialPath])

  const fetchEntries = useCallback(
    async (path: string) => {
      setLoading(true)
      const params = path ? `?path=${encodeURIComponent(path)}` : ""
      const res = await fetch(`/api/agents/${agentId}/files${params}`, { cache: "no-store" })
      if (res.ok) {
        const data: FileEntry[] = await res.json()
        setEntries(sortEntries(data))
      }
      setLoading(false)
    },
    [agentId],
  )

  useEffect(() => {
    if (!openFile) {
      fetchEntries(currentPath)
    }
  }, [currentPath, openFile, fetchEntries])

  const navigateToFile = (filePath: string) => {
    navigate(`${basePath}/${filePath}`)
  }

  const navigateToDir = (dirPath: string) => {
    if (dirPath) {
      navigate(`${basePath}/${dirPath}`)
    } else {
      navigate(basePath)
    }
  }

  const handleOpenFile = (entry: FileEntry) => {
    if (entry.type === "directory") {
      navigateToDir(entry.path)
      return
    }
    navigateToFile(entry.path)
  }

  const handleCloseFile = () => {
    navigateToDir(currentPath)
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

  const pathSegments = currentPath ? currentPath.split("/").filter(Boolean) : []

  if (openFile) {
    const fileName = openFile.split("/").pop() ?? openFile
    const lineCount = content.split("\n").length

    return (
      <div className="flex flex-1 flex-col overflow-hidden">
        <div className="flex items-center gap-3 border-b px-4 py-2">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={handleCloseFile}
          >
            <ArrowLeft className="size-4" />
          </Button>
          <span className="text-sm font-medium">{fileName}</span>
          <span className="text-xs text-muted-foreground">{openFile}</span>
          {!isImage && (
            <div className="ml-auto flex items-center gap-2">
              {isMarkdown && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPreviewMode(!previewMode)}
                >
                  {previewMode ? (
                    <><Pencil className="mr-1.5 size-3.5" />Edit</>
                  ) : (
                    <><Eye className="mr-1.5 size-3.5" />Preview</>
                  )}
                </Button>
              )}
              <Button size="sm" onClick={handleSave} disabled={!dirty || saving}>
                <Save className="mr-1.5 size-3.5" />
                {saving ? "Saving..." : "Save"}
              </Button>
            </div>
          )}
        </div>
        {isImage ? (
          <div className="flex flex-1 items-center justify-center overflow-auto bg-muted/30 p-4">
            <img
              src={`/api/agents/${agentId}/files/${encodeURIComponent(openFile)}`}
              alt={fileName}
              className="max-h-full max-w-full object-contain"
            />
          </div>
        ) : isMarkdown && previewMode ? (
          <div className="flex-1 overflow-y-auto p-6">
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <Markdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ children, ...props }) => (
                    <a {...props} target="_blank" rel="noopener noreferrer">{children}</a>
                  ),
                }}
              >
                {content}
              </Markdown>
            </div>
          </div>
        ) : (
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
        )}
      </div>
    )
  }

  const dirCount = entries.filter((e) => e.type === "directory").length
  const fileCount = entries.filter((e) => e.type === "file").length

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center gap-2 border-b px-4 py-2">
        <Breadcrumb>
          <BreadcrumbList>
            <BreadcrumbItem>
              {pathSegments.length > 0 ? (
                <BreadcrumbLink
                  className="cursor-pointer"
                  onClick={() => navigateToDir("")}
                >
                  Workspace
                </BreadcrumbLink>
              ) : (
                <BreadcrumbPage>Workspace</BreadcrumbPage>
              )}
            </BreadcrumbItem>
            {pathSegments.map((seg, i) => {
              const segPath = pathSegments.slice(0, i + 1).join("/")
              const isLast = i === pathSegments.length - 1
              return (
                <span key={segPath} className="contents">
                  <BreadcrumbSeparator />
                  <BreadcrumbItem>
                    {isLast ? (
                      <BreadcrumbPage>{seg}</BreadcrumbPage>
                    ) : (
                      <BreadcrumbLink
                        className="cursor-pointer"
                        onClick={() => navigateToDir(segPath)}
                      >
                        {seg}
                      </BreadcrumbLink>
                    )}
                  </BreadcrumbItem>
                </span>
              )
            })}
          </BreadcrumbList>
        </Breadcrumb>
        {!loading && entries.length > 0 && (
          <span className="ml-auto text-xs text-muted-foreground">
            {dirCount > 0 && `${dirCount} ${dirCount === 1 ? "folder" : "folders"}`}
            {dirCount > 0 && fileCount > 0 && ", "}
            {fileCount > 0 && `${fileCount} ${fileCount === 1 ? "file" : "files"}`}
          </span>
        )}
      </div>
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <p className="p-4 text-xs text-muted-foreground">Loading...</p>
        ) : entries.length === 0 ? (
          <p className="p-4 text-xs text-muted-foreground">Empty directory</p>
        ) : (
          <div className="divide-y">
            {entries.map((entry) => (
              <button
                key={entry.path}
                type="button"
                onClick={() => handleOpenFile(entry)}
                className="flex w-full items-center gap-3 px-4 py-2 text-left text-sm transition-colors hover:bg-accent/50"
              >
                {entry.type === "directory" ? (
                  <Folder className="size-4 shrink-0 text-muted-foreground" />
                ) : (
                  <File className="size-4 shrink-0 text-muted-foreground" />
                )}
                <span className={entry.type === "directory" ? "font-medium" : ""}>
                  {entry.name}
                </span>
                {entry.size != null && (
                  <span className="ml-auto text-xs text-muted-foreground">
                    {formatSize(entry.size)}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
