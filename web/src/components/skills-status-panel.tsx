import { useEffect, useState } from "react"

interface SkillSummary {
  id: string
  name: string
  description: string
  builtin: boolean
  enabled: boolean
}

export function SkillsStatusPanel({ agentId }: { agentId: string }) {
  const [skills, setSkills] = useState<SkillSummary[]>([])
  const [draftCount, setDraftCount] = useState(0)

  useEffect(() => {
    let cancelled = false

    async function fetchSkills() {
      try {
        const res = await fetch(`/api/agents/${agentId}/registry-skills`)
        if (cancelled || !res.ok) return
        const data = await res.json()
        setSkills(data.skills ?? [])
      } catch {
        // ignore fetch errors
      }
      try {
        const draftsRes = await fetch(`/api/agents/${agentId}/skill-drafts`)
        if (!cancelled && draftsRes.ok) {
          const draftsData = await draftsRes.json()
          setDraftCount(draftsData.length)
        }
      } catch {
        // ignore fetch errors
      }
    }

    fetchSkills()
    const interval = setInterval(fetchSkills, 10000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [agentId])

  return (
    <div className="flex flex-col gap-1 px-3 py-2">
      <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mb-0.5">
        Skills
      </span>
      {skills.length === 0 ? (
        <span className="text-[11px] text-muted-foreground/60 italic">
          Empty
        </span>
      ) : (
        skills.map((skill) => (
          <div key={skill.id} className="flex items-center gap-2 py-0.5">
            <span
              className={`inline-block size-1.5 shrink-0 rounded-full ${
                skill.enabled
                  ? "bg-green-500"
                  : "bg-muted-foreground/40"
              }`}
            />
            <span className="text-xs text-muted-foreground truncate">
              {skill.name}
            </span>
          </div>
        ))
      )}
      {draftCount > 0 && (
        <span className="text-[10px] text-amber-600">
          {draftCount} {draftCount === 1 ? "draft" : "drafts"} pending review
        </span>
      )}
    </div>
  )
}
