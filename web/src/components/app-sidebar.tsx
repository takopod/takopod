import { Link, useLocation } from "react-router-dom"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { Button } from "@/components/ui/button"
import { useTheme } from "@/components/theme-provider"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  SidebarRail,
} from "@/components/ui/sidebar"
import { AgentIcon } from "@/components/agent-icon"
import type { Agent } from "@/lib/types"
import {
  Bot,
  Calendar,
  Check,
  ChevronRight,
  Hash,
  MessageSquare,
  Moon,
  Plus,
  Server,
  Settings,
  Sparkles,
  Sun,
} from "lucide-react"

interface AppSidebarProps extends React.ComponentProps<typeof Sidebar> {
  agents: Agent[]
  selectedAgentId: string | null
  onAgentChange: (value: string) => void
}

export function AppSidebar({
  agents,
  selectedAgentId,
  onAgentChange,
  ...props
}: AppSidebarProps) {
  const { theme, setTheme } = useTheme()
  const location = useLocation()
  const currentPath = location.pathname

  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <div className="cursor-default">
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <Bot className="size-4" />
                </div>
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-semibold">rhclaw</span>
                </div>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  className="ml-auto text-sidebar-foreground/60 hover:text-sidebar-foreground"
                  onClick={(e) => {
                    e.stopPropagation()
                    setTheme(theme === "dark" ? "light" : "dark")
                  }}
                >
                  {theme === "dark" ? (
                    <Sun className="size-3.5" />
                  ) : (
                    <Moon className="size-3.5" />
                  )}
                </Button>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>

        <SidebarGroupLabel className="uppercase tracking-wider">Agents</SidebarGroupLabel>
        <SidebarMenu>
          {agents.map((agent) => (
            <SidebarMenuItem key={agent.id}>
              <SidebarMenuButton
                onClick={() => onAgentChange(agent.id)}
                tooltip={agent.name}
              >
                {agent.icon ? (
                  <AgentIcon name={agent.icon} className="size-4" />
                ) : (
                  <Bot className="size-4" />
                )}
                <span>{agent.name}</span>
                {selectedAgentId === agent.id && (
                  <Check className="ml-auto size-3.5" />
                )}
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
          <SidebarMenuItem>
            <SidebarMenuButton
              onClick={() => onAgentChange("__create__")}
              tooltip="Add Agent"
            >
              <Plus className="size-4" />
              <span>Add Agent</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel className="uppercase tracking-wider">Navigation</SidebarGroupLabel>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                asChild
                isActive={currentPath.startsWith("/a/")}
                tooltip="Chat"
              >
                <Link to={(() => {
                  const sel = agents.find((a) => a.id === selectedAgentId)
                  return sel ? `/a/${encodeURIComponent(sel.name)}` : "/"
                })()}>
                  <MessageSquare />
                  <span>Chat</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>

            <SidebarMenuItem>
              <SidebarMenuButton
                asChild
                isActive={currentPath === "/schedules"}
                tooltip="Schedules"
              >
                <Link to="/schedules">
                  <Calendar />
                  <span>Schedules</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>

            <SidebarMenuItem>
              <SidebarMenuButton
                asChild
                isActive={currentPath === "/skills"}
                tooltip="Skills"
              >
                <Link to="/skills">
                  <Sparkles />
                  <span>Skills</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>

            <SidebarMenuItem>
              <SidebarMenuButton
                asChild
                isActive={currentPath === "/mcp"}
                tooltip="MCP Servers"
              >
                <Link to="/mcp">
                  <Server />
                  <span>MCP Servers</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>

            <Collapsible
              asChild
              defaultOpen={currentPath.startsWith("/settings")}
              className="group/collapsible"
            >
              <SidebarMenuItem>
                <CollapsibleTrigger asChild>
                  <SidebarMenuButton
                    isActive={currentPath.startsWith("/settings")}
                    tooltip="Settings"
                  >
                    <Settings />
                    <span>Settings</span>
                    <ChevronRight className="ml-auto transition-transform duration-200 group-data-[state=open]/collapsible:rotate-90" />
                  </SidebarMenuButton>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <SidebarMenuSub>
                    <SidebarMenuSubItem>
                      <SidebarMenuSubButton
                        asChild
                        isActive={currentPath === "/settings"}
                      >
                        <Link to="/settings">
                          <span>General</span>
                        </Link>
                      </SidebarMenuSubButton>
                    </SidebarMenuSubItem>
                    <SidebarMenuSubItem>
                      <SidebarMenuSubButton
                        asChild
                        isActive={currentPath === "/settings/slack"}
                      >
                        <Link to="/settings/slack">
                          <Hash className="size-3.5" />
                          <span>Slack</span>
                        </Link>
                      </SidebarMenuSubButton>
                    </SidebarMenuSubItem>
                  </SidebarMenuSub>
                </CollapsibleContent>
              </SidebarMenuItem>
            </Collapsible>
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter />
      <SidebarRail />
    </Sidebar>
  )
}
