import { useCallback, useEffect, useMemo, useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { FileEditor } from "@/components/file-editor"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import {
  ChevronDown,
  ChevronRight,
  File,
  FileCode,
  FileJson,
  FileText,
  Folder,
  FolderOpen,
  Loader2,
  RotateCcw,
  Trash2,
} from "lucide-react"

interface SkillDetail {
  id: string
  name: string
  description: string
  builtin: boolean
  content: string
  files: string[]
}

interface FileNode {
  name: string
  path: string
  children?: FileNode[]
}

function buildFileTree(files: string[]): FileNode[] {
  const root: FileNode[] = []
  for (const filePath of files) {
    const parts = filePath.split("/")
    let current = root
    for (let i = 0; i < parts.length; i++) {
      const name = parts[i]
      const isFile = i === parts.length - 1
      const existing = current.find((n) => n.name === name)
      if (existing) {
        current = existing.children || []
      } else {
        const node: FileNode = { name, path: filePath }
        if (!isFile) {
          node.children = []
        }
        current.push(node)
        current = node.children || []
      }
    }
  }
  return root
}

function getFileIcon(name: string) {
  const ext = name.split(".").pop()?.toLowerCase()
  switch (ext) {
    case "md":
      return FileText
    case "json":
    case "jsonl":
      return FileJson
    case "py":
    case "ts":
    case "tsx":
    case "js":
    case "jsx":
    case "sh":
    case "yaml":
    case "yml":
    case "toml":
      return FileCode
    default:
      return File
  }
}

function getLanguageLabel(name: string): string | null {
  const ext = name.split(".").pop()?.toLowerCase()
  switch (ext) {
    case "md": return "Markdown"
    case "py": return "Python"
    case "ts": return "TypeScript"
    case "tsx": return "TSX"
    case "js": return "JavaScript"
    case "jsx": return "JSX"
    case "json": return "JSON"
    case "jsonl": return "JSONL"
    case "yaml": case "yml": return "YAML"
    case "toml": return "TOML"
    case "sh": return "Shell"
    case "css": return "CSS"
    case "html": return "HTML"
    case "sql": return "SQL"
    case "txt": return "Text"
    default: return null
  }
}

function isMarkdown(name: string) {
  return name.toLowerCase().endsWith(".md")
}

function TreeNode({
  node,
  depth = 0,
  selectedPath,
  onSelect,
}: {
  node: FileNode
  depth?: number
  selectedPath: string | null
  onSelect: (path: string) => void
}) {
  const [open, setOpen] = useState(true)
  const isDir = !!node.children

  if (isDir) {
    return (
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger
          className="flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-[13px] text-muted-foreground hover:bg-accent/60 hover:text-foreground transition-colors"
          style={{ paddingLeft: `${depth * 14 + 6}px` }}
        >
          {open ? (
            <ChevronDown className="size-3 shrink-0 text-muted-foreground/60" />
          ) : (
            <ChevronRight className="size-3 shrink-0 text-muted-foreground/60" />
          )}
          {open ? (
            <FolderOpen className="size-3.5 shrink-0 text-amber-500/80" />
          ) : (
            <Folder className="size-3.5 shrink-0 text-amber-500/80" />
          )}
          <span className="truncate">{node.name}</span>
        </CollapsibleTrigger>
        <CollapsibleContent>
          {node.children!.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              onSelect={onSelect}
            />
          ))}
        </CollapsibleContent>
      </Collapsible>
    )
  }

  const Icon = getFileIcon(node.name)
  const isSelected = selectedPath === node.path

  return (
    <button
      type="button"
      className={`flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-[13px] transition-colors ${
        isSelected
          ? "bg-accent text-accent-foreground"
          : "text-muted-foreground hover:bg-accent/40 hover:text-foreground"
      }`}
      style={{ paddingLeft: `${depth * 14 + 22}px` }}
      onClick={() => onSelect(node.path)}
    >
      <Icon className="size-3.5 shrink-0" />
      <span className="truncate">{node.name}</span>
    </button>
  )
}

interface SkillFilesDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  skill: SkillDetail
  onSaved?: (updated: SkillDetail) => void
  onDeleted?: () => void
}

export function SkillFilesDialog({
  open,
  onOpenChange,
  skill,
  onSaved,
  onDeleted,
}: SkillFilesDialogProps) {
  const allFiles = useMemo(() => ["SKILL.md", ...skill.files], [skill.files])
  const fileTree = useMemo(() => buildFileTree(allFiles), [allFiles])
  const [selectedPath, setSelectedPath] = useState<string>("SKILL.md")
  const [fileContent, setFileContent] = useState<string>("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editContent, setEditContent] = useState(skill.content)
  const [saving, setSaving] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const isSkillMd = selectedPath === "SKILL.md"
  const dirty = isSkillMd && editContent !== skill.content

  useEffect(() => {
    if (open) {
      setSelectedPath("SKILL.md")
      setEditContent(skill.content)
    }
  }, [open, skill.content])

  const fetchFile = useCallback(async (filePath: string) => {
    if (filePath === "SKILL.md") return
    setLoading(true)
    setError(null)
    setFileContent("")
    try {
      const res = await fetch(`/api/skills/${skill.id}/files/${filePath}`)
      if (!res.ok) {
        setError(`Failed to load file (${res.status})`)
        setFileContent("")
        return
      }
      setFileContent(await res.text())
    } catch {
      setError("Failed to load file")
      setFileContent("")
    } finally {
      setLoading(false)
    }
  }, [skill.id])

  useEffect(() => {
    if (open && selectedPath && selectedPath !== "SKILL.md") {
      fetchFile(selectedPath)
    }
  }, [open, selectedPath, fetchFile])

  const handleSave = async () => {
    setSaving(true)
    const res = await fetch(`/api/skills/${skill.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: editContent }),
    })
    if (res.ok) {
      const updated: SkillDetail = await res.json()
      setEditContent(updated.content)
      onSaved?.(updated)
    }
    setSaving(false)
  }

  const handleReset = async () => {
    setSaving(true)
    const res = await fetch(`/api/skills/${skill.id}/reset`, { method: "POST" })
    if (res.ok) {
      const updated: SkillDetail = await res.json()
      setEditContent(updated.content)
      onSaved?.(updated)
    }
    setSaving(false)
  }

  const handleDelete = async () => {
    const res = await fetch(`/api/skills/${skill.id}`, { method: "DELETE" })
    if (res.ok) {
      onOpenChange(false)
      onDeleted?.()
    }
  }

  const fileName = selectedPath?.split("/").pop() || ""
  const langLabel = getLanguageLabel(fileName)
  const isMd = isMarkdown(fileName)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton
        className="!max-w-none !w-[70vw] !h-[70vh] !p-0 flex flex-col overflow-hidden !gap-0"
      >
        <div className="flex items-center gap-3 border-b pl-4 pr-12 py-2.5 shrink-0">
          <DialogTitle className="text-sm font-medium truncate">{skill.name}</DialogTitle>
          {skill.description && (
            <span className="text-xs text-muted-foreground truncate">{skill.description}</span>
          )}
          <div className="ml-auto flex items-center gap-2">
            {skill.builtin && <Badge variant="outline">BUILTIN</Badge>}
          </div>
        </div>

        <div className="flex flex-1 min-h-0">
          <div className="w-56 shrink-0 border-r bg-muted/30">
            <ScrollArea className="h-full">
              <div className="p-2 space-y-0.5">
                {fileTree.map((node) => (
                  <TreeNode
                    key={node.path}
                    node={node}
                    selectedPath={selectedPath}
                    onSelect={setSelectedPath}
                  />
                ))}
              </div>
            </ScrollArea>
          </div>

          <div className="flex-1 flex flex-col min-w-0 min-h-0">
            {!isSkillMd && (
              <div className="flex items-center gap-2 border-b px-4 py-1.5 bg-muted/20 shrink-0">
                <span className="text-xs text-muted-foreground font-mono truncate">
                  {selectedPath}
                </span>
                {langLabel && (
                  <Badge variant="outline" className="ml-auto shrink-0 text-[10px] px-1.5 py-0">
                    {langLabel}
                  </Badge>
                )}
              </div>
            )}

            {isSkillMd ? (
              <FileEditor
                value={editContent}
                onChange={setEditContent}
                markdown
              />
            ) : (
              <ScrollArea className="flex-1">
                {loading ? (
                  <div className="flex items-center justify-center h-full min-h-40">
                    <Loader2 className="size-5 animate-spin text-muted-foreground" />
                  </div>
                ) : error ? (
                  <div className="flex items-center justify-center h-full min-h-40">
                    <p className="text-sm text-destructive">{error}</p>
                  </div>
                ) : isMd ? (
                  <div className="p-6">
                    <div className="prose prose-sm dark:prose-invert max-w-none">
                      <Markdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                          a: ({ children, ...props }) => (
                            <a {...props} target="_blank" rel="noopener noreferrer">{children}</a>
                          ),
                        }}
                      >
                        {fileContent}
                      </Markdown>
                    </div>
                  </div>
                ) : (
                  <div className="font-mono text-xs">
                    <div className="flex min-h-full">
                      <div
                        className="shrink-0 select-none border-r bg-muted/40 px-3 py-3 text-right text-muted-foreground/50"
                        aria-hidden
                      >
                        {fileContent.split("\n").map((_, i) => (
                          <div key={i} className="leading-5">{i + 1}</div>
                        ))}
                      </div>
                      <pre className="flex-1 p-3 leading-5 overflow-x-auto whitespace-pre">
                        {fileContent}
                      </pre>
                    </div>
                  </div>
                )}
              </ScrollArea>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 border-t px-4 py-2 shrink-0">
          {skill.builtin ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setConfirmReset(true)}
              disabled={saving}
            >
              <RotateCcw className="mr-1.5 size-3.5" />
              Reset
            </Button>
          ) : (
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setConfirmDelete(true)}
            >
              <Trash2 className="mr-1.5 size-3.5" />
              Delete
            </Button>
          )}
          <div className="ml-auto">
            <Button
              size="sm"
              onClick={handleSave}
              disabled={!dirty || saving}
            >
              {saving ? "Saving..." : "Save"}
            </Button>
          </div>
        </div>

        <ConfirmDialog
          open={confirmReset}
          onOpenChange={setConfirmReset}
          title="Reset skill"
          description={`Reset "${skill.name}" to its default content? This cannot be undone.`}
          confirmLabel="Reset"
          destructive
          onConfirm={handleReset}
        />
        <ConfirmDialog
          open={confirmDelete}
          onOpenChange={setConfirmDelete}
          title="Delete skill"
          description="Delete this system skill? This won't affect existing agents."
          confirmLabel="Delete"
          destructive
          onConfirm={handleDelete}
        />
      </DialogContent>
    </Dialog>
  )
}
