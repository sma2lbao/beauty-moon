import { type Document } from '@/lib/api'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { FileText, Trash, Play } from 'lucide-react'

interface DocumentCardProps {
  doc: Document
  onProcess: (id: string) => void
  onDelete: (id: string) => void
  isProcessing: boolean
}

export function DocumentCard({ doc, onProcess, onDelete, isProcessing }: DocumentCardProps) {
  const statusVariant = doc.status === 'processed' ? 'success' : 'warning'

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div className="flex items-center gap-2">
          <FileText className="w-4 h-4" />
          <span className="font-medium">{doc.title}</span>
        </div>
        <Badge variant={statusVariant}>{doc.status}</Badge>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {doc.source && (
            <p className="text-sm text-muted-foreground">来源: {doc.source}</p>
          )}
          <p className="text-sm text-muted-foreground line-clamp-2">
            {doc.content.substring(0, 200)}...
          </p>
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            {doc.has_code && <Badge variant="secondary">含代码</Badge>}
            {doc.has_tables && <Badge variant="secondary">含表格</Badge>}
            <span>创建于: {new Date(doc.created_at).toLocaleDateString()}</span>
          </div>
          <div className="flex gap-2 pt-2">
            {doc.status !== 'processed' && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => onProcess(doc.id)}
                disabled={isProcessing}
              >
                <Play className="w-3 h-3 mr-1" />
                {isProcessing ? '处理中...' : '处理'}
              </Button>
            )}
            <Button
              size="sm"
              variant="destructive"
              onClick={() => onDelete(doc.id)}
            >
              <Trash className="w-3 h-3 mr-1" />
              删除
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
