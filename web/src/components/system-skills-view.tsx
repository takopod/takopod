import { useCallback, useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { SkillFilesDialog } from "@/components/skill-files-dialog"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { Separator } from "@/components/ui/separator"
import {
  Info,
  Plus,
  Trash2,
  Upload,
  X,
} from "lucide-react"

interface SkillSummary {
  id: string
  name: string
  description: string
  builtin: boolean
}

interface SkillDetail extends SkillSummary {
  content: string
  files: string[]
}

export function SystemSkillsView() {
  const [skills, setSkills] = useState<SkillSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [showUpload, setShowUpload] = useState(false)
  const [selected, setSelected] = useState<SkillDetail | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [zipFile, setZipFile] = useState<File | null>(null)
  const [zipError, setZipError] = useState("")
  const [uploading, setUploading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const fetchSkills = useCallback(async () => {
    const res = await fetch("/api/skills")
    if (res.ok) setSkills(await res.json())
    setLoading(false)
  }, [])

  useEffect(() => {
    fetchSkills()
  }, [fetchSkills])

  const handleFileSelect = (file: globalThis.File) => {
    setZipError("")
    if (!file.name.endsWith(".zip")) {
      setZipError("Only .zip files are accepted")
      return
    }
    setZipFile(file)
  }

  const closeUploadDialog = () => {
    setShowUpload(false)
    setZipFile(null)
    setZipError("")
  }

  const handleUpload = async () => {
    if (!zipFile) return
    setUploading(true)
    setZipError("")
    const formData = new FormData()
    formData.append("file", zipFile)
    const res = await fetch("/api/skills/upload", {
      method: "POST",
      body: formData,
    })
    if (res.ok) {
      await fetchSkills()
      closeUploadDialog()
    } else {
      const err = await res.json().catch(() => ({ detail: "Upload failed" }))
      setZipError(err.detail || "Upload failed")
    }
    setUploading(false)
  }

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const handleSelect = async (skillId: string) => {
    const res = await fetch(`/api/skills/${skillId}`)
    if (res.ok) {
      setSelected(await res.json())
    }
  }

  const handleDeleteConfirm = async () => {
    if (!confirmDeleteId) return
    const res = await fetch(`/api/skills/${confirmDeleteId}`, {
      method: "DELETE",
    })
    if (res.ok) {
      await fetchSkills()
    }
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="sticky top-0 z-10 flex items-center gap-2 border-b bg-background px-4 py-1.5">
        <SidebarTrigger className="-ml-1" />
        <Separator orientation="vertical" className="mr-1 data-[orientation=vertical]:h-4" />
        <span className="text-sm font-medium">Available Skills</span>
        <div className="ml-auto">
          <Button size="sm" onClick={() => setShowUpload(true)}>
            <Plus className="mr-1.5 size-3.5" />
            Add Skill
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        <div className="mx-auto max-w-2xl">
          <div className="mb-4 flex items-start gap-2.5 rounded-md border border-primary/20 bg-primary/5 px-4 py-3">
            <Info className="mt-0.5 size-4 shrink-0 text-primary" />
            <p className="text-xs text-muted-foreground">
              They are copied to each new agent at creation time. Changes here
              do not affect existing agents.
            </p>
          </div>

          {loading ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : (
            <div className="rounded-md border divide-y">
              {skills.length === 0 && (
                <div className="px-4 py-6 text-center">
                  <p className="text-sm text-muted-foreground">
                    No default skills configured. Add one to give new agents
                    reusable capabilities out of the box.
                  </p>
                </div>
              )}

              {skills
                .sort((a, b) => (b.builtin ? 1 : 0) - (a.builtin ? 1 : 0))
                .map((skill) => (
                <button
                  key={skill.id}
                  type="button"
                  className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-accent/50"
                  onClick={() => handleSelect(skill.id)}
                >
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-medium">{skill.name}</span>
                    {skill.description && (
                      <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                        {skill.description}
                      </p>
                    )}
                  </div>
                  {skill.builtin ? (
                    <Badge variant="outline" className="shrink-0">BUILTIN</Badge>
                  ) : (
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={(e) => {
                        e.stopPropagation()
                        setConfirmDeleteId(skill.id)
                      }}
                    >
                      <Trash2 className="size-3.5 text-destructive" />
                    </Button>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {selected && (
        <SkillFilesDialog
          open
          onOpenChange={(open) => { if (!open) setSelected(null) }}
          skill={selected}
          onSaved={(updated) => {
            setSelected(updated)
            fetchSkills()
          }}
          onDeleted={() => {
            setSelected(null)
            fetchSkills()
          }}
        />
      )}

      <Dialog open={showUpload} onOpenChange={(open) => { if (!open) closeUploadDialog() }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Upload Skill</DialogTitle>
            <DialogDescription>
              Upload a .zip file containing SKILL.md with name and description in the frontmatter.
            </DialogDescription>
          </DialogHeader>

          <input
            ref={fileInputRef}
            type="file"
            accept=".zip"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) handleFileSelect(f)
              e.target.value = ""
            }}
          />

          {!zipFile ? (
            <div
              className={`flex cursor-pointer flex-col items-center gap-2 rounded-md border-2 border-dashed px-4 py-10 transition-colors ${
                dragging
                  ? "border-primary bg-primary/5"
                  : "border-muted-foreground/25 hover:border-muted-foreground/50"
              }`}
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
              onDragEnter={(e) => { e.preventDefault(); setDragging(true) }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDragging(false)
                const f = e.dataTransfer.files[0]
                if (f) handleFileSelect(f)
              }}
            >
              <Upload className="size-6 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                Drop .zip file here or click to browse
              </p>
            </div>
          ) : (
            <div className="flex items-center justify-between rounded-md border bg-muted/50 px-3 py-2.5">
              <div className="flex items-center gap-2 min-w-0">
                <Upload className="size-4 shrink-0 text-muted-foreground" />
                <span className="truncate text-sm">{zipFile.name}</span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {formatSize(zipFile.size)}
                </span>
              </div>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => { setZipFile(null); setZipError("") }}
              >
                <X className="size-3.5" />
              </Button>
            </div>
          )}

          {zipError && (
            <p className="text-xs text-destructive">{zipError}</p>
          )}

          <DialogFooter>
            <Button variant="outline" size="sm" onClick={closeUploadDialog}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={handleUpload}
              disabled={!zipFile || uploading}
            >
              {uploading ? "Uploading..." : "Upload"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={confirmDeleteId !== null}
        onOpenChange={(open) => { if (!open) setConfirmDeleteId(null) }}
        title="Delete skill"
        description="Delete this system skill? This won't affect existing agents."
        confirmLabel="Delete"
        destructive
        onConfirm={handleDeleteConfirm}
      />
    </div>
  )
}
