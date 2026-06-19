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

export function QAPage() {
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
      } catch {
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

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages, streamingState.answer, streamingState.steps.length])

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
}
