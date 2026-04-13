import { useCallback, useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import { FileEditor } from "@/components/file-editor"
import { ArrowLeft, Plus, Search, Square, X } from "lucide-react"

interface RegistrySkill {
  id: string
  name: string
  description: string
  builtin: boolean
  enabled: boolean
}

interface SkillDetail {
  id: string
  name: string
  description: string
  content: string
  files: string[]
  builtin: boolean
}

export function SkillsPanel({ agentId }: { agentId: string }) {
  const navigate = useNavigate()
  const [skills, setSkills] = useState<RegistrySkill[]>([])
  const [available, setAvailable] = useState<RegistrySkill[]>([])
  const [availableLoaded, setAvailableLoaded] = useState(false)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<SkillDetail | null>(null)
  const [stopping, setStopping] = useState(false)
  const [toggling, setToggling] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const [searchFocused, setSearchFocused] = useState(false)

  const fetchSkills = useCallback(async () => {
    const res = await fetch(`/api/agents/${agentId}/registry-skills`)
    if (res.ok) {
      const data = await res.json()
      setSkills(data.skills || [])
    }
    setLoading(false)
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

  const handleSelect = async (skillId: string) => {
    const res = await fetch(`/api/skills/${skillId}`)
    if (res.ok) {
      const detail: SkillDetail = await res.json()
      setSelected(detail)
    }
  }

  const filtered = available
    .filter((s) => s.name.toLowerCase().includes(search.toLowerCase()))
    .slice(0, 5)

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
          <span className="text-xs text-muted-foreground ml-auto">
            Read-only (edit in System Skills)
          </span>
        </div>

        <FileEditor
          value={selected.content}
          readOnly
        />

        {selected.description && (
          <div className="border-t px-4 py-2">
            <span className="text-xs text-muted-foreground truncate">
              {selected.description}
            </span>
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
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : (
          <div className="flex flex-col gap-4">
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
                            <Link to="/skills" className="underline">System Skills</Link>{" "}
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
                      } ${toggling === skill.id || skill.builtin ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
                      disabled={toggling === skill.id || skill.builtin}
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
                    {skill.builtin ? (
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

            <p className="text-xs text-muted-foreground">
              Changes take effect after stopping and restarting the worker.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
