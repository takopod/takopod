import { useCallback, useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { FileEditor } from "@/components/file-editor"
import { ArrowLeft, Square } from "lucide-react"

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
  const [registrySkills, setRegistrySkills] = useState<RegistrySkill[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<SkillDetail | null>(null)
  const [stopping, setStopping] = useState(false)
  const [toggling, setToggling] = useState<string | null>(null)

  const fetchSkills = useCallback(async () => {
    const res = await fetch(`/api/agents/${agentId}/registry-skills`)
    if (res.ok) setRegistrySkills(await res.json())
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

  const handleToggleRegistry = async (skillId: string, enabled: boolean) => {
    setToggling(skillId)
    const res = await fetch(`/api/agents/${agentId}/registry-skills/${skillId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    })
    if (res.ok) {
      setRegistrySkills((prev) =>
        prev.map((s) => (s.id === skillId ? { ...s, enabled } : s)),
      )
    }
    setToggling(null)
  }

  const handleSelect = async (skillId: string) => {
    const res = await fetch(`/api/skills/${skillId}`)
    if (res.ok) {
      const detail: SkillDetail = await res.json()
      setSelected(detail)
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
        ) : registrySkills.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No skills available. Add skills in System Skills settings.
          </p>
        ) : (
          <div className="flex flex-col gap-3">
            {registrySkills.map((skill) => (
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
                  onClick={() =>
                    handleToggleRegistry(skill.id, !skill.enabled)
                  }
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
                {skill.builtin && (
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                    BUILTIN
                  </span>
                )}
              </div>
            ))}

            <p className="text-xs text-muted-foreground">
              Toggle skills on/off. Restart the worker for changes to take effect.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
