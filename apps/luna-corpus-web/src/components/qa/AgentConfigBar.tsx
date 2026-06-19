import type { AgentMode, AgentTool } from '@/lib/agent'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'

interface AgentConfigBarProps {
  mode: AgentMode
  onModeChange: (mode: AgentMode) => void
  tools: AgentTool[]
  selectedTools: string[]
  onSelectedToolsChange: (tools: string[]) => void
  isLoadingTools: boolean
  toolsError?: string
  disabled?: boolean
}

const agentModes: AgentMode[] = ['direct', 'react', 'plan', 'langgraph']

export function AgentConfigBar({
  mode,
  onModeChange,
  tools,
  selectedTools,
  onSelectedToolsChange,
  isLoadingTools,
  toolsError,
  disabled = false,
}: AgentConfigBarProps) {
  const toggleTool = (toolName: string) => {
    if (selectedTools.includes(toolName)) {
      onSelectedToolsChange(selectedTools.filter((name) => name !== toolName))
      return
    }
    onSelectedToolsChange([...selectedTools, toolName])
  }

  return (
    <Card className="mb-4 p-4 space-y-3">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <label className="flex flex-col gap-1 text-sm font-medium">
          Agent 模式
          <select
            aria-label="Agent 模式"
            value={mode}
            disabled={disabled}
            onChange={(event) => onModeChange(event.target.value as AgentMode)}
            className="h-10 rounded-md border border-input bg-background px-3 text-sm"
          >
            {agentModes.map((agentMode) => (
              <option key={agentMode} value={agentMode}>
                {agentMode}
              </option>
            ))}
          </select>
        </label>

        <div className="flex-1 space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">启用工具</span>
            <Badge variant="secondary">{selectedTools.length}/{tools.length}</Badge>
          </div>

          {isLoadingTools && <p className="text-sm text-muted-foreground">加载工具中...</p>}
          {toolsError && <p className="text-sm text-destructive">{toolsError}</p>}

          {!isLoadingTools && !toolsError && (
            <div className="flex flex-wrap gap-3">
              {tools.map((tool) => (
                <label key={tool.name} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={selectedTools.includes(tool.name)}
                    disabled={disabled}
                    onChange={() => toggleTool(tool.name)}
                  />
                  <span>{tool.name}</span>
                </label>
              ))}
            </div>
          )}
        </div>
      </div>
    </Card>
  )
}
