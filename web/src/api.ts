const API_BASE = '/api'

export interface ReviewRequest {
  code: string
  lang: string
  framework?: string
  api_key?: string
  use_cache?: boolean
}

export interface Finding {
  line: number
  layer: string
  kind: string
  severity: string
  message: string
}

export interface ReviewResponse {
  risk: string
  summary: string
  static_summary: string
  ai_summary: string
  findings: Finding[]
  _perf: Record<string, unknown>
}

export async function review(req: ReviewRequest): Promise<ReviewResponse> {
  const res = await fetch(`${API_BASE}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) {
    throw new Error(`评审请求失败: ${res.status} ${res.statusText}`)
  }
  return res.json()
}

export interface BatchRequest {
  directory: string
  lang?: string
  framework?: string
  api_key?: string
  use_cache?: boolean
  line_threshold?: number
}

export interface BatchFileResult {
  file: string
  lines: number
  risk: string
  elapsed_ms: number
  pool: string
  perf: Record<string, unknown>
}

export interface BatchResponse {
  batch_summary: {
    total_files: number
    small_files: number
    large_files: number
  }
  files: BatchFileResult[]
}

export async function batchReview(req: BatchRequest): Promise<BatchResponse> {
  const res = await fetch(`${API_BASE}/batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) {
    throw new Error(`批量评审请求失败: ${res.status} ${res.statusText}`)
  }
  return res.json()
}

export async function health(): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_BASE}/health`)
  if (!res.ok) throw new Error('健康检查失败')
  return res.json()
}

export async function breakerStatus(): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_BASE}/breaker`)
  if (!res.ok) throw new Error('熔断器状态获取失败')
  return res.json()
}

export async function resetBreaker(lang: string = ''): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_BASE}/breaker/reset`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lang }),
  })
  if (!res.ok) throw new Error('重置熔断器失败')
  return res.json()
}

export async function vectorStats(): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_BASE}/vector/stats`)
  if (!res.ok) throw new Error('向量统计获取失败')
  return res.json()
}

export async function trendReport(): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_BASE}/trend`)
  if (!res.ok) throw new Error('趋势报告获取失败')
  return res.json()
}