import { useCallback, useMemo, useState } from "react"
import type { Agent } from "@/lib/types"

const STORAGE_KEY = "takopod:agentOrder"

function loadOrder(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveOrder(ids: string[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(ids))
}

export function useAgentOrder(agents: Agent[]) {
  const [version, setVersion] = useState(0)

  const orderedAgents = useMemo(() => {
    const savedOrder = loadOrder()
    const agentMap = new Map(agents.map((a) => [a.id, a]))

    const ordered: Agent[] = []
    for (const id of savedOrder) {
      const agent = agentMap.get(id)
      if (agent) {
        ordered.push(agent)
        agentMap.delete(id)
      }
    }

    for (const agent of agents) {
      if (agentMap.has(agent.id)) {
        ordered.push(agent)
      }
    }

    return ordered
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agents, version])

  const reorder = useCallback(
    (activeId: string, overId: string) => {
      const currentIds = orderedAgents.map((a) => a.id)
      const oldIndex = currentIds.indexOf(activeId)
      const newIndex = currentIds.indexOf(overId)
      if (oldIndex === -1 || newIndex === -1 || oldIndex === newIndex) return

      const newIds = [...currentIds]
      const [removed] = newIds.splice(oldIndex, 1)
      newIds.splice(newIndex, 0, removed)
      saveOrder(newIds)
      setVersion((v) => v + 1)
    },
    [orderedAgents],
  )

  return { orderedAgents, reorder }
}
