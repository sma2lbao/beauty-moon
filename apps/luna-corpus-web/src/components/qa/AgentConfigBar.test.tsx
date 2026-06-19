import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AgentConfigBar } from './AgentConfigBar'
import type { AgentTool } from '@/lib/agent'

const tools: AgentTool[] = [
  { name: 'rag_search', description: 'Search documents', parameters_schema: {} },
  { name: 'calculator', description: 'Run calculations', parameters_schema: {} },
]

describe('AgentConfigBar', () => {
  it('changes Agent mode', async () => {
    const user = userEvent.setup()
    const onModeChange = vi.fn()

    render(
      <AgentConfigBar
        mode="react"
        onModeChange={onModeChange}
        tools={tools}
        selectedTools={['rag_search']}
        onSelectedToolsChange={vi.fn()}
        isLoadingTools={false}
      />,
    )

    await user.selectOptions(screen.getByLabelText('Agent 模式'), 'plan')

    expect(onModeChange).toHaveBeenCalledWith('plan')
  })

  it('toggles selected tools', async () => {
    const user = userEvent.setup()
    const onSelectedToolsChange = vi.fn()

    render(
      <AgentConfigBar
        mode="react"
        onModeChange={vi.fn()}
        tools={tools}
        selectedTools={['rag_search']}
        onSelectedToolsChange={onSelectedToolsChange}
        isLoadingTools={false}
      />,
    )

    await user.click(screen.getByLabelText('calculator'))

    expect(onSelectedToolsChange).toHaveBeenCalledWith(['rag_search', 'calculator'])
  })

  it('shows loading and error states', () => {
    const { rerender } = render(
      <AgentConfigBar
        mode="react"
        onModeChange={vi.fn()}
        tools={[]}
        selectedTools={[]}
        onSelectedToolsChange={vi.fn()}
        isLoadingTools={true}
      />,
    )

    expect(screen.getByText('加载工具中...')).toBeInTheDocument()

    rerender(
      <AgentConfigBar
        mode="react"
        onModeChange={vi.fn()}
        tools={[]}
        selectedTools={[]}
        onSelectedToolsChange={vi.fn()}
        isLoadingTools={false}
        toolsError="工具列表加载失败"
      />,
    )

    expect(screen.getByText('工具列表加载失败')).toBeInTheDocument()
  })
})
