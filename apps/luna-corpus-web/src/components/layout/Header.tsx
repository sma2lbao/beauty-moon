import { useQuery } from '@tanstack/react-query'
import { api, type HealthStatus } from '@/lib/api'
import { Badge } from '@/components/ui/badge'

function StatusIndicator({ status }: { status: string }) {
  const isConnected = status === 'connected' || status === 'ok'
  return (
    <Badge variant={isConnected ? 'success' : 'destructive'}>
      {status}
    </Badge>
  )
}

export function Header() {
  const { data } = useQuery<HealthStatus>({
    queryKey: ['health'],
    queryFn: api.healthCheck,
    refetchInterval: 30000,
  })

  return (
    <header className="flex items-center justify-between h-14 px-6 border-b bg-card">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium">健康状态:</span>
      </div>
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">MySQL:</span>
          <StatusIndicator status={data?.mysql || 'checking'} />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Chroma:</span>
          <StatusIndicator status={data?.chroma || 'checking'} />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Ollama:</span>
          <StatusIndicator status={data?.ollama || 'checking'} />
        </div>
      </div>
    </header>
  )
}
