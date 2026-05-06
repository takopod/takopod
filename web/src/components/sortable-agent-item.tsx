import { useSortable } from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import { Bot, Check, GripVertical } from "lucide-react"
import { SidebarMenuButton, SidebarMenuItem } from "@/components/ui/sidebar"
import { AgentIcon } from "@/components/agent-icon"
import type { Agent } from "@/lib/types"

interface SortableAgentItemProps {
  agent: Agent
  isSelected: boolean
  onSelect: () => void
}

export function SortableAgentItem({
  agent,
  isSelected,
  onSelect,
}: SortableAgentItemProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: agent.id })

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    position: "relative",
    zIndex: isDragging ? 10 : undefined,
  }

  return (
    <SidebarMenuItem ref={setNodeRef} style={style} {...attributes}>
      <SidebarMenuButton onClick={onSelect} tooltip={agent.name}>
        <div
          ref={setActivatorNodeRef}
          {...listeners}
          className="shrink-0 cursor-grab touch-none opacity-0 group-hover/menu-item:opacity-60 hover:!opacity-100 transition-opacity -ml-0.5 mr-0.5"
          aria-label={`Drag to reorder ${agent.name}`}
          role="button"
          tabIndex={-1}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.stopPropagation()}
        >
          <GripVertical className="size-3" />
        </div>
        {agent.icon ? (
          <AgentIcon name={agent.icon} className="size-4" />
        ) : (
          <Bot className="size-4" />
        )}
        <span>{agent.name}</span>
        {isSelected && <Check className="ml-auto size-3.5" />}
      </SidebarMenuButton>
    </SidebarMenuItem>
  )
}
