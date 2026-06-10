import { useQuery } from '@tanstack/react-query'
import { api, type HealthStatus } from '@/lib/api'
import { ServiceCard } from '@/components/status/ServiceCard'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Loader } from 'lucide-react'

export function StatusPage() {
  const { data, isLoading, isError, error } = useQuery<HealthStatus>({
    queryKey: ['health'],
    queryFn: api.healthCheck,
    refetchInterval: 10000,
  })

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">系统状态</h2>

      <div className="grid gap-4 md:grid-cols-3">
        <ServiceCard name="MySQL" status={data?.mysql || 'checking'} />
        <ServiceCard name="ChromaDB" status={data?.chroma || 'checking'} />
        <ServiceCard name="Ollama" status={data?.ollama || 'checking'} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>整体状态</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader className="w-4 h-4 animate-spin" />
              检查中...
            </div>
          ) : isError ? (
            <p className="text-destructive">连接错误: {error.message}</p>
          ) : (
            <p className={`text-lg font-medium ${
              data?.status === 'ok' ? 'text-green-600' : 'text-yellow-600'
            }`}>
              {data?.status === 'ok' ? '所有服务正常' : '部分服务异常'}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
