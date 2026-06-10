import { Link, useLocation } from 'react-router-dom'
import { MessageSquare, FileText, Activity, Settings } from 'lucide-react'
import { cn } from '@/lib/utils'

const navItems = [
  { path: '/', label: '问答', icon: MessageSquare },
  { path: '/documents', label: '文档', icon: FileText },
  { path: '/status', label: '状态', icon: Activity },
  { path: '/settings', label: '设置', icon: Settings },
]

export function Sidebar() {
  const location = useLocation()

  return (
    <aside className="flex flex-col w-64 border-r bg-card">
      <div className="p-4 border-b">
        <h1 className="text-xl font-bold">Luna-Corpus</h1>
      </div>
      <nav className="flex-1 p-4 space-y-1">
        {navItems.map(({ path, label, icon: Icon }) => (
          <Link
            key={path}
            to={path}
            className={cn(
              'flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors',
              location.pathname === path
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
            )}
          >
            <Icon className="w-4 h-4" />
            {label}
          </Link>
        ))}
      </nav>
    </aside>
  )
}
