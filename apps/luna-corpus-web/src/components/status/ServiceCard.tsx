import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { CheckCircle, XCircle, Loader } from 'lucide-react'

interface ServiceCardProps {
  name: string
  status: string
}

export function ServiceCard({ name, status }: ServiceCardProps) {
  const isConnected = status === 'connected' || status === 'ok'
  const isChecking = status === 'checking'

  const Icon = isChecking ? Loader : isConnected ? CheckCircle : XCircle

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>{name}</CardTitle>
        <Icon
          className={`w-5 h-5 ${isChecking ? 'animate-spin' : ''}`}
          style={{ color: isChecking ? '#888' : isConnected ? '#22c55e' : '#ef4444' }}
        />
      </CardHeader>
      <CardContent>
        <Badge variant={isConnected ? 'success' : 'destructive'}>
          {isChecking ? '检查中...' : status}
        </Badge>
      </CardContent>
    </Card>
  )
}
