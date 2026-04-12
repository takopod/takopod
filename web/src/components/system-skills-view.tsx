import { useCallback, useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { FileEditor } from "@/components/file-editor"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { Separator } from "@/components/ui/separator"
import { Badge } from "@/components/ui/badge"
import { Info, Plus, Trash2, RotateCcw, X, ArrowLeft } from "lucide-react"

interface SkillSummary {
  id: string
  name: string
  description: string
  builtin: boolean
}

interface SkillDetail extends SkillSummary {
  content: string
}

export function SystemSkillsView() {
  const [skills, setSkills] = useState<SkillSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [selected, setSelected] = useState<SkillDetail | null>(null)
  const [editContent, setEditContent] = useState("")
  const [newName, setNewName] = useState("")
  const [newDesc, setNewDesc] = useState("")
  const [newContent, setNewContent] = useState("")
  const [saving, setSaving] = useState(false)

  const fetchSkills = useCallback(async () => {
    const res = await fetch("/api/skills")
    if (res.ok) setSkills(await res.json())
    setLoading(false)
  }, [])

  useEffect(() => {
    fetchSkills()
  }, [fetchSkills])

  const handleCreate = async () => {
    if (!newName.trim()) return
    setSaving(true)
    const res = await fetch("/api/skills", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: newName.trim(),
        description: newDesc.trim(),
        content: newContent.trim(),
      }),
    })
    if (res.ok) {
      await fetchSkills()
      setShowAdd(false)
      setNewName("")
      setNewDesc("")
      setNewContent("")
    }
    setSaving(false)
  }

  const handleSelect = async (skillId: string) => {
    const res = await fetch(`/api/skills/${skillId}`)
    if (res.ok) {
      const detail: SkillDetail = await res.json()
      setSelected(detail)
      setEditContent(detail.content)
    }
  }

  const handleSave = async () => {
    if (!selected) return
    setSaving(true)
    const res = await fetch(`/api/skills/${selected.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: editContent }),
    })
    if (res.ok) {
      const detail: SkillDetail = await res.json()
      setSelected(detail)
      setEditContent(detail.content)
      await fetchSkills()
    }
    setSaving(false)
  }

  const handleReset = async () => {
    if (!selected) return
    if (!confirm(`Reset "${selected.name}" to its default content? This cannot be undone.`)) return
    setSaving(true)
    const res = await fetch(`/api/skills/${selected.id}/reset`, {
      method: "POST",
    })
    if (res.ok) {
      const detail: SkillDetail = await res.json()
      setSelected(detail)
      setEditContent(detail.content)
      await fetchSkills()
    }
    setSaving(false)
  }

  const handleDelete = async (skillId: string) => {
    if (!confirm("Delete this system skill? This won't affect existing agents.")) return
    const res = await fetch(`/api/skills/${skillId}`, {
      method: "DELETE",
    })
    if (res.ok) {
      setSelected(null)
      await fetchSkills()
    }
  }

  const dirty = selected !== null && editContent !== selected.content

  // Detail view for a selected skill
  if (selected) {
    return (
      <div className="flex flex-1 flex-col overflow-hidden">
        <div className="sticky top-0 z-10 flex items-center gap-2 border-b bg-background px-4 py-1.5">
          <SidebarTrigger className="-ml-1" />
          <Separator orientation="vertical" className="mr-1 data-[orientation=vertical]:h-4" />
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setSelected(null)}
          >
            <ArrowLeft className="size-4" />
          </Button>
          <span className="text-sm font-medium">{selected.name}</span>
          {selected.description && (
            <span className="text-xs text-muted-foreground truncate">
              {selected.description}
            </span>
          )}
          <div className="ml-auto flex items-center gap-2">
            {selected.builtin ? (
              <Button
                variant="outline"
                size="sm"
                onClick={handleReset}
                disabled={saving}
              >
                <RotateCcw className="mr-1.5 size-3.5" />
                Reset
              </Button>
            ) : (
              <Button
                variant="destructive"
                size="sm"
                onClick={() => handleDelete(selected.id)}
              >
                <Trash2 className="mr-1.5 size-3.5" />
                Delete
              </Button>
            )}
            <Button
              size="sm"
              onClick={handleSave}
              disabled={!dirty || saving}
            >
              {saving ? "Saving..." : "Save"}
            </Button>
          </div>
        </div>

        <FileEditor
          value={editContent}
          onChange={(v) => setEditContent(v)}
        />
      </div>
    )
  }

  // List view
  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="sticky top-0 z-10 flex items-center gap-2 border-b bg-background px-4 py-1.5">
        <SidebarTrigger className="-ml-1" />
        <Separator orientation="vertical" className="mr-1 data-[orientation=vertical]:h-4" />
        <span className="text-sm font-medium">Default Skills</span>
        <div className="ml-auto">
          <Button size="sm" onClick={() => setShowAdd(true)} disabled={showAdd}>
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
              These are system-level default skills. They are copied to each new
              agent at creation time. Changes here do not affect existing agents.
            </p>
          </div>

          {loading ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : (
            <div className="flex flex-col gap-3">
              {skills.length === 0 && !showAdd && (
                <p className="text-sm text-muted-foreground">
                  No default skills configured. Add one to give new agents
                  reusable capabilities out of the box.
                </p>
              )}

              {skills.map((skill) => (
                <button
                  key={skill.id}
                  type="button"
                  className="flex flex-col gap-1 rounded-md border px-4 py-3 text-left hover:bg-muted/50"
                  onClick={() => handleSelect(skill.id)}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{skill.name}</span>
                    {skill.builtin && (
                      <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                        builtin
                      </Badge>
                    )}
                  </div>
                  {skill.description && (
                    <span className="text-xs text-muted-foreground">
                      {skill.description}
                    </span>
                  )}
                </button>
              ))}

              {showAdd && (
                <div className="rounded-md border p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <span className="text-sm font-medium">Add Default Skill</span>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => setShowAdd(false)}
                    >
                      <X className="size-4" />
                    </Button>
                  </div>
                  <div className="flex flex-col gap-3">
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="skill-name" className="text-xs">
                        Name (lowercase, hyphens)
                      </Label>
                      <Input
                        id="skill-name"
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        placeholder="e.g. review-pr"
                        autoFocus
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="skill-desc" className="text-xs">
                        Description
                      </Label>
                      <Input
                        id="skill-desc"
                        value={newDesc}
                        onChange={(e) => setNewDesc(e.target.value)}
                        placeholder="When to use this skill"
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="skill-content" className="text-xs">
                        SKILL.md Content (optional, auto-generated if empty)
                      </Label>
                      <Textarea
                        id="skill-content"
                        value={newContent}
                        onChange={(e) => setNewContent(e.target.value)}
                        placeholder={
                          "---\nname: review-pr\ndescription: Review a GitHub PR\n---\n\n# Review PR\n\nInstructions here..."
                        }
                        className="min-h-32 resize-none font-mono text-xs"
                        spellCheck={false}
                      />
                    </div>
                    <div className="flex justify-end gap-2 pt-1">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setShowAdd(false)}
                      >
                        Cancel
                      </Button>
                      <Button
                        size="sm"
                        onClick={handleCreate}
                        disabled={!newName.trim() || saving}
                      >
                        {saving ? "Creating..." : "Create"}
                      </Button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
