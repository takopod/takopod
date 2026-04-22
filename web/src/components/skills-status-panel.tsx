import { useEffect, useState } from "react"
import { Link } from "react-router-dom"

interface SkillSummary {
  id: string
  name: string
  description: string
  builtin: boolean
  always_enabled: boolean
}

interface CustomSkill {
  id: string
  name: string
  description: string
}

export function SkillsStatusPanel({ agentId, agentName }: { agentId: string; agentName?: string }) {
  const [skills, setSkills] = useState<SkillSummary[]>([])
  const [customSkills, setCustomSkills] = useState<CustomSkill[]>([])
  const [draftCount, setDraftCount] = useState(0)

  useEffect(() => {
    let cancelled = false

    async function fetchSkills() {
      let registryIds: Set<string> = new Set()
      try {
        const res = await fetch(`/api/agents/${agentId}/registry-skills`)
        if (cancelled || !res.ok) return
        const data = await res.json()
        const registrySkills: SkillSummary[] = data.skills ?? []
        setSkills(registrySkills)
        registryIds = new Set(registrySkills.map((s) => s.id))
      } catch {
        // ignore fetch errors
      }
      try {
        const customRes = await fetch(`/api/agents/${agentId}/skills`)
        if (!cancelled && customRes.ok) {
          const allSkills: CustomSkill[] = await customRes.json()
          setCustomSkills(allSkills.filter((s) => !registryIds.has(s.id)))
        }
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
      {skills.length === 0 && customSkills.length === 0 ? (
        <span className="text-[11px] text-muted-foreground/60 italic">
          Empty
        </span>
      ) : (
        <>
          {skills.map((skill) => (
            <div key={skill.id} className="flex items-center gap-2 py-0.5">
              <span
                className="inline-block size-1.5 shrink-0 rounded-full bg-green-500"
              />
              <span className="text-xs text-muted-foreground truncate">
                {skill.name}
              </span>
            </div>
          ))}
          {customSkills.map((skill) => (
            <div key={skill.id} className="flex items-center gap-2 py-0.5">
              <span
                className="inline-block size-1.5 shrink-0 rounded-full bg-green-500"
              />
              <span className="text-xs text-muted-foreground truncate">
                {skill.name}
              </span>
            </div>
          ))}
        </>
      )}
      {draftCount > 0 && (
        <Link
          to={`/a/${encodeURIComponent(agentName ?? agentId)}/settings/skills`}
          className="text-[10px] text-amber-600 hover:underline cursor-pointer"
        >
          {draftCount} {draftCount === 1 ? "draft" : "drafts"} pending review
        </Link>
      )}
    </div>
  )
}
