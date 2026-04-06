import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { ArrowLeft, Plus, Square, Trash2, Upload, X } from "lucide-react"

interface SkillSummary {
  id: string
  name: string
  description: string
}

interface SkillDetail extends SkillSummary {
  content: string
  files: string[]
}

export function SkillsPanel({ agentId }: { agentId: string }) {
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [skills, setSkills] = useState<SkillSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [selected, setSelected] = useState<SkillDetail | null>(null)
  const [editing, setEditing] = useState(false)
  const [editContent, setEditContent] = useState("")
  const [newName, setNewName] = useState("")
  const [newDesc, setNewDesc] = useState("")
  const [newContent, setNewContent] = useState("")
  const [saving, setSaving] = useState(false)
  const [stopping, setStopping] = useState(false)

  const fetchSkills = useCallback(async () => {
    const res = await fetch(`/api/agents/${agentId}/skills`)
    if (res.ok) setSkills(await res.json())
    setLoading(false)
  }, [agentId])

  useEffect(() => {
    fetchSkills()
  }, [fetchSkills])

  const handleStop = async () => {
    setStopping(true)
    try {
      const res = await fetch("/api/containers")
      if (res.ok) {
        const containers = await res.json()
        const active = containers.find(
          (c: { agent_id: string; status: string }) =>
            c.agent_id === agentId &&
            ["running", "idle", "starting"].includes(c.status),
        )
        if (active) {
          await fetch(`/api/containers/${active.id}`, { method: "DELETE" })
        }
      }
    } finally {
      setStopping(false)
    }
  }

  const handleCreate = async () => {
    if (!newName.trim()) return
    setSaving(true)
    const res = await fetch(`/api/agents/${agentId}/skills`, {
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
    const res = await fetch(`/api/agents/${agentId}/skills/${skillId}`)
    if (res.ok) {
      const detail: SkillDetail = await res.json()
      setSelected(detail)
      setEditing(false)
      setEditContent(detail.content)
    }
  }

  const handleSave = async () => {
    if (!selected) return
    setSaving(true)
    const res = await fetch(`/api/agents/${agentId}/skills/${selected.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: editContent }),
    })
    if (res.ok) {
      const detail: SkillDetail = await res.json()
      setSelected(detail)
      setEditing(false)
      await fetchSkills()
    }
    setSaving(false)
  }

  const handleDelete = async (skillId: string) => {
    if (!confirm("Delete this skill?")) return
    const res = await fetch(`/api/agents/${agentId}/skills/${skillId}`, {
      method: "DELETE",
    })
    if (res.ok) {
      setSelected(null)
      await fetchSkills()
    }
  }

  const handleUpload = async (files: FileList | null) => {
    if (!files || !selected) return
    const form = new FormData()
    for (const f of files) {
      form.append("files", f)
    }
    const res = await fetch(
      `/api/agents/${agentId}/skills/${selected.id}/files`,
      { method: "POST", body: form },
    )
    if (res.ok) {
      await handleSelect(selected.id)
    }
  }

  const handleDeleteFile = async (filePath: string) => {
    if (!selected) return
    const res = await fetch(
      `/api/agents/${agentId}/skills/${selected.id}/files/${filePath}`,
      { method: "DELETE" },
    )
    if (res.ok) {
      await handleSelect(selected.id)
    }
  }

  // Detail view for a selected skill
  if (selected) {
    return (
      <div className="flex flex-1 flex-col overflow-hidden">
        <div className="flex items-center gap-3 border-b px-4 py-2">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setSelected(null)}
          >
            <ArrowLeft className="size-4" />
          </Button>
          <span className="text-sm font-medium">{selected.name}</span>
          <div className="ml-auto flex items-center gap-2">
            {editing ? (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setEditing(false)
                    setEditContent(selected.content)
                  }}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={handleSave}
                  disabled={saving || editContent === selected.content}
                >
                  {saving ? "Saving..." : "Save"}
                </Button>
              </>
            ) : (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setEditing(true)}
                >
                  Edit
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => handleDelete(selected.id)}
                >
                  <Trash2 className="mr-1.5 size-3.5" />
                  Delete
                </Button>
              </>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          <div className="flex flex-col gap-4">
            {selected.description && (
              <p className="text-sm text-muted-foreground">
                {selected.description}
              </p>
            )}

            <div className="flex flex-col gap-1.5">
              <Label className="text-xs">SKILL.md</Label>
              <Textarea
                value={editing ? editContent : selected.content}
                onChange={(e) => setEditContent(e.target.value)}
                readOnly={!editing}
                className="min-h-64 resize-none font-mono text-xs"
                spellCheck={false}
              />
            </div>

            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <Label className="text-xs">Supporting Files</Label>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <Upload className="mr-1.5 size-3.5" />
                  Upload
                </Button>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  className="hidden"
                  onChange={(e) => handleUpload(e.target.files)}
                />
              </div>
              {selected.files.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No supporting files. Upload scripts, templates, or reference
                  docs.
                </p>
              ) : (
                <div className="flex flex-col gap-1">
                  {selected.files.map((f) => (
                    <div
                      key={f}
                      className="flex items-center justify-between rounded-md border px-3 py-1.5"
                    >
                      <code className="text-xs">{f}</code>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => handleDeleteFile(f)}
                      >
                        <Trash2 className="size-3 text-destructive" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    )
  }

  // List view
  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center gap-3 border-b px-4 py-2">
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => navigate(`/agents/${agentId}`)}
        >
          <ArrowLeft className="size-4" />
        </Button>
        <span className="text-sm font-medium">Skills</span>
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleStop}
            disabled={stopping}
          >
            <Square className="mr-1.5 size-3 fill-current" />
            {stopping ? "Stopping..." : "Stop Worker"}
          </Button>
          <Button size="sm" onClick={() => setShowAdd(true)} disabled={showAdd}>
            <Plus className="mr-1.5 size-3.5" />
            Add Skill
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : (
          <div className="flex flex-col gap-3">
            {skills.length === 0 && !showAdd && (
              <p className="text-sm text-muted-foreground">
                No skills configured. Add one to give this agent reusable
                capabilities.
              </p>
            )}

            {skills.map((skill) => (
              <button
                key={skill.id}
                type="button"
                className="flex flex-col gap-1 rounded-md border px-4 py-3 text-left hover:bg-muted/50"
                onClick={() => handleSelect(skill.id)}
              >
                <span className="text-sm font-medium">{skill.name}</span>
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
                  <span className="text-sm font-medium">Add Skill</span>
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
                      placeholder={"---\nname: review-pr\ndescription: Review a GitHub PR\n---\n\n# Review PR\n\nInstructions here..."}
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

            {skills.length > 0 && (
              <p className="text-xs text-muted-foreground">
                Changes take effect after stopping and restarting the worker.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
