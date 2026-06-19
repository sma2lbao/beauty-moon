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
