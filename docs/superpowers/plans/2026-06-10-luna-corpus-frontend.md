# Luna-Corpus Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a React + Vite + shadcn/ui dashboard for the luna-corpus RAG Q&A system

**Architecture:** Single-page application with sidebar navigation, header status bar, and four main pages (Q&A, Documents, Status, Settings). API calls to backend via REST.

**Tech Stack:** React 18, Vite, TypeScript, shadcn/ui, Tailwind CSS, React Router v6, TanStack Query

---

## Task 1: Scaffold React + Vite Project

**Files:**
- Create: `apps/luna-corpus-web/` (new directory)
- Modify: `apps/luna-corpus-web/package.json`, `apps/luna-corpus-web/vite.config.ts`, `apps/luna-corpus-web/tsconfig.json`

- [ ] **Step 1: Create project directory and package.json**

```bash
mkdir -p apps/luna-corpus-web
cd apps/luna-corpus-web
```

Create `apps/luna-corpus-web/package.json`:
```json
{
  "name": "luna-corpus-web",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "lint": "eslint .",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0",
    "@tanstack/react-query": "^5.51.0",
    "clsx": "^2.1.1",
    "tailwind-merge": "^2.4.0",
    "class-variance-authority": "^0.7.0",
    "@radix-ui/react-slot": "^1.1.0",
    "@radix-ui/react-dialog": "^1.1.0",
    "@radix-ui/react-tabs": "^1.1.0",
    "@radix-ui/react-label": "^2.1.0",
    "lucide-react": "^0.408.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.3",
    "vite": "^5.3.4",
    "tailwindcss": "^3.4.6",
    "postcss": "^8.4.39",
    "autoprefixer": "^10.4.19",
    "@eslint/js": "^9.8.0",
    "eslint": "^9.8.0",
    "eslint-plugin-react-hooks": "^5.1.0-rc.0",
    "eslint-plugin-react-refresh": "^0.4.9",
    "globals": "^14.0.0",
    "typescript-eslint": "^8.0.0"
  }
}
```

- [ ] **Step 2: Create Vite config**

Create `apps/luna-corpus-web/vite.config.ts`:
```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
```

- [ ] **Step 3: Create TypeScript config**

Create `apps/luna-corpus-web/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

Create `apps/luna-corpus-web/tsconfig.node.json`:
```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 4: Create Tailwind config**

Create `apps/luna-corpus-web/tailwind.config.js`:
```javascript
/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
```

Create `apps/luna-corpus-web/postcss.config.js`:
```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

- [ ] **Step 5: Create index.html**

Create `apps/luna-corpus-web/index.html`:
```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/vite.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Luna-Corpus Dashboard</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 6: Install dependencies**

Run: `cd apps/luna-corpus-web && npm install`

---

## Task 2: Set Up Core UI Components (shadcn/ui base)

**Files:**
- Create: `apps/luna-corpus-web/src/lib/utils.ts`
- Create: `apps/luna-corpus-web/src/components/ui/button.tsx`
- Create: `apps/luna-corpus-web/src/components/ui/card.tsx`
- Create: `apps/luna-corpus-web/src/components/ui/input.tsx`
- Create: `apps/luna-corpus-web/src/components/ui/badge.tsx`
- Create: `apps/luna-corpus-web/src/components/ui/dialog.tsx`
- Create: `apps/luna-corpus-web/src/components/ui/textarea.tsx`
- Create: `apps/luna-corpus-web/src/components/ui/tabs.tsx`
- Create: `apps/luna-corpus-web/src/components/ui/label.tsx`

- [ ] **Step 1: Create utils**

Create `apps/luna-corpus-web/src/lib/utils.ts`:
```typescript
import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
```

Create `apps/luna-corpus-web/src/lib/api.ts`:
```typescript
const API_BASE = '/api/v1'

export interface HealthStatus {
  status: string
  mysql: string
  chroma: string
  ollama: string
}

export interface QuestionRequest {
  question: string
  top_k?: number
}

export interface Source {
  document_id: string
  document_title?: string
  chunk_content: string
  relevance_score: number
}

export interface AnswerResponse {
  answer: string
  sources: Source[]
  processing_time_ms: number
}

export interface Document {
  id: string
  title: string
  source?: string
  content: string
  has_tables: boolean
  has_code: boolean
  status: string
  created_at: string
  updated_at: string
}

export interface DocumentCreate {
  title: string
  content: string
  source?: string
}

export const api = {
  async healthCheck(): Promise<HealthStatus> {
    const res = await fetch(`${API_BASE}/health`)
    if (!res.ok) throw new Error('Health check failed')
    return res.json()
  },

  async query(question: QuestionRequest): Promise<AnswerResponse> {
    const res = await fetch(`${API_BASE}/qa/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(question),
    })
    if (!res.ok) throw new Error('Query failed')
    return res.json()
  },

  async getDocuments(): Promise<{ documents: Document[]; total: number }> {
    const res = await fetch(`${API_BASE}/documents`)
    if (!res.ok) throw new Error('Failed to fetch documents')
    return res.json()
  },

  async getDocument(id: string): Promise<Document> {
    const res = await fetch(`${API_BASE}/documents/${id}`)
    if (!res.ok) throw new Error('Failed to fetch document')
    return res.json()
  },

  async createDocument(doc: DocumentCreate): Promise<Document> {
    const res = await fetch(`${API_BASE}/documents`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(doc),
    })
    if (!res.ok) throw new Error('Failed to create document')
    return res.json()
  },

  async deleteDocument(id: string): Promise<void> {
    const res = await fetch(`${API_BASE}/documents/${id}`, {
      method: 'DELETE',
    })
    if (!res.ok) throw new Error('Failed to delete document')
  },

  async processDocument(id: string): Promise<{ status: string; chunks_created: number }> {
    const res = await fetch(`${API_BASE}/documents/${id}/process`, {
      method: 'POST',
    })
    if (!res.ok) throw new Error('Failed to process document')
    return res.json()
  },
}
```

- [ ] **Step 2: Create Button component**

Create `apps/luna-corpus-web/src/components/ui/button.tsx`:
```typescript
import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        outline: "border border-input bg-background hover:bg-accent hover:text-accent-foreground",
        secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-9 rounded-md px-3",
        lg: "h-11 rounded-md px-8",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"

export { Button, buttonVariants }
```

- [ ] **Step 3: Create Card component**

Create `apps/luna-corpus-web/src/components/ui/card.tsx`:
```typescript
import * as React from "react"
import { cn } from "@/lib/utils"

const Card = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      "rounded-lg border bg-card text-card-foreground shadow-sm",
      className
    )}
    {...props}
  />
))
Card.displayName = "Card"

const CardHeader = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("flex flex-col space-y-1.5 p-6", className)}
    {...props}
  />
))
CardHeader.displayName = "CardHeader"

const CardTitle = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLHeadingElement>
>(({ className, ...props }, ref) => (
  <h3
    ref={ref}
    className={cn(
      "text-2xl font-semibold leading-none tracking-tight",
      className
    )}
    {...props}
  />
))
CardTitle.displayName = "CardTitle"

const CardDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <p
    ref={ref}
    className={cn("text-sm text-muted-foreground", className)}
    {...props}
  />
))
CardDescription.displayName = "CardDescription"

const CardContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div ref={ref} className={cn("p-6 pt-0", className)} {...props} />
))
CardContent.displayName = "CardContent"

const CardFooter = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("flex items-center p-6 pt-0", className)}
    {...props}
  />
))
CardFooter.displayName = "CardFooter"

export { Card, CardHeader, CardFooter, CardTitle, CardDescription, CardContent }
```

- [ ] **Step 4: Create Input component**

Create `apps/luna-corpus-web/src/components/ui/input.tsx`:
```typescript
import * as React from "react"
import { cn } from "@/lib/utils"

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Input.displayName = "Input"

export { Input }
```

- [ ] **Step 5: Create Textarea component**

Create `apps/luna-corpus-web/src/components/ui/textarea.tsx`:
```typescript
import * as React from "react"
import { cn } from "@/lib/utils"

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {}

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, ...props }, ref) => {
    return (
      <textarea
        className={cn(
          "flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Textarea.displayName = "Textarea"

export { Textarea }
```

- [ ] **Step 6: Create Badge component**

Create `apps/luna-corpus-web/src/components/ui/badge.tsx`:
```typescript
import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground hover:bg-primary/80",
        secondary: "border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80",
        destructive: "border-transparent bg-destructive text-destructive-foreground hover:bg-destructive/80",
        outline: "text-foreground",
        success: "border-transparent bg-green-500 text-white",
        warning: "border-transparent bg-yellow-500 text-white",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}

export { Badge, badgeVariants }
```

---

## Task 3: Create Layout Components

**Files:**
- Create: `apps/luna-corpus-web/src/components/layout/Sidebar.tsx`
- Create: `apps/luna-corpus-web/src/components/layout/Header.tsx`
- Create: `apps/luna-corpus-web/src/components/layout/Layout.tsx`

- [ ] **Step 1: Create Sidebar**

Create `apps/luna-corpus-web/src/components/layout/Sidebar.tsx`:
```typescript
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
```

- [ ] **Step 2: Create Header with Status Indicators**

Create `apps/luna-corpus-web/src/components/layout/Header.tsx`:
```typescript
import { useQuery } from '@tanstack/react-query'
import { api, type HealthStatus } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

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
```

- [ ] **Step 3: Create Layout wrapper**

Create `apps/luna-corpus-web/src/components/layout/Layout.tsx`:
```typescript
import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { Header } from './Header'

export function Layout() {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <div className="flex flex-col flex-1 overflow-hidden">
        <Header />
        <main className="flex-1 overflow-auto p-6 bg-background">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
```

---

## Task 4: Create Q&A Page

**Files:**
- Create: `apps/luna-corpus-web/src/pages/QAPage.tsx`
- Create: `apps/luna-corpus-web/src/components/qa/QuestionInput.tsx`
- Create: `apps/luna-corpus-web/src/components/qa/MessageBubble.tsx`
- Create: `apps/luna-corpus-web/src/components/qa/SourceCard.tsx`

- [ ] **Step 1: Create QuestionInput component**

Create `apps/luna-corpus-web/src/components/qa/QuestionInput.tsx`:
```typescript
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
```

- [ ] **Step 2: Create SourceCard component**

Create `apps/luna-corpus-web/src/components/qa/SourceCard.tsx`:
```typescript
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
```

- [ ] **Step 3: Create MessageBubble component**

Create `apps/luna-corpus-web/src/components/qa/MessageBubble.tsx`:
```typescript
import { type AnswerResponse } from '@/lib/api'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { SourceCard } from './SourceCard'
import { User, Bot } from 'lucide-react'

interface MessageBubbleProps {
  type: 'user' | 'assistant'
  content?: string
  answer?: AnswerResponse
}

export function MessageBubble({ type, content, answer }: MessageBubbleProps) {
  const isUser = type === 'user'

  return (
    <Card className={isUser ? 'bg-primary text-primary-foreground' : ''}>
      <CardHeader className="flex flex-row items-center gap-2 pb-2">
        {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
        <span className="font-medium">{isUser ? '你' : 'Luna'}</span>
      </CardHeader>
      <CardContent className={isUser ? 'pt-0' : ''}>
        {isUser ? (
          <p>{content}</p>
        ) : answer ? (
          <>
            <p className="whitespace-pre-wrap">{answer.answer}</p>
            {answer.sources.length > 0 && (
              <div className="mt-4">
                <h4 className="text-sm font-medium mb-2">参考来源:</h4>
                {answer.sources.map((source, idx) => (
                  <SourceCard key={idx} source={source} />
                ))}
              </div>
            )}
            <p className="text-xs text-muted-foreground mt-4">
              处理时间: {answer.processing_time_ms}ms
            </p>
          </>
        ) : null}
      </CardContent>
    </Card>
  )
}
```

- [ ] **Step 4: Create QAPage**

Create `apps/luna-corpus-web/src/pages/QAPage.tsx`:
```typescript
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api, type AnswerResponse } from '@/lib/api'
import { QuestionInput } from '@/components/qa/QuestionInput'
import { MessageBubble } from '@/components/qa/MessageBubble'
import { Card } from '@/components/ui/card'

interface Message {
  id: string
  type: 'user' | 'assistant'
  content?: string
  answer?: AnswerResponse
}

export function QAPage() {
  const [messages, setMessages] = useState<Message[]>([])

  const queryMutation = useMutation({
    mutationFn: (question: string) => api.query({ question }),
    onSuccess: (data, question) => {
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), type: 'user', content: question },
        { id: crypto.randomUUID(), type: 'assistant', answer: data },
      ])
    },
  })

  return (
    <div className="flex flex-col h-full">
      <h2 className="text-2xl font-bold mb-4">问答</h2>
      <Card className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-auto p-4 space-y-4">
          {messages.length === 0 && (
            <div className="flex items-center justify-center h-full text-muted-foreground">
              开始提问吧！
            </div>
          )}
          {messages.map((msg) => (
            <MessageBubble key={msg.id} type={msg.type} content={msg.content} answer={msg.answer} />
          ))}
        </div>
        <div className="p-4 border-t">
          <QuestionInput
            onSubmit={(q) => queryMutation.mutate(q)}
            isLoading={queryMutation.isPending}
          />
          {queryMutation.isError && (
            <p className="text-sm text-destructive mt-2">
              错误: {queryMutation.error.message}
            </p>
          )}
        </div>
      </Card>
    </div>
  )
}
```

---

## Task 5: Create Documents Page

**Files:**
- Create: `apps/luna-corpus-web/src/pages/DocumentsPage.tsx`
- Create: `apps/luna-corpus-web/src/components/documents/DocumentCard.tsx`
- Create: `apps/luna-corpus-web/src/components/documents/AddDocumentDialog.tsx`

- [ ] **Step 1: Create AddDocumentDialog**

Create `apps/luna-corpus-web/src/components/documents/AddDocumentDialog.tsx`:
```typescript
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
```

- [ ] **Step 2: Create DocumentCard**

Create `apps/luna-corpus-web/src/components/documents/DocumentCard.tsx`:
```typescript
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
```

- [ ] **Step 3: Create Dialog component**

Create `apps/luna-corpus-web/src/components/ui/dialog.tsx`:
```typescript
import * as React from "react"
import * as DialogPrimitive from "@radix-ui/react-dialog"
import { X } from "lucide-react"
import { cn } from "@/lib/utils"

const Dialog = DialogPrimitive.Root
const DialogTrigger = DialogPrimitive.Trigger
const DialogPortal = DialogPrimitive.Portal
const DialogClose = DialogPrimitive.Close

const DialogOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      "fixed inset-0 z-50 bg-black/80 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
      className
    )}
    {...props}
  />
))
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName

const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>(({ className, children, ...props }, ref) => (
  <DialogPortal>
    <DialogOverlay />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        "fixed left-[50%] top-[50%] z-50 grid w-full max-w-lg translate-x-[-50%] translate-y-[-50%] gap-4 border bg-background p-6 shadow-lg duration-200 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[state=closed]:slide-out-to-left-1/2 data-[state=closed]:slide-out-to-top-[48%] data-[state=open]:slide-in-from-left-1/2 data-[state=open]:slide-in-from-top-[48%] sm:rounded-lg",
        className
      )}
      {...props}
    >
      {children}
      <DialogPrimitive.Close className="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:pointer-events-none data-[state=open]:bg-accent data-[state=open]:text-muted-foreground">
        <X className="h-4 w-4" />
        <span className="sr-only">Close</span>
      </DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPortal>
))
DialogContent.displayName = DialogPrimitive.Content.displayName

const DialogHeader = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col space-y-1.5 text-center sm:text-left",
      className
    )}
    {...props}
  />
)
DialogHeader.displayName = "DialogHeader"

const DialogTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn(
      "text-lg font-semibold leading-none tracking-tight",
      className
    )}
    {...props}
  />
))
DialogTitle.displayName = DialogPrimitive.Title.displayName

export {
  Dialog,
  DialogPortal,
  DialogOverlay,
  DialogClose,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
}
```

- [ ] **Step 4: Create DocumentsPage**

Create `apps/luna-corpus-web/src/pages/DocumentsPage.tsx`:
```typescript
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
```

Add missing import to DocumentsPage.tsx:
```typescript
import { useState } from 'react'
```

---

## Task 6: Create Status Page

**Files:**
- Create: `apps/luna-corpus-web/src/pages/StatusPage.tsx`
- Create: `apps/luna-corpus-web/src/components/status/ServiceCard.tsx`

- [ ] **Step 1: Create ServiceCard**

Create `apps/luna-corpus-web/src/components/status/ServiceCard.tsx`:
```typescript
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
```

- [ ] **Step 2: Create StatusPage**

Create `apps/luna-corpus-web/src/pages/StatusPage.tsx`:
```typescript
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
```

---

## Task 7: Create Settings Page

**Files:**
- Create: `apps/luna-corpus-web/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Create SettingsPage**

Create `apps/luna-corpus-web/src/pages/SettingsPage.tsx`:
```typescript
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
```

---

## Task 8: Set Up Routing and Entry Point

**Files:**
- Create: `apps/luna-corpus-web/src/App.tsx`
- Create: `apps/luna-corpus-web/src/main.tsx`
- Create: `apps/luna-corpus-web/src/index.css`

- [ ] **Step 1: Create main.tsx**

Create `apps/luna-corpus-web/src/main.tsx`:
```typescript
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60,
      retry: 1,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
)
```

- [ ] **Step 2: Create App.tsx**

Create `apps/luna-corpus-web/src/App.tsx`:
```typescript
import { Routes, Route } from 'react-router-dom'
import { Layout } from '@/components/layout/Layout'
import { QAPage } from '@/pages/QAPage'
import { DocumentsPage } from '@/pages/DocumentsPage'
import { StatusPage } from '@/pages/StatusPage'
import { SettingsPage } from '@/pages/SettingsPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<QAPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="status" element={<StatusPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  )
}

export default App
```

- [ ] **Step 3: Create index.css**

Create `apps/luna-corpus-web/src/index.css`:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: 0 0% 100%;
    --foreground: 222.2 84% 4.9%;
    --card: 0 0% 100%;
    --card-foreground: 222.2 84% 4.9%;
    --popover: 0 0% 100%;
    --popover-foreground: 222.2 84% 4.9%;
    --primary: 221.2 83.2% 53.3%;
    --primary-foreground: 210 40% 98%;
    --secondary: 210 40% 96.1%;
    --secondary-foreground: 222.2 47.4% 11.2%;
    --muted: 210 40% 96.1%;
    --muted-foreground: 215.4 16.3% 46.9%;
    --accent: 210 40% 96.1%;
    --accent-foreground: 222.2 47.4% 11.2%;
    --destructive: 0 84.2% 60.2%;
    --destructive-foreground: 210 40% 98%;
    --border: 214.3 31.8% 91.4%;
    --input: 214.3 31.8% 91.4%;
    --ring: 221.2 83.2% 53.3%;
    --radius: 0.5rem;
  }
}

@layer base {
  * {
    @apply border-border;
  }
  body {
    @apply bg-background text-foreground;
  }
}
```

---

## Task 9: Add Tabs and Label components

**Files:**
- Create: `apps/luna-corpus-web/src/components/ui/tabs.tsx`
- Create: `apps/luna-corpus-web/src/components/ui/label.tsx`

- [ ] **Step 1: Create Tabs component**

Create `apps/luna-corpus-web/src/components/ui/tabs.tsx`:
```typescript
import * as React from "react"
import * as TabsPrimitive from "@radix-ui/react-tabs"
import { cn } from "@/lib/utils"

const Tabs = TabsPrimitive.Root

const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(
      "inline-flex h-10 items-center justify-center rounded-md bg-muted p-1 text-muted-foreground",
      className
    )}
    {...props}
  />
))
TabsList.displayName = TabsPrimitive.List.displayName

const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      "inline-flex items-center justify-center whitespace-nowrap rounded-sm px-3 py-1.5 text-sm font-medium ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-sm",
      className
    )}
    {...props}
  />
))
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName

const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      "mt-2 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
      className
    )}
    {...props}
  />
))
TabsContent.displayName = TabsPrimitive.Content.displayName

export { Tabs, TabsList, TabsTrigger, TabsContent }
```

- [ ] **Step 2: Create Label component**

Create `apps/luna-corpus-web/src/components/ui/label.tsx`:
```typescript
import * as React from "react"
import * as LabelPrimitive from "@radix-ui/react-label"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const labelVariants = cva(
  "text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
)

const Label = React.forwardRef<
  React.ElementRef<typeof LabelPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root> &
    VariantProps<typeof labelVariants>
>(({ className, ...props }, ref) => (
  <LabelPrimitive.Root
    ref={ref}
    className={cn(labelVariants(), className)}
    {...props}
  />
))
Label.displayName = LabelPrimitive.Root.displayName

export { Label }
```

---

## Task 10: Add to Nx workspace (optional)

**Files:**
- Modify: `nx.json`

- [ ] **Step 1: Add as implicit dependency (optional)**

This step is optional. The frontend can run independently without Nx integration.

To integrate with Nx, add the project to Nx configuration. However, since `@nx/react` plugin is not installed, the frontend app will run standalone via `npm run dev` in the `apps/luna-corpus-web` directory.

---

## Verification

1. Start backend: `cd apps/luna-corpus && uv run uvicorn app.main:app --reload`
2. Start frontend: `cd apps/luna-corpus-web && npm run dev`
3. Open http://localhost:3000
4. Verify all pages load correctly:
   - Q&A page: Submit a question and verify response
   - Documents page: Add, view, delete documents
   - Status page: Verify health indicators
   - Settings page: Verify settings form renders
