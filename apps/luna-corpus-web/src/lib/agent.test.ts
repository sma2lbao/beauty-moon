import {
  createInitialAgentStreamState,
  reduceAgentStreamState,
  type AgentStreamEvent,
} from './agent'

describe('reduceAgentStreamState', () => {
  it('maps start, phase, step, and tool events to concise steps', () => {
    let state = createInitialAgentStreamState('react')

    const events: AgentStreamEvent[] = [
      { event: 'start', data: { query: '解释项目' } },
      { event: 'phase', data: { phase: 'planning' } },
      { event: 'step', data: { step: 1, total: 3 } },
      { event: 'tool_call', data: { tool: 'rag_search', args: { query: '隐藏参数' } } },
      { event: 'tool_result', data: { tool: 'rag_search', result: '隐藏结果' } },
    ]

    for (const event of events) {
      state = reduceAgentStreamState(state, event)
    }

    expect(state.steps.map((step) => step.label)).toEqual([
      '开始处理',
      '规划中',
      '执行第 1/3 步',
      '调用工具：rag_search',
      '工具执行完成',
    ])
    expect(state.toolCalls).toEqual([{ tool: 'rag_search', success: true }])
  })

  it('accepts token data as a string or content object', () => {
    let state = createInitialAgentStreamState('direct')

    state = reduceAgentStreamState(state, { event: 'token', data: '你好' })
    state = reduceAgentStreamState(state, { event: 'token', data: { content: '，世界' } })

    expect(state.answer).toBe('你好，世界')
  })

  it('uses done answer and summarized tool calls without exposing args or results', () => {
    const state = reduceAgentStreamState(createInitialAgentStreamState('plan'), {
      event: 'done',
      data: {
        answer: '最终回答',
        tool_calls: [
          { tool: 'calculator', args: { expression: '1+1' }, result: '2', success: true },
          { tool: 'current_time', args: {}, result: 'now', success: false },
        ],
      },
    })

    expect(state.answer).toBe('最终回答')
    expect(state.isComplete).toBe(true)
    expect(state.toolCalls).toEqual([
      { tool: 'calculator', success: true },
      { tool: 'current_time', success: false },
    ])
  })

  it('records stream errors without removing existing answer text', () => {
    let state = createInitialAgentStreamState('langgraph')
    state = reduceAgentStreamState(state, { event: 'token', data: 'partial' })
    state = reduceAgentStreamState(state, { event: 'error', data: 'backend failed' })

    expect(state.answer).toBe('partial')
    expect(state.error).toBe('backend failed')
    expect(state.isComplete).toBe(true)
  })
})
