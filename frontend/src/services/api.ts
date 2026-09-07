export interface RuntimeWorkflow {
  workflow_id: string
  goal: string
  state: string
  plan_version: number
  client_request_id?: string | null
  created_at: string
  updated_at: string
  progress?: number
}

export interface RuntimeProvider {
  profile_id: string
  provider_id: string
  account_id: string
  name: string
  auth_state: string
  fencing_token: number
  created_at: string
  updated_at: string
}

export interface RuntimeRecoveryItem {
  workflow_id: string
  goal: string
  state: string
  updated_at: string
}

export interface RuntimeAuditItem {
  seq: number
  timestamp: string
  workflow_id: string | null
  event_type: string
  actor: string
  payload: string | null
  prev_hash: string | null
  entry_hash: string
}

const API_BASE = (import.meta.env.VITE_ATRIN_API_URL || 'http://127.0.0.1:8765').replace(/\/$/, '')
const TOKEN_STORAGE_KEY = 'atrin.runtime.token'

export function getRuntimeToken(): string | null {
  return window.sessionStorage.getItem(TOKEN_STORAGE_KEY)
}

export function setRuntimeToken(token: string): void {
  window.sessionStorage.setItem(TOKEN_STORAGE_KEY, token)
}

export function clearRuntimeToken(): void {
  window.sessionStorage.removeItem(TOKEN_STORAGE_KEY)
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getRuntimeToken()
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (token) headers.set('X-Atrin-Token', token)

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers })
  const raw = await response.text()
  let payload: unknown = null
  if (raw) {
    try {
      payload = JSON.parse(raw)
    } catch {
      payload = raw
    }
  }
  if (!response.ok) {
    const detail = typeof payload === 'object' && payload !== null && 'detail' in payload
      ? String((payload as { detail: unknown }).detail)
      : `Runtime API request failed (${response.status})`
    throw new Error(detail)
  }
  return payload as T
}

export function isRuntimeApiAvailable(): boolean {
  return Boolean(API_BASE)
}

export async function getStatus(): Promise<{ status: string; message: string; database: string; version: string }> {
  return request('/api/v1/status')
}

export async function getProviders(limit = 100, offset = 0): Promise<RuntimeProvider[]> {
  const response = await request<{ items: RuntimeProvider[] }>(`/api/v1/providers?limit=${limit}&offset=${offset}`)
  return response.items
}

export async function getWorkflows(limit = 100, offset = 0): Promise<RuntimeWorkflow[]> {
  const response = await request<{ items: RuntimeWorkflow[] }>(`/api/v1/workflows?limit=${limit}&offset=${offset}`)
  return response.items
}

export async function getRecoveryQueue(limit = 100, offset = 0): Promise<RuntimeRecoveryItem[]> {
  const response = await request<{ items: RuntimeRecoveryItem[] }>(`/api/v1/recovery?limit=${limit}&offset=${offset}`)
  return response.items
}

export async function getAudit(workflowId?: string, limit = 100): Promise<RuntimeAuditItem[]> {
  const query = workflowId ? `?workflow_id=${encodeURIComponent(workflowId)}&limit=${limit}` : `?limit=${limit}`
  const response = await request<{ items: RuntimeAuditItem[] }>(`/api/v1/audit${query}`)
  return response.items
}

export async function pauseWorkflow(workflowId: string, reason: string): Promise<void> {
  await request(`/api/v1/workflows/${encodeURIComponent(workflowId)}/pause`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}

export async function resumeWorkflow(workflowId: string): Promise<unknown> {
  return request(`/api/v1/workflows/${encodeURIComponent(workflowId)}/resume`, { method: 'POST' })
}

export async function cancelWorkflow(workflowId: string): Promise<void> {
  await request(`/api/v1/workflows/${encodeURIComponent(workflowId)}/cancel`, { method: 'POST' })
}

export async function runWorkflowStep(workflowId: string, stepId: string): Promise<unknown> {
  return request(`/api/v1/workflows/${encodeURIComponent(workflowId)}/run`, {
    method: 'POST',
    body: JSON.stringify({ step_id: stepId }),
  })
}
