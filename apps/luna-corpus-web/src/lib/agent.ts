const API_BASE = '/api/v1'

export type AgentMode = 'direct' | 'react' | 'plan' | 'langgraph'

export interface AgentTool {
  name: string
  description: string
  parameters_schema: Record<string, unknown>
}

export interface AgentQueryRequest {
  query: string
  mode: AgentMode
  available_tools: string[]
  stream: true
}

export interface AgentStep {
  id: string
  label: string
}

export interface AgentToolCallSummary {
  tool: string
  success: boolean
}

export interface AgentAssistantAnswer {
  answer: string
  mode: AgentMode
  steps: AgentStep[]
  toolCalls: AgentToolCallSummary[]
  error?: string
}

type KnownAgentStreamEvent =
  | { event: 'start'; data: { query: string } }
  | { event: 'phase'; data: { phase: string } }
  | { event: 'plan'; data: { plan: string } }
  | { event: 'step'; data: { step: number; total: number } }
  | { event: 'thought'; data: { content?: string } }
  | { event: 'tool_call'; data: { tool: string; args?: Record<string, unknown> } }
  | { event: 'tool_result'; data: { tool?: string; result: string } }
  | { event: 'token'; data: string | { content: string } }
  | { event: 'done'; data: { answer?: string; tool_calls?: Array<{ tool: string; success?: boolean }> } }
  | { event: 'error'; data: string }

export type AgentStreamEvent = KnownAgentStreamEvent | { event: string; data: unknown }

export interface AgentStreamState extends AgentAssistantAnswer {
  isComplete: boolean
}

export function createInitialAgentStreamState(mode: AgentMode): AgentStreamState {
  return {
    answer: '',
    mode,
    steps: [],
    toolCalls: [],
    isComplete: false,
  }
}

export async function fetchAgentTools(): Promise<AgentTool[]> {
  const response = await fetch(`${API_BASE}/agent/tools`)
  if (!response.ok) throw new Error('Failed to fetch agent tools')
  const data = await response.json() as { tools: AgentTool[] }
  return data.tools
}

export async function* streamAgentQuery(
  request: AgentQueryRequest,
): AsyncGenerator<AgentStreamEvent, void, unknown> {
  const response = await fetch(`${API_BASE}/agent/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })

  if (!response.ok) throw new Error('Agent stream query failed')
  if (!response.body) throw new Error('Agent stream response has no body')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6)
          if (data.trim()) yield JSON.parse(data) as AgentStreamEvent
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

export function reduceAgentStreamState(
  state: AgentStreamState,
  event: AgentStreamEvent,
): AgentStreamState {
  const knownEvent = event as KnownAgentStreamEvent

  switch (knownEvent.event) {
    case 'start':
      return addStep(state, '开始处理')
    case 'phase':
      return addStep(state, phaseLabel(knownEvent.data.phase))
    case 'plan':
      return addStep(state, '已生成执行计划')
    case 'step':
      return addStep(state, `执行第 ${knownEvent.data.step}/${knownEvent.data.total} 步`)
    case 'thought':
      return addStep(state, '分析中')
    case 'tool_call':
      return {
        ...addStep(state, `调用工具：${knownEvent.data.tool}`),
        toolCalls: upsertToolCall(state.toolCalls, knownEvent.data.tool, true),
      }
    case 'tool_result':
      return addStep(state, '工具执行完成')
    case 'token':
      return { ...state, answer: state.answer + tokenContent(knownEvent.data) }
    case 'done':
      return {
        ...addStep(state, '生成最终回答'),
        answer: knownEvent.data.answer ?? state.answer,
        toolCalls: knownEvent.data.tool_calls?.map((toolCall) => ({
          tool: toolCall.tool,
          success: toolCall.success ?? true,
        })) ?? state.toolCalls,
        isComplete: true,
      }
    case 'error':
      return { ...state, error: knownEvent.data, isComplete: true }
    default:
      return state
  }
}

function addStep(state: AgentStreamState, label: string): AgentStreamState {
  if (state.steps.at(-1)?.label === label) return state
  return {
    ...state,
    steps: [...state.steps, { id: `${state.steps.length + 1}`, label }],
  }
}

function phaseLabel(phase: string): string {
  const labels: Record<string, string> = {
    planning: '规划中',
    executing: '执行中',
    finalizing: '总结中',
  }
  return labels[phase] ?? phase
}

function tokenContent(data: string | { content: string }): string {
  return typeof data === 'string' ? data : data.content
}

function upsertToolCall(
  toolCalls: AgentToolCallSummary[],
  tool: string,
  success: boolean,
): AgentToolCallSummary[] {
  if (toolCalls.some((toolCall) => toolCall.tool === tool)) return toolCalls
  return [...toolCalls, { tool, success }]
}
