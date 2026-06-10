import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type DocumentCreate } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'

export function AddDocumentDialog() {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<DocumentCreate>({ title: '', content: '', source: '' })
  const queryClient = useQueryClient()

  const createMutation = useMutation({
    mutationFn: api.createDocument,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      setOpen(false)
      setForm({ title: '', content: '', source: '' })
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    createMutation.mutate(form)
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>添加文档</Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>添加新文档</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Label htmlFor="title">标题</Label>
            <Input
              id="title"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              required
            />
          </div>
          <div>
            <Label htmlFor="source">来源 (可选)</Label>
            <Input
              id="source"
              value={form.source || ''}
              onChange={(e) => setForm({ ...form, source: e.target.value })}
            />
          </div>
          <div>
            <Label htmlFor="content">内容</Label>
            <Textarea
              id="content"
              value={form.content}
              onChange={(e) => setForm({ ...form, content: e.target.value })}
              rows={10}
              required
            />
          </div>
          {createMutation.isError && (
            <p className="text-sm text-destructive">
              错误: {createMutation.error.message}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              取消
            </Button>
            <Button type="submit" disabled={createMutation.isPending}>
              {createMutation.isPending ? '创建中...' : '创建'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
