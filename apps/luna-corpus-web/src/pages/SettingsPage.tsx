import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export function SettingsPage() {
  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">设置</h2>

      <Card>
        <CardHeader>
          <CardTitle>API 配置</CardTitle>
          <CardDescription>配置后端 API 连接</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="api-url">API 地址</Label>
            <Input
              id="api-url"
              defaultValue="/api/v1"
              disabled
              className="max-w-md"
            />
            <p className="text-xs text-muted-foreground">
              当前使用 Vite 代理，指向 http://localhost:8000
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>向量检索配置</CardTitle>
          <CardDescription>RAG 检索相关参数</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="top-k">Top-K 检索数量</Label>
            <Input
              id="top-k"
              type="number"
              defaultValue="5"
              className="max-w-xs"
            />
            <p className="text-xs text-muted-foreground">
              从向量数据库中检索的相关文档数量 (1-20)
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
