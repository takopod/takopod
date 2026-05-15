import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { SkillFilesDialog } from "@/components/skill-files-dialog"
import {
  Eye,
  Loader2,
  MoreHorizontal,
  Package,
  Plus,
  Search,
  Sparkles,
  Trash2,
  Upload,
  Wrench,
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

  const [activeTab, setActiveTab] = useState("all")
  const [searchQuery, setSearchQuery] = useState("")

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

  const builtinCount = skills.filter((s) => s.builtin).length
  const customCount = skills.filter((s) => !s.builtin).length

  const filteredSkills = useMemo(() => {
    let result = [...skills].sort((a, b) => (b.builtin ? 1 : 0) - (a.builtin ? 1 : 0))
    if (activeTab === "builtin") result = result.filter((s) => s.builtin)
    if (activeTab === "custom") result = result.filter((s) => !s.builtin)
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      result = result.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          s.description.toLowerCase().includes(q)
      )
    }
    return result
  }, [skills, activeTab, searchQuery])

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">Skills</h2>
            <p className="text-xs text-muted-foreground">
              Manage reusable capabilities available to new agents
            </p>
          </div>
          <Button size="sm" onClick={() => setShowUpload(true)}>
            <Plus className="mr-1 size-3.5" />
            Add Skill
          </Button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl space-y-5 p-5">
          {/* Stat Cards */}
          <div className="grid grid-cols-3 gap-3">
            <Card size="sm" className="gap-0">
              <CardContent className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-lg bg-muted">
                  <Wrench className="size-4 text-muted-foreground" />
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Total</p>
                  <p className="text-xl font-semibold tracking-tight">{skills.length}</p>
                </div>
              </CardContent>
            </Card>
            <Card size="sm" className="gap-0">
              <CardContent className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-lg bg-blue-500/10">
                  <Package className="size-4 text-blue-600 dark:text-blue-400" />
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Builtin</p>
                  <p className="text-xl font-semibold tracking-tight">{builtinCount}</p>
                </div>
              </CardContent>
            </Card>
            <Card size="sm" className="gap-0">
              <CardContent className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-lg bg-purple-500/10">
                  <Sparkles className="size-4 text-purple-600 dark:text-purple-400" />
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Custom</p>
                  <p className="text-xl font-semibold tracking-tight">{customCount}</p>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Tabs + Search */}
          <div className="flex items-center justify-between gap-4">
            <Tabs value={activeTab} onValueChange={setActiveTab}>
              <TabsList>
                <TabsTrigger value="all">
                  All
                  <Badge variant="secondary" className="ml-1 h-4 min-w-5 px-1 text-[10px]">
                    {skills.length}
                  </Badge>
                </TabsTrigger>
                <TabsTrigger value="builtin">
                  Builtin
                  <Badge variant="secondary" className="ml-1 h-4 min-w-5 px-1 text-[10px]">
                    {builtinCount}
                  </Badge>
                </TabsTrigger>
                <TabsTrigger value="custom">
                  Custom
                  <Badge variant="secondary" className="ml-1 h-4 min-w-5 px-1 text-[10px]">
                    {customCount}
                  </Badge>
                </TabsTrigger>
              </TabsList>
            </Tabs>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Search skills..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-8 w-56 pl-8 text-sm"
              />
            </div>
          </div>

          {/* Data Table */}
          <div className="rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="pl-4">Name</TableHead>
                  <TableHead className="min-w-[250px]">Description</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead className="w-10 pr-4"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading && (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={4} className="h-32 text-center">
                      <div className="flex items-center justify-center gap-2 text-muted-foreground">
                        <Loader2 className="size-4 animate-spin" />
                        <span className="text-sm">Loading skills...</span>
                      </div>
                    </TableCell>
                  </TableRow>
                )}
                {!loading && filteredSkills.length === 0 && (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={4} className="h-32 text-center">
                      <div className="flex flex-col items-center gap-1.5 text-muted-foreground">
                        <Wrench className="size-8 opacity-30" />
                        <p className="text-sm">
                          {skills.length === 0
                            ? "No skills configured"
                            : "No skills match your filters"}
                        </p>
                        {skills.length === 0 && (
                          <p className="text-xs">
                            Add a skill to give new agents reusable capabilities.
                          </p>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                )}
                {filteredSkills.map((skill) => (
                  <TableRow
                    key={skill.id}
                    className="cursor-pointer"
                    onClick={() => handleSelect(skill.id)}
                  >
                    {/* Name */}
                    <TableCell className="pl-4">
                      <span className="text-sm font-medium">{skill.name}</span>
                    </TableCell>

                    {/* Description */}
                    <TableCell>
                      {skill.description ? (
                        <TooltipProvider>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <p className="max-w-[350px] truncate text-sm text-muted-foreground">
                                {skill.description}
                              </p>
                            </TooltipTrigger>
                            <TooltipContent side="bottom" className="max-w-sm">
                              <span>{skill.description}</span>
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      ) : (
                        <span className="text-xs text-muted-foreground">--</span>
                      )}
                    </TableCell>

                    {/* Source */}
                    <TableCell>
                      {skill.builtin ? (
                        <Badge
                          variant="outline"
                          className="border-blue-500/30 bg-blue-500/10 text-[11px] font-normal text-blue-700 dark:text-blue-400"
                        >
                          builtin
                        </Badge>
                      ) : (
                        <Badge
                          variant="outline"
                          className="border-purple-500/30 bg-purple-500/10 text-[11px] font-normal text-purple-700 dark:text-purple-400"
                        >
                          custom
                        </Badge>
                      )}
                    </TableCell>

                    {/* Actions */}
                    <TableCell className="pr-4">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <MoreHorizontal className="size-3.5" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem onClick={(e) => { e.stopPropagation(); handleSelect(skill.id) }}>
                            <Eye className="size-4" />
                            View
                          </DropdownMenuItem>
                          {!skill.builtin && (
                            <>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem
                                variant="destructive"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setConfirmDeleteId(skill.id)
                                }}
                              >
                                <Trash2 className="size-4" />
                                Delete
                              </DropdownMenuItem>
                            </>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {filteredSkills.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Showing {filteredSkills.length} of {skills.length} skill{skills.length !== 1 ? "s" : ""}
            </p>
          )}
        </div>
      </div>

      {/* ── Skill Detail Dialog ── */}
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

      {/* ── Upload Dialog ── */}
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
