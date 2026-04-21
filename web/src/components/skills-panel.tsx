import { useCallback, useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import { FileEditor } from "@/components/file-editor"
import { ArrowLeft, Pencil, Plus, Search, Square, X } from "lucide-react"

interface RegistrySkill {
  id: string
  name: string
  description: string
  builtin: boolean
  enabled: boolean
  always_enabled: boolean
}

interface SkillDetail {
  id: string
  name: string
  description: string
  content: string
  files: string[]
  builtin: boolean
}

interface CustomSkill {
  id: string
  name: string
  description: string
}

interface SkillDraftSummary {
  id: string
  name: string
  description: string
  files: string[]
}

interface SkillDraftDetail {
  id: string
  name: string
  description: string
  content: string
  files: string[]
}

export function SkillsPanel({ agentId, agentName, initialPath }: { agentId: string; agentName?: string; initialPath?: string }) {
  const navigate = useNavigate()
  const basePath = `/a/${encodeURIComponent(agentName ?? agentId)}/settings/skills`
  // Parse initialPath: "draft/deploy-to-aws" or "skill/git-workflow"
  const pathParts = initialPath?.split("/") ?? []
  const viewType = pathParts[0] === "draft" || pathParts[0] === "skill" ? pathParts[0] : null
  const viewId = pathParts[1] ?? null
  const [skills, setSkills] = useState<RegistrySkill[]>([])
  const [available, setAvailable] = useState<RegistrySkill[]>([])
  const [availableLoaded, setAvailableLoaded] = useState(false)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<SkillDetail | null>(null)
  const [stopping, setStopping] = useState(false)
  const [toggling, setToggling] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const [searchFocused, setSearchFocused] = useState(false)
  const [customSkills, setCustomSkills] = useState<CustomSkill[]>([])
  const [drafts, setDrafts] = useState<SkillDraftSummary[]>([])
  const [selectedDraft, setSelectedDraft] = useState<SkillDraftDetail | null>(null)
  const [draftEditing, setDraftEditing] = useState(false)
  const [draftEditContent, setDraftEditContent] = useState("")
  const [draftError, setDraftError] = useState<string | null>(null)

  const fetchSkills = useCallback(async () => {
    const res = await fetch(`/api/agents/${agentId}/registry-skills`)
    if (res.ok) {
      const data = await res.json()
      setSkills(data.skills || [])
    }
    setLoading(false)
  }, [agentId])

  const fetchCustomSkills = useCallback(async () => {
    try {
      const res = await fetch(`/api/agents/${agentId}/skills`)
      if (res.ok) {
        const data: CustomSkill[] = await res.json()
        // Filter out skills that are already in the registry list
        setCustomSkills(data.filter((s) => !skills.some((rs) => rs.id === s.id)))
      }
    } catch {
      // ignore
    }
  }, [agentId, skills])

  const fetchDrafts = useCallback(async () => {
    try {
      const res = await fetch(`/api/agents/${agentId}/skill-drafts`)
      if (res.ok) {
        setDrafts(await res.json())
      }
    } catch {
      // ignore
    }
  }, [agentId])

  const fetchAvailable = useCallback(async () => {
    if (availableLoaded) return
    const res = await fetch(`/api/agents/${agentId}/registry-skills`)
    if (res.ok) {
      const data = await res.json()
      setAvailable(data.available || [])
    }
    setAvailableLoaded(true)
  }, [agentId, availableLoaded])

  useEffect(() => {
    fetchSkills()
    fetchDrafts()
    fetchCustomSkills()
  }, [fetchSkills, fetchDrafts, fetchCustomSkills])

  // Load skill/draft detail when URL params change (enables browser back)
  useEffect(() => {
    if (viewType === "draft" && viewId) {
      fetch(`/api/agents/${agentId}/skill-drafts/${viewId}`)
        .then((res) => res.ok ? res.json() : null)
        .then((data) => { if (data) { setSelectedDraft(data); setSelected(null); setDraftEditing(false); setDraftError(null) } })
    } else if (viewType === "skill" && viewId) {
      fetch(`/api/agents/${agentId}/skills/${viewId}`)
        .then((res) => res.ok ? res.json() : fetch(`/api/skills/${viewId}`))
        .then((res) => res instanceof Response ? (res.ok ? res.json() : null) : res)
        .then((data) => { if (data) { setSelected(data); setSelectedDraft(null); setDraftEditing(false) } })
    } else {
      setSelected(null)
      setSelectedDraft(null)
      setDraftEditing(false)
    }
  }, [viewType, viewId, agentId])

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

  const handleToggle = async (skillId: string, enabled: boolean) => {
    setToggling(skillId)
    const res = await fetch(`/api/agents/${agentId}/registry-skills/${skillId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    })
    if (res.ok) {
      setSkills((prev) =>
        prev.map((s) => (s.id === skillId ? { ...s, enabled } : s)),
      )
    }
    setToggling(null)
  }

  const handleAdd = async (skillId: string) => {
    const res = await fetch(`/api/agents/${agentId}/registry-skills/${skillId}`, {
      method: "POST",
    })
    if (res.ok) {
      setSearch("")
      setAvailableLoaded(false)
      setAvailable([])
      await fetchSkills()
    }
  }

  const handleRemove = async (skillId: string) => {
    const res = await fetch(`/api/agents/${agentId}/registry-skills/${skillId}`, {
      method: "DELETE",
    })
    if (res.ok) {
      setAvailableLoaded(false)
      setAvailable([])
      await fetchSkills()
    }
  }

  const handleSelect = (skillId: string) => {
    navigate(`${basePath}/skill/${skillId}`)
  }

  const handleSelectDraft = (draftId: string) => {
    navigate(`${basePath}/draft/${draftId}`)
  }

  const handleApproveDraft = async (draftId: string) => {
    setDraftError(null)
    const res = await fetch(
      `/api/agents/${agentId}/skill-drafts/${draftId}/approve`,
      { method: "POST" },
    )
    if (res.ok) {
      navigate(basePath)
      fetchDrafts()
      fetchSkills()
      fetchCustomSkills()
    } else if (res.status === 409) {
      setDraftError("A skill with this name already exists.")
    }
  }

  const handleRejectDraft = async (draftId: string) => {
    const res = await fetch(
      `/api/agents/${agentId}/skill-drafts/${draftId}/reject`,
      { method: "POST" },
    )
    if (res.ok) {
      navigate(basePath)
      fetchDrafts()
    }
  }

  const handleSaveDraftEdit = async (draftId: string) => {
    const res = await fetch(`/api/agents/${agentId}/skill-drafts/${draftId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: draftEditContent }),
    })
    if (res.ok) {
      const updated: SkillDraftDetail = await res.json()
      setSelectedDraft(updated)
      setDraftEditing(false)
    }
  }

  const filtered = available
    .filter((s) => s.name.toLowerCase().includes(search.toLowerCase()))
    .slice(0, 5)

  // Detail view for a selected draft
  if (selectedDraft) {
    return (
      <div className="flex flex-1 flex-col overflow-hidden">
        <div className="flex items-center gap-3 border-b px-4 py-2">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => navigate(basePath)}
          >
            <ArrowLeft className="size-4" />
          </Button>
          <span className="text-sm font-medium">{selectedDraft.name}</span>
          <span className="text-[10px] rounded bg-amber-500/10 text-amber-600 px-1.5 py-0.5 font-medium">
            DRAFT
          </span>
        </div>

        <FileEditor
          value={draftEditing ? draftEditContent : selectedDraft.content}
          onChange={draftEditing ? setDraftEditContent : undefined}
          readOnly={!draftEditing}
        />

        {selectedDraft.files.length > 0 && (
          <div className="border-t px-4 py-2">
            <span className="text-xs text-muted-foreground">
              Supporting files: {selectedDraft.files.join(", ")}
            </span>
          </div>
        )}

        {draftError && (
          <div className="px-4 py-2 text-xs text-destructive">
            {draftError}
          </div>
        )}

        <div className="flex items-center gap-2 border-t px-4 py-2">
          {draftEditing ? (
            <>
              <Button size="sm" onClick={() => handleSaveDraftEdit(selectedDraft.id)}>
                Save
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setDraftEditing(false)}
              >
                Cancel
              </Button>
            </>
          ) : (
            <>
              <Button size="sm" onClick={() => handleApproveDraft(selectedDraft.id)}>
                Approve
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setDraftEditContent(selectedDraft.content)
                  setDraftEditing(true)
                }}
              >
                Edit
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive"
                onClick={() => handleRejectDraft(selectedDraft.id)}
              >
                Reject
              </Button>
            </>
          )}
        </div>
      </div>
    )
  }

  // Detail view for a selected skill
  if (selected) {
    const isCustom = !selected.builtin && customSkills.some((s) => s.id === selected.id)
    return (
      <div className="flex flex-1 flex-col overflow-hidden">
        <div className="flex items-center gap-3 border-b px-4 py-2">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => navigate(basePath)}
          >
            <ArrowLeft className="size-4" />
          </Button>
          <span className="text-sm font-medium">{selected.name}</span>
          {isCustom ? (
            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
              CUSTOM
            </span>
          ) : (
            <span className="text-xs text-muted-foreground ml-auto">
              Read-only (edit in System Skills)
            </span>
          )}
        </div>

        <FileEditor
          value={draftEditing ? draftEditContent : selected.content}
          onChange={draftEditing ? setDraftEditContent : undefined}
          readOnly={!draftEditing}
        />

        {selected.description && !draftEditing && (
          <div className="border-t px-4 py-2">
            <span className="text-xs text-muted-foreground truncate">
              {selected.description}
            </span>
          </div>
        )}

        {isCustom && (
          <div className="flex items-center gap-2 border-t px-4 py-2">
            {draftEditing ? (
              <>
                <Button size="sm" onClick={async () => {
                  const res = await fetch(`/api/agents/${agentId}/skills/${selected.id}`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ content: draftEditContent }),
                  })
                  if (res.ok) {
                    const updated = await res.json()
                    setSelected(updated)
                    setDraftEditing(false)
                    fetchCustomSkills()
                  }
                }}>
                  Save
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setDraftEditing(false)}>
                  Cancel
                </Button>
              </>
            ) : (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setDraftEditContent(selected.content)
                  setDraftEditing(true)
                }}
              >
                <Pencil className="mr-1.5 size-3" />
                Edit
              </Button>
            )}
          </div>
        )}
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
          onClick={() => navigate(`/a/${encodeURIComponent(agentName ?? agentId)}/settings`)}
        >
          <ArrowLeft className="size-4" />
        </Button>
        <span className="text-sm font-medium">
          Skills{drafts.length > 0 && ` (${drafts.length} ${drafts.length === 1 ? "draft" : "drafts"})`}
        </span>
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
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : (
          <div className="flex flex-col gap-4">
            {drafts.length > 0 && (
              <>
                <div className="flex flex-col gap-1">
                  <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                    Drafts
                  </span>
                  {drafts.map((draft) => (
                    <div
                      key={draft.id}
                      className="flex items-center gap-3 rounded-md border px-4 py-2.5"
                    >
                      <button
                        type="button"
                        className="flex flex-1 flex-col gap-0.5 text-left hover:underline"
                        onClick={() => handleSelectDraft(draft.id)}
                      >
                        <span className="text-sm font-medium">{draft.name}</span>
                        {draft.description && (
                          <span className="text-xs text-muted-foreground">
                            {draft.description.length > 100
                              ? draft.description.slice(0, 100) + "..."
                              : draft.description}
                          </span>
                        )}
                      </button>
                      <Pencil className="size-3.5 text-muted-foreground shrink-0" />
                      <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-600">
                        DRAFT
                      </span>
                    </div>
                  ))}
                </div>
                <Separator />
              </>
            )}

            {/* Search & add section */}
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onFocus={() => {
                  setSearchFocused(true)
                  fetchAvailable()
                }}
                onBlur={() => {
                  setTimeout(() => setSearchFocused(false), 150)
                }}
                placeholder="Search available skills..."
                className="pl-8"
              />
              {searchFocused && availableLoaded && (
                <div className="absolute left-0 right-0 top-full z-50 mt-1 flex flex-col rounded-md border bg-popover shadow-md">
                  {filtered.length === 0 ? (
                    <p className="px-3 py-2 text-xs text-muted-foreground">
                      {available.length === 0
                        ? <>No skills available. Add skills in the global{" "}
                            <Link to="/settings/skills" className="underline">System Skills</Link>{" "}
                            settings.</>
                        : "No matching skills."}
                    </p>
                  ) : (
                    filtered.map((skill, i) => (
                      <div
                        key={skill.id}
                        className={`flex items-center gap-3 px-3 py-2 ${
                          i > 0 ? "border-t" : ""
                        }`}
                      >
                        <div className="flex flex-1 flex-col gap-0.5">
                          <span className="text-sm font-medium">{skill.name}</span>
                          {skill.description && (
                            <span className="text-xs text-muted-foreground">
                              {skill.description}
                            </span>
                          )}
                        </div>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          onClick={() => handleAdd(skill.id)}
                        >
                          <Plus className="size-3.5" />
                        </Button>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>

            <Separator />

            {/* Added skills */}
            {skills.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No skills added to this agent yet.
              </p>
            ) : (
              <div className="flex flex-col gap-3">
                {skills.map((skill) => (
                  <div
                    key={skill.id}
                    className="flex items-center gap-3 rounded-md border px-4 py-2.5"
                  >
                    <button
                      type="button"
                      className={`relative inline-flex h-5 w-9 shrink-0 rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                        skill.enabled ? "bg-primary" : "bg-input"
                      } ${toggling === skill.id || skill.always_enabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
                      disabled={toggling === skill.id || skill.always_enabled}
                      onClick={() => handleToggle(skill.id, !skill.enabled)}
                    >
                      <span
                        className={`pointer-events-none block size-4 rounded-full bg-background shadow-lg ring-0 transition-transform ${
                          skill.enabled ? "translate-x-4" : "translate-x-0"
                        }`}
                      />
                    </button>
                    <button
                      type="button"
                      className="flex flex-1 flex-col gap-0.5 text-left hover:underline"
                      onClick={() => handleSelect(skill.id)}
                    >
                      <span className="text-sm font-medium">{skill.name}</span>
                      {skill.description && (
                        <span className="text-xs text-muted-foreground">
                          {skill.description}
                        </span>
                      )}
                    </button>
                    {skill.always_enabled ? (
                      <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                        BUILTIN
                      </span>
                    ) : (
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => handleRemove(skill.id)}
                      >
                        <X className="size-3.5" />
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            )}

            {customSkills.length > 0 && (
              <>
                <Separator />
                <div className="flex flex-col gap-1">
                  <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                    Custom Skills
                  </span>
                  {customSkills.map((skill) => (
                    <button
                      key={skill.id}
                      type="button"
                      className="flex items-center gap-3 rounded-md border px-4 py-2.5 text-left hover:bg-accent/50"
                      onClick={() => handleSelect(skill.id)}
                    >
                      <div className="flex flex-1 flex-col gap-0.5">
                        <span className="text-sm font-medium">{skill.name}</span>
                        {skill.description && (
                          <span className="text-xs text-muted-foreground truncate max-w-[250px]">
                            {skill.description}
                          </span>
                        )}
                      </div>
                      <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                        CUSTOM
                      </span>
                    </button>
                  ))}
                </div>
              </>
            )}

            <p className="text-xs text-muted-foreground">
              Changes take effect after stopping and restarting the worker.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
