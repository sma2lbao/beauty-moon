import { render, screen } from '@testing-library/react'
import { MessageBubble } from './MessageBubble'
import type { AgentAssistantAnswer } from '@/lib/agent'

describe('MessageBubble', () => {
  it('renders Agent answer steps and final text', () => {
    const agentAnswer: AgentAssistantAnswer = {
      answer: '这是最终回答',
      mode: 'react',
      steps: [
        { id: '1', label: '开始处理' },
        { id: '2', label: '调用工具：rag_search' },
      ],
      toolCalls: [{ tool: 'rag_search', success: true }],
    }

    render(<MessageBubble type="assistant" agentAnswer={agentAnswer} />)

    expect(screen.getByText('模式: react')).toBeInTheDocument()
    expect(screen.getByText('开始处理')).toBeInTheDocument()
    expect(screen.getByText('调用工具：rag_search')).toBeInTheDocument()
    expect(screen.getByText('这是最终回答')).toBeInTheDocument()
    expect(screen.getByText('工具: rag_search')).toBeInTheDocument()
  })

  it('renders Agent stream error without hiding partial answer', () => {
    const agentAnswer: AgentAssistantAnswer = {
      answer: '部分回答',
      mode: 'plan',
      steps: [{ id: '1', label: '开始处理' }],
      toolCalls: [],
      error: '后端失败',
    }

    render(<MessageBubble type="assistant" agentAnswer={agentAnswer} />)

    expect(screen.getByText('部分回答')).toBeInTheDocument()
    expect(screen.getByText('错误: 后端失败')).toBeInTheDocument()
  })
})
