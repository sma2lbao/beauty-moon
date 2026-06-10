import { type AnswerResponse } from '@/lib/api'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { SourceCard } from './SourceCard'
import { User, Bot } from 'lucide-react'

interface MessageBubbleProps {
  type: 'user' | 'assistant'
  content?: string
  answer?: AnswerResponse
}

export function MessageBubble({ type, content, answer }: MessageBubbleProps) {
  const isUser = type === 'user'

  return (
    <Card className={isUser ? 'bg-primary text-primary-foreground' : ''}>
      <CardHeader className="flex flex-row items-center gap-2 pb-2">
        {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
        <span className="font-medium">{isUser ? '你' : 'Luna'}</span>
      </CardHeader>
      <CardContent className={isUser ? 'pt-0' : ''}>
        {isUser ? (
          <p>{content}</p>
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
        ) : null}
      </CardContent>
    </Card>
  )
}
