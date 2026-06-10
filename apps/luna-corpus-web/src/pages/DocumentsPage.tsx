import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { AddDocumentDialog } from '@/components/documents/AddDocumentDialog'
import { DocumentCard } from '@/components/documents/DocumentCard'
import { Input } from '@/components/ui/input'

export function DocumentsPage() {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['documents'],
    queryFn: api.getDocuments,
  })

  const processMutation = useMutation({
    mutationFn: api.processDocument,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: api.deleteDocument,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })

  const filteredDocs = data?.documents.filter((doc) =>
    doc.title.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">文档管理</h2>
        <AddDocumentDialog />
      </div>

      <Input
        placeholder="搜索文档..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="max-w-sm"
      />

      {isLoading ? (
        <div className="text-center py-8 text-muted-foreground">加载中...</div>
      ) : filteredDocs?.length === 0 ? (
        <div className="text-center py-8 text-muted-foreground">
          暂无文档，点击"添加文档"开始
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {filteredDocs?.map((doc) => (
            <DocumentCard
              key={doc.id}
              doc={doc}
              onProcess={(id) => processMutation.mutate(id)}
              onDelete={(id) => deleteMutation.mutate(id)}
              isProcessing={processMutation.isPending}
            />
          ))}
        </div>
      )}
    </div>
  )
}
