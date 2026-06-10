import { type Source } from '@/lib/api'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

interface SourceCardProps {
  source: Source
}

export function SourceCard({ source }: SourceCardProps) {
  return (
    <Card className="mt-2">
      <CardContent className="p-3">
        <div className="flex items-center justify-between mb-2">
          <Badge variant="secondary">来源文档</Badge>
          <span className="text-xs text-muted-foreground">
            相关度: {(source.relevance_score * 100).toFixed(1)}%
          </span>
        </div>
        <p className="text-sm text-muted-foreground line-clamp-3">
          {source.chunk_content}
        </p>
      </CardContent>
    </Card>
  )
}
