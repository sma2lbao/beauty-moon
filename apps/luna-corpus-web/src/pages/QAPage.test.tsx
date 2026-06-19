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
