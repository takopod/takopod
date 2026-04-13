import {
  Anchor,
  Aperture,
  Atom,
  Bot,
  BrainCircuit,
  Compass,
  Cpu,
  Fingerprint,
  Flame,
  Gem,
  Hexagon,
  Microscope,
  Orbit,
  Podcast,
  Radar,
  Satellite,
  Shield,
  Swords,
  TreePine,
  Zap,
  type LucideProps,
} from "lucide-react"

const ICON_MAP: Record<string, React.FC<LucideProps>> = {
  Anchor,
  Aperture,
  Atom,
  Bot,
  BrainCircuit,
  Compass,
  Cpu,
  Fingerprint,
  Flame,
  Gem,
  Hexagon,
  Microscope,
  Orbit,
  Podcast,
  Radar,
  Satellite,
  Shield,
  Swords,
  TreePine,
  Zap,
}

interface AgentIconProps extends LucideProps {
  name: string
}

export function AgentIcon({ name, ...props }: AgentIconProps) {
  const Icon = ICON_MAP[name] ?? Bot
  return <Icon {...props} />
}
