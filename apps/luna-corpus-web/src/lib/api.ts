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
