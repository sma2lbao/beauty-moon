import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api, type AnswerResponse } from '@/lib/api'
import { QuestionInput } from '@/components/qa/QuestionInput'
import { MessageBubble } from '@/components/qa/MessageBubble'
import { Card } from '@/components/ui/card'

interface Message {
  id: string
  type: 'user' | 'assistant'
  content?: string
  answer?: AnswerResponse
}

export function QAPage() {
  const [messages, setMessages] = useState<Message[]>([])

  const queryMutation = useMutation({
    mutationFn: (question: string) => api.query({ question }),
    onSuccess: (data, question) => {
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), type: 'user', content: question },
        { id: crypto.randomUUID(), type: 'assistant', answer: data },
      ])
    },
  })

  return (
    <div className="flex flex-col h-full">
      <h2 className="text-2xl font-bold mb-4">问答</h2>
      <Card className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-auto p-4 space-y-4">
          {messages.length === 0 && (
            <div className="flex items-center justify-center h-full text-muted-foreground">
              开始提问吧！
            </div>
          )}
          {messages.map((msg) => (
            <MessageBubble key={msg.id} type={msg.type} content={msg.content} answer={msg.answer} />
          ))}
        </div>
        <div className="p-4 border-t">
          <QuestionInput
            onSubmit={(q) => queryMutation.mutate(q)}
            isLoading={queryMutation.isPending}
          />
          {queryMutation.isError && (
            <p className="text-sm text-destructive mt-2">
              错误: {queryMutation.error.message}
            </p>
          )}
        </div>
      </Card>
    </div>
  )
}
