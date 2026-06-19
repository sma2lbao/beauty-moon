# Agent Q&A Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the existing Q&A page with Agent-powered Q&A that supports mode selection, backend-provided tool selection, and concise execution steps.

**Architecture:** Keep the current React/Vite Q&A page and route structure. Add a focused Agent API module for backend contracts and stream normalization, a small Agent configuration component for mode/tool selection, and extend the existing message bubble to render Agent answers and progress.

**Tech Stack:** Nx 22, pnpm workspaces, React 18, TypeScript, Vite, Tailwind, existing local UI components, Vitest, React Testing Library.

## Global Constraints

- Q&A submissions must use `/api/v1/agent/stream` and stop using `/api/v1/qa/stream`.
- The UI must support `direct`, `react`, `plan`, and `langgraph` Agent modes.
- The default mode is `react`.
- Tool options must come from `GET /api/v1/agent/tools`.
- Do not use frontend fallback tool definitions when tool discovery fails.
- Do not expose raw tool arguments, raw tool outputs, or full tool call logs in the normal Q&A flow.
- Keep the existing message flow: submit, clear input, disable input while streaming, stream assistant response, persist completed message.
- Run workspace tasks through `pnpm nx`.

---

## File Structure

- Modify `apps/luna-corpus-web/package.json`
  - Add frontend test scripts and test dependencies.
- Modify `apps/luna-corpus-web/vite.config.ts`
  - Add Vitest configuration using `jsdom`.
- Create `apps/luna-corpus-web/src/test/setup.ts`
  - Load `@testing-library/jest-dom/vitest` matchers.
- Create `apps/luna-corpus-web/src/lib/agent.ts`
  - Own Agent API types, tool fetching, Agent stream fetching, and event normalization.
- Create `apps/luna-corpus-web/src/lib/agent.test.ts`
  - Test pure Agent event normalization and request helpers.
- Create `apps/luna-corpus-web/src/components/qa/AgentConfigBar.tsx`
  - Render mode selector, tool multi-select, loading state, and error state.
- Create `apps/luna-corpus-web/src/components/qa/AgentConfigBar.test.tsx`
  - Test mode changes, tool toggles, disabled state, and error state.
- Modify `apps/luna-corpus-web/src/components/qa/MessageBubble.tsx`
  - Add optional Agent answer rendering while preserving user message rendering.
- Create `apps/luna-corpus-web/src/components/qa/MessageBubble.test.tsx`
  - Test concise step rendering, answer rendering, and error rendering.
- Modify `apps/luna-corpus-web/src/pages/QAPage.tsx`
  - Replace legacy RAG stream flow with Agent stream flow and configuration state.
- Create `apps/luna-corpus-web/src/pages/QAPage.test.tsx`
  - Test initial tool loading, Agent request parameters, persisted messages, and stream errors.

---

### Task 1: Add Frontend Test Harness

**Files:**
- Modify: `apps/luna-corpus-web/package.json`
- Modify: `apps/luna-corpus-web/vite.config.ts`
- Create: `apps/luna-corpus-web/src/test/setup.ts`

**Interfaces:**
- Consumes: Existing Vite React app configuration.
- Produces: `pnpm nx test luna-corpus-web` target inferred from `package.json` script, Vitest globals, jsdom test environment.

- [ ] **Step 1: Add the failing test script**

Modify `apps/luna-corpus-web/package.json` scripts to include `test`:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "lint": "eslint .",
    "preview": "vite preview",
    "test": "vitest run"
  }
}
```

- [ ] **Step 2: Install test dependencies**

Run:

```bash
pnpm add -D -F luna-corpus-web vitest jsdom @testing-library/react @testing-library/user-event @testing-library/jest-dom
```

Expected: `apps/luna-corpus-web/package.json` and the workspace lockfile update with the new dev dependencies.

- [ ] **Step 3: Configure Vitest**

Modify `apps/luna-corpus-web/vite.config.ts`:

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    globals: true,
  },
})
```

- [ ] **Step 4: Add Vite test type support**

Modify `apps/luna-corpus-web/tsconfig.json` so `compilerOptions` includes Vitest and jest-dom types:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"],
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 5: Create test setup file**

Create `apps/luna-corpus-web/src/test/setup.ts`:

```ts
import '@testing-library/jest-dom/vitest'
```

- [ ] **Step 6: Run test target to verify harness works**

Run:

```bash
pnpm nx test luna-corpus-web
```

Expected: PASS with no test files found or a Vitest pass summary if a smoke test exists. If Vitest exits non-zero because no test files exist, add `apps/luna-corpus-web/src/test/smoke.test.ts`:

```ts
describe('test harness', () => {
  it('runs vitest', () => {
    expect(true).toBe(true)
  })
})
```

Then rerun:

```bash
pnpm nx test luna-corpus-web
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/luna-corpus-web/package.json apps/luna-corpus-web/vite.config.ts apps/luna-corpus-web/tsconfig.json apps/luna-corpus-web/src/test/setup.ts pnpm-lock.yaml
git add apps/luna-corpus-web/src/test/smoke.test.ts 2>/dev/null || true
git commit -m "test(web): add frontend test harness"
```

---

### Task 2: Add Agent API Types and Event Normalization

**Files:**
- Create: `apps/luna-corpus-web/src/lib/agent.ts`
- Create: `apps/luna-corpus-web/src/lib/agent.test.ts`

**Interfaces:**
- Consumes: Browser `fetch`, backend endpoints `/api/v1/agent/tools` and `/api/v1/agent/stream`.
- Produces:
  - `type AgentMode = 'direct' | 'react' | 'plan' | 'langgraph'`
  - `interface AgentTool { name: string; description: string; parameters_schema: Record<string, unknown> }`
  - `interface AgentStep { id: string; label: string }`
  - `interface AgentToolCallSummary { tool: string; success: boolean }`
  - `interface AgentAssistantAnswer { answer: string; mode: AgentMode; steps: AgentStep[]; toolCalls: AgentToolCallSummary[]; error?: string }`
  - `fetchAgentTools(): Promise<AgentTool[]>`
  - `streamAgentQuery(request: AgentQueryRequest): AsyncGenerator<AgentStreamEvent, void, unknown>`
  - `reduceAgentStreamState(state: AgentStreamState, event: AgentStreamEvent): AgentStreamState`
  - `createInitialAgentStreamState(mode: AgentMode): AgentStreamState`

- [ ] **Step 1: Write failing normalization tests**

Create `apps/luna-corpus-web/src/lib/agent.test.ts`:

```ts
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
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pnpm nx test luna-corpus-web -- --run src/lib/agent.test.ts
```

Expected: FAIL because `src/lib/agent.ts` does not exist.

- [ ] **Step 3: Implement Agent module**

Create `apps/luna-corpus-web/src/lib/agent.ts`:

```ts
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

export type AgentStreamEvent =
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
  | { event: string; data: unknown }

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
  switch (event.event) {
    case 'start':
      return addStep(state, '开始处理')
    case 'phase':
      return addStep(state, phaseLabel(event.data.phase))
    case 'plan':
      return addStep(state, '已生成执行计划')
    case 'step':
      return addStep(state, `执行第 ${event.data.step}/${event.data.total} 步`)
    case 'thought':
      return addStep(state, '分析中')
    case 'tool_call':
      return {
        ...addStep(state, `调用工具：${event.data.tool}`),
        toolCalls: upsertToolCall(state.toolCalls, event.data.tool, true),
      }
    case 'tool_result':
      return addStep(state, '工具执行完成')
    case 'token':
      return { ...state, answer: state.answer + tokenContent(event.data) }
    case 'done':
      return {
        ...addStep(state, '生成最终回答'),
        answer: event.data.answer ?? state.answer,
        toolCalls: event.data.tool_calls?.map((toolCall) => ({
          tool: toolCall.tool,
          success: toolCall.success ?? true,
        })) ?? state.toolCalls,
        isComplete: true,
      }
    case 'error':
      return { ...state, error: event.data, isComplete: true }
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
```

- [ ] **Step 4: Run Agent module tests**

Run:

```bash
pnpm nx test luna-corpus-web -- --run src/lib/agent.test.ts
```

Expected: PASS.

- [ ] **Step 5: Run lint and build**

Run:

```bash
pnpm nx lint luna-corpus-web
pnpm nx build luna-corpus-web
```

Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/luna-corpus-web/src/lib/agent.ts apps/luna-corpus-web/src/lib/agent.test.ts
git commit -m "feat(web): add agent stream state handling"
```

---

### Task 3: Add Agent Configuration Bar

**Files:**
- Create: `apps/luna-corpus-web/src/components/qa/AgentConfigBar.tsx`
- Create: `apps/luna-corpus-web/src/components/qa/AgentConfigBar.test.tsx`

**Interfaces:**
- Consumes: `AgentMode` and `AgentTool` from `@/lib/agent`.
- Produces: `AgentConfigBar` component with props:
  - `mode: AgentMode`
  - `onModeChange: (mode: AgentMode) => void`
  - `tools: AgentTool[]`
  - `selectedTools: string[]`
  - `onSelectedToolsChange: (tools: string[]) => void`
  - `isLoadingTools: boolean`
  - `toolsError?: string`
  - `disabled?: boolean`

- [ ] **Step 1: Write failing component tests**

Create `apps/luna-corpus-web/src/components/qa/AgentConfigBar.test.tsx`:

```tsx
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
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pnpm nx test luna-corpus-web -- --run src/components/qa/AgentConfigBar.test.tsx
```

Expected: FAIL because `AgentConfigBar.tsx` does not exist.

- [ ] **Step 3: Implement AgentConfigBar**

Create `apps/luna-corpus-web/src/components/qa/AgentConfigBar.tsx`:

```tsx
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
```

- [ ] **Step 4: Run component tests**

Run:

```bash
pnpm nx test luna-corpus-web -- --run src/components/qa/AgentConfigBar.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Run lint**

Run:

```bash
pnpm nx lint luna-corpus-web
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/luna-corpus-web/src/components/qa/AgentConfigBar.tsx apps/luna-corpus-web/src/components/qa/AgentConfigBar.test.tsx
git commit -m "feat(web): add agent query controls"
```

---

### Task 4: Extend Message Bubble for Agent Answers

**Files:**
- Modify: `apps/luna-corpus-web/src/components/qa/MessageBubble.tsx`
- Create: `apps/luna-corpus-web/src/components/qa/MessageBubble.test.tsx`

**Interfaces:**
- Consumes: `AgentAssistantAnswer` from `@/lib/agent`.
- Produces: `MessageBubble` accepts optional `agentAnswer?: AgentAssistantAnswer` and renders concise steps, answer text, mode, tool summaries, and error.

- [ ] **Step 1: Write failing MessageBubble tests**

Create `apps/luna-corpus-web/src/components/qa/MessageBubble.test.tsx`:

```tsx
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
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pnpm nx test luna-corpus-web -- --run src/components/qa/MessageBubble.test.tsx
```

Expected: FAIL because `agentAnswer` is not supported.

- [ ] **Step 3: Update MessageBubble**

Modify `apps/luna-corpus-web/src/components/qa/MessageBubble.tsx`:

```tsx
import { type AnswerResponse } from '@/lib/api'
import type { AgentAssistantAnswer } from '@/lib/agent'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { SourceCard } from './SourceCard'
import { User, Bot, Loader2 } from 'lucide-react'

interface MessageBubbleProps {
  type: 'user' | 'assistant'
  content?: string
  answer?: AnswerResponse
  agentAnswer?: AgentAssistantAnswer
  isStreaming?: boolean
}

export function MessageBubble({
  type,
  content,
  answer,
  agentAnswer,
  isStreaming = false,
}: MessageBubbleProps) {
  const isUser = type === 'user'

  return (
    <Card className={isUser ? 'bg-primary text-primary-foreground' : ''}>
      <CardHeader className="flex flex-row items-center gap-2 pb-2">
        {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
        <span className="font-medium">{isUser ? '你' : 'Luna'}</span>
        {agentAnswer && <Badge variant="secondary">模式: {agentAnswer.mode}</Badge>}
        {isStreaming && !isUser && <Loader2 className="w-3 h-3 animate-spin" />}
      </CardHeader>
      <CardContent className={isUser ? 'pt-0' : ''}>
        {isUser ? (
          <p>{content}</p>
        ) : agentAnswer ? (
          <AgentAnswerContent agentAnswer={agentAnswer} />
        ) : answer ? (
          <>
            <p className="whitespace-pre-wrap">{answer.answer}</p>
            {answer.sources.length > 0 && (
              <div className="mt-4">
                <h4 className="text-sm font-medium mb-2">参考来源:</h4>
                {answer.sources.map((source, idx) => (
                  <SourceCard key={idx} source={source} />
                ))}
              </div>
            )}
            <p className="text-xs text-muted-foreground mt-4">
              处理时间: {answer.processing_time_ms}ms
            </p>
          </>
        ) : isStreaming && content ? (
          <p className="whitespace-pre-wrap">{content}</p>
        ) : null}
      </CardContent>
    </Card>
  )
}

function AgentAnswerContent({ agentAnswer }: { agentAnswer: AgentAssistantAnswer }) {
  return (
    <div className="space-y-4">
      {agentAnswer.steps.length > 0 && (
        <div>
          <h4 className="text-sm font-medium mb-2">执行步骤</h4>
          <ol className="space-y-1 text-sm text-muted-foreground">
            {agentAnswer.steps.map((step) => (
              <li key={step.id}>{step.label}</li>
            ))}
          </ol>
        </div>
      )}

      {agentAnswer.answer && (
        <p className="whitespace-pre-wrap">{agentAnswer.answer}</p>
      )}

      {agentAnswer.toolCalls.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {agentAnswer.toolCalls.map((toolCall) => (
            <Badge key={toolCall.tool} variant={toolCall.success ? 'secondary' : 'destructive'}>
              工具: {toolCall.tool}
            </Badge>
          ))}
        </div>
      )}

      {agentAnswer.error && (
        <p className="text-sm text-destructive">错误: {agentAnswer.error}</p>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run MessageBubble tests**

Run:

```bash
pnpm nx test luna-corpus-web -- --run src/components/qa/MessageBubble.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Run lint**

Run:

```bash
pnpm nx lint luna-corpus-web
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/luna-corpus-web/src/components/qa/MessageBubble.tsx apps/luna-corpus-web/src/components/qa/MessageBubble.test.tsx
git commit -m "feat(web): render agent answer progress"
```

---

### Task 5: Wire Q&A Page to Agent API

**Files:**
- Modify: `apps/luna-corpus-web/src/pages/QAPage.tsx`
- Create: `apps/luna-corpus-web/src/pages/QAPage.test.tsx`

**Interfaces:**
- Consumes:
  - `AgentConfigBar` from `@/components/qa/AgentConfigBar`
  - `fetchAgentTools`, `streamAgentQuery`, `createInitialAgentStreamState`, `reduceAgentStreamState`, `AgentMode`, `AgentStreamState`, `AgentAssistantAnswer` from `@/lib/agent`
- Produces:
  - Q&A page that fetches tools on mount.
  - Q&A submissions using `/api/v1/agent/stream` through `streamAgentQuery`.
  - Persisted Agent assistant messages.

- [ ] **Step 1: Write failing QAPage integration tests**

Create `apps/luna-corpus-web/src/pages/QAPage.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QAPage } from './QAPage'

function streamFromEvents(events: unknown[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const event of events) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
      }
      controller.close()
    },
  })
}

describe('QAPage Agent flow', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('loads tools, submits selected mode and tools, and persists the Agent answer', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.spyOn(globalThis, 'fetch')

    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
      tools: [
        { name: 'rag_search', description: 'Search documents', parameters_schema: {} },
        { name: 'calculator', description: 'Calculate', parameters_schema: {} },
      ],
    })))

    fetchMock.mockResolvedValueOnce(new Response(streamFromEvents([
      { event: 'start', data: { query: '问题' } },
      { event: 'tool_call', data: { tool: 'rag_search', args: { query: '问题' } } },
      { event: 'token', data: { content: '答案' } },
      { event: 'done', data: { answer: '最终答案', tool_calls: [{ tool: 'rag_search', success: true }] } },
    ])))

    render(<QAPage />)

    await screen.findByLabelText('rag_search')
    await user.selectOptions(screen.getByLabelText('Agent 模式'), 'plan')
    await user.click(screen.getByLabelText('calculator'))
    await user.type(screen.getByPlaceholderText('输入你的问题...'), '问题')
    await user.click(screen.getByRole('button'))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenLastCalledWith('/api/v1/agent/stream', expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          query: '问题',
          mode: 'plan',
          available_tools: ['rag_search'],
          stream: true,
        }),
      }))
    })

    expect(await screen.findByText('最终答案')).toBeInTheDocument()
    expect(screen.getByText('调用工具：rag_search')).toBeInTheDocument()
    expect(screen.getByText('工具: rag_search')).toBeInTheDocument()
  })

  it('blocks submit when tool discovery fails', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
    fetchMock.mockResolvedValueOnce(new Response('fail', { status: 500 }))

    render(<QAPage />)

    expect(await screen.findByText('工具列表加载失败')).toBeInTheDocument()
    expect(screen.getByRole('button')).toBeDisabled()
  })
})
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pnpm nx test luna-corpus-web -- --run src/pages/QAPage.test.tsx
```

Expected: FAIL because QAPage still uses legacy `api.streamQuery` and has no Agent controls.

- [ ] **Step 3: Update QAPage imports and state**

Modify the top of `apps/luna-corpus-web/src/pages/QAPage.tsx`:

```tsx
import { useState, useRef, useEffect } from 'react'
import {
  createInitialAgentStreamState,
  fetchAgentTools,
  reduceAgentStreamState,
  streamAgentQuery,
  type AgentAssistantAnswer,
  type AgentMode,
  type AgentStreamState,
  type AgentTool,
} from '@/lib/agent'
import { QuestionInput } from '@/components/qa/QuestionInput'
import { MessageBubble } from '@/components/qa/MessageBubble'
import { AgentConfigBar } from '@/components/qa/AgentConfigBar'
import { Card } from '@/components/ui/card'

interface Message {
  id: string
  type: 'user' | 'assistant'
  content?: string
  agentAnswer?: AgentAssistantAnswer
}
```

- [ ] **Step 4: Replace QAPage component state and tool loading**

Inside `QAPage`, replace the old streaming state declarations with:

```tsx
const [messages, setMessages] = useState<Message[]>([])
const [isStreaming, setIsStreaming] = useState(false)
const [mode, setMode] = useState<AgentMode>('react')
const [tools, setTools] = useState<AgentTool[]>([])
const [selectedTools, setSelectedTools] = useState<string[]>([])
const [isLoadingTools, setIsLoadingTools] = useState(true)
const [toolsError, setToolsError] = useState<string>()
const [streamingState, setStreamingState] = useState<AgentStreamState>(
  createInitialAgentStreamState('react'),
)
const streamingStateRef = useRef<AgentStreamState>(createInitialAgentStreamState('react'))
const streamingMessageId = useRef<string | null>(null)
const messagesEndRef = useRef<HTMLDivElement>(null)

useEffect(() => {
  let isMounted = true

  async function loadTools() {
    try {
      const agentTools = await fetchAgentTools()
      if (!isMounted) return
      setTools(agentTools)
      setSelectedTools(agentTools.map((tool) => tool.name))
      setToolsError(undefined)
    } catch (error) {
      if (!isMounted) return
      setToolsError('工具列表加载失败')
    } finally {
      if (isMounted) setIsLoadingTools(false)
    }
  }

  void loadTools()

  return () => {
    isMounted = false
  }
}, [])
```

Keep the existing `scrollToBottom` function and update its effect dependency:

```tsx
useEffect(() => {
  scrollToBottom()
}, [messages, streamingState.answer, streamingState.steps.length])
```

- [ ] **Step 5: Replace handleQuery with Agent stream flow**

Replace `handleQuery` in `apps/luna-corpus-web/src/pages/QAPage.tsx`:

```tsx
const handleQuery = async (question: string) => {
  if (isStreaming || isLoadingTools || toolsError) return

  const userMessageId = crypto.randomUUID()
  streamingMessageId.current = crypto.randomUUID()
  const initialState = createInitialAgentStreamState(mode)
  streamingStateRef.current = initialState

  setIsStreaming(true)
  setStreamingState(initialState)
  setMessages((prev) => [
    ...prev,
    { id: userMessageId, type: 'user', content: question },
  ])

  try {
    for await (const event of streamAgentQuery({
      query: question,
      mode,
      available_tools: selectedTools,
      stream: true,
    })) {
      const nextState = reduceAgentStreamState(streamingStateRef.current, event)
      streamingStateRef.current = nextState
      setStreamingState(nextState)
    }
  } catch (error) {
    const nextState = {
      ...streamingStateRef.current,
      error: error instanceof Error ? error.message : 'Unknown error',
      isComplete: true,
    }
    streamingStateRef.current = nextState
    setStreamingState(nextState)
  } finally {
    if (streamingMessageId.current) {
      const finalState = streamingStateRef.current
      setMessages((prev) => [
        ...prev,
        {
          id: streamingMessageId.current!,
          type: 'assistant',
          agentAnswer: {
            answer: finalState.answer || (finalState.error ? '' : '回答生成失败'),
            mode: finalState.mode,
            steps: finalState.steps,
            toolCalls: finalState.toolCalls,
            error: finalState.error,
          },
        },
      ])
    }

    setIsStreaming(false)
    setStreamingState(createInitialAgentStreamState(mode))
    streamingMessageId.current = null
  }
}
```

- [ ] **Step 6: Update QAPage render**

Update the JSX in `QAPage` so the title is followed by `AgentConfigBar`, and messages pass `agentAnswer`:

```tsx
return (
  <div className="flex flex-col h-full">
    <h2 className="text-2xl font-bold mb-4">问答</h2>
    <AgentConfigBar
      mode={mode}
      onModeChange={setMode}
      tools={tools}
      selectedTools={selectedTools}
      onSelectedToolsChange={setSelectedTools}
      isLoadingTools={isLoadingTools}
      toolsError={toolsError}
      disabled={isStreaming}
    />
    <Card className="flex-1 flex flex-col overflow-hidden">
      <div className="flex-1 overflow-auto p-4 space-y-4">
        {messages.length === 0 && !isStreaming && (
          <div className="flex items-center justify-center h-full text-muted-foreground">
            开始提问吧！
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            type={msg.type}
            content={msg.content}
            agentAnswer={msg.agentAnswer}
          />
        ))}
        {isStreaming && streamingMessageId.current && (
          <MessageBubble
            key={streamingMessageId.current}
            type="assistant"
            agentAnswer={streamingState}
            isStreaming={true}
          />
        )}
        <div ref={messagesEndRef} />
      </div>
      <div className="p-4 border-t">
        <QuestionInput
          onSubmit={handleQuery}
          isLoading={isStreaming || isLoadingTools || Boolean(toolsError)}
        />
      </div>
    </Card>
  </div>
)
```

- [ ] **Step 7: Run QAPage tests**

Run:

```bash
pnpm nx test luna-corpus-web -- --run src/pages/QAPage.test.tsx
```

Expected: PASS.

- [ ] **Step 8: Run full frontend checks**

Run:

```bash
pnpm nx test luna-corpus-web
pnpm nx lint luna-corpus-web
pnpm nx build luna-corpus-web
```

Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/luna-corpus-web/src/pages/QAPage.tsx apps/luna-corpus-web/src/pages/QAPage.test.tsx
git commit -m "feat(web): route qa through agent stream"
```

---

### Task 6: Browser Verification and Cleanup

**Files:**
- Modify only files that fail verification due to defects found in this task.

**Interfaces:**
- Consumes: Completed Tasks 1-5.
- Produces: Verified Agent Q&A user flow in the running browser.

- [ ] **Step 1: Start backend and frontend through Nx**

Run backend:

```bash
pnpm nx serve luna-corpus
```

Run frontend in a second terminal:

```bash
pnpm nx dev luna-corpus-web
```

Expected: backend listens on port 8000 and frontend listens on port 3000.

- [ ] **Step 2: Verify tool loading in the browser**

Open the frontend dev server in a browser. Navigate to the Q&A page.

Expected:

- The Agent configuration bar appears under the title.
- The mode selector defaults to `react`.
- Tools from `/api/v1/agent/tools` appear as checkboxes.
- The input is enabled after tools load.

- [ ] **Step 3: Verify Agent query happy path**

Ask a question that should use document search.

Expected:

- The user message appears immediately.
- The assistant bubble shows a spinner.
- The assistant bubble shows concise execution steps.
- The final answer persists in the message list.
- The request in DevTools uses `/api/v1/agent/stream`, not `/api/v1/qa/stream`.

- [ ] **Step 4: Verify mode and tool selection**

Change mode to `plan`. Uncheck `calculator`. Ask another question.

Expected:

- The request body contains `"mode":"plan"`.
- The request body `available_tools` excludes `calculator`.
- The UI remains disabled while streaming and re-enables after completion.

- [ ] **Step 5: Verify stream error recovery**

Stop the backend while the frontend remains open, then submit a question.

Expected:

- The submitted user message remains visible.
- The assistant bubble shows an error.
- The input re-enables after the failed request.

Restart backend after this check:

```bash
pnpm nx serve luna-corpus
```

- [ ] **Step 6: Run final checks**

Run:

```bash
pnpm nx test luna-corpus-web
pnpm nx lint luna-corpus-web
pnpm nx build luna-corpus-web
```

Expected: all PASS.

- [ ] **Step 7: Commit verification fixes if any**

If Step 1-6 required code changes, commit only those changes:

```bash
git add apps/luna-corpus-web
git commit -m "fix(web): polish agent qa flow"
```

If no changes were required, do not create an empty commit.

---

## Self-Review

- Spec coverage: Tasks cover Agent stream replacement, all four modes, backend tool fetching, tool multi-select, concise progress steps, no legacy Q&A UI mode, no raw tool logs, error states, and persisted messages.
- Placeholder scan: The plan contains concrete file paths, code snippets, commands, and expected outcomes. It does not include unresolved placeholders.
- Type consistency: `AgentMode`, `AgentTool`, `AgentStreamState`, `AgentAssistantAnswer`, `AgentConfigBar` props, and `MessageBubble` props are introduced before use and referenced consistently across tasks.
