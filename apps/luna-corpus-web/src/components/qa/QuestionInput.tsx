import { useState } from 'react'
import { Send } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface QuestionInputProps {
  onSubmit: (question: string) => void
  isLoading: boolean
}

export function QuestionInput({ onSubmit, isLoading }: QuestionInputProps) {
  const [question, setQuestion] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (question.trim() && !isLoading) {
      onSubmit(question.trim())
      setQuestion('')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex gap-2">
      <Input
        placeholder="输入你的问题..."
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        disabled={isLoading}
        className="flex-1"
      />
      <Button type="submit" disabled={isLoading || !question.trim()}>
        <Send className="w-4 h-4" />
      </Button>
    </form>
  )
}
