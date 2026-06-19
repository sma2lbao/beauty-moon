import { useState, useRef, useEffect } from 'react'
import { api, type AnswerResponse, type Source } from '@/lib/api'
import { QuestionInput } from '@/components/qa/QuestionInput'
import { MessageBubble } from '@/components/qa/MessageBubble'
import { Card } from '@/components/ui/card'

interface Message {
  id: string
  type: 'user' | 'assistant'
  content?: string
  answer?: AnswerResponse
}

interface StreamingState {
  status: string
  answer: string
  sources: Source[]
}

interface DoneData {
  answer: string
  sources: Source[]
  processing_time_ms: number
}

export function QAPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingState, setStreamingState] = useState<StreamingState>({
    status: '',
    answer: '',
    sources: [],
  })
  const streamingMessageId = useRef<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const doneDataRef = useRef<DoneData | null>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages, streamingState.answer])

  const handleQuery = async (question: string) => {
    if (isStreaming) return

    const userMessageId = crypto.randomUUID()
    streamingMessageId.current = crypto.randomUUID()
    doneDataRef.current = null

    setIsStreaming(true)
    setStreamingState({ status: '准备中...', answer: '', sources: [] })
    setMessages((prev) => [
      ...prev,
      { id: userMessageId, type: 'user', content: question },
    ])

    try {
      for await (const event of api.streamQuery(question)) {
        switch (event.event) {
          case 'retrieval_status':
            setStreamingState((prev) => ({ ...prev, status: event.data }))
            break
          case 'token':
            setStreamingState((prev) => ({ ...prev, answer: prev.answer + event.data }))
            break
          case 'done':
            doneDataRef.current = event.data
            setStreamingState((prev) => ({
              ...prev,
              sources: event.data.sources,
              status: `完成 (${event.data.processing_time_ms}ms)`,
            }))
            break
          case 'error':
            setStreamingState((prev) => ({ ...prev, status: `错误: ${event.data}` }))
            break
        }
      }
    } catch (error) {
      setStreamingState((prev) => ({
        ...prev,
        status: `错误: ${error instanceof Error ? error.message : 'Unknown error'}`,
      }))
    } finally {
      const finalData = doneDataRef.current
      const finalAnswer = finalData?.answer || streamingState.answer || '回答生成失败'
      const finalSources = finalData?.sources || streamingState.sources
      const processingTime = finalData?.processing_time_ms || 0

      if (streamingMessageId.current) {
        setMessages((prev) => [
          ...prev,
          {
            id: streamingMessageId.current!,
            type: 'assistant',
            answer: {
              answer: finalAnswer,
              sources: finalSources,
              processing_time_ms: processingTime,
            },
          },
        ])
      }

      setIsStreaming(false)
      setStreamingState({ status: '', answer: '', sources: [] })
      streamingMessageId.current = null
      doneDataRef.current = null
    }
  }

  return (
    <div className="flex flex-col h-full">
      <h2 className="text-2xl font-bold mb-4">问答</h2>
      <Card className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-auto p-4 space-y-4">
          {messages.length === 0 && !isStreaming && (
            <div className="flex items-center justify-center h-full text-muted-foreground">
              开始提问吧！
            </div>
          )}
          {messages.map((msg) => (
            <MessageBubble key={msg.id} type={msg.type} content={msg.content} answer={msg.answer} />
          ))}
          {isStreaming && streamingMessageId.current && (
            <MessageBubble
              key={streamingMessageId.current}
              type="assistant"
              content={streamingState.answer || streamingState.status}
              isStreaming={true}
            />
          )}
          <div ref={messagesEndRef} />
        </div>
        <div className="p-4 border-t">
          <QuestionInput
            onSubmit={handleQuery}
            isLoading={isStreaming}
          />
        </div>
      </Card>
    </div>
  )
}
