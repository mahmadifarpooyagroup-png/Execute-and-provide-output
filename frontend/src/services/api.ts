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

export interface RuntimeProviderCatalogItem {
  id: string
  name: string
  description?: string | null
  connection_kind: string
  transport?: string | null
  adapter_id: string
  protocol?: string | null
  capabilities: string[]
  enabled: boolean
  health_status: string
  version?: string | null
}

export interface RuntimeWorkflowStep {
  step_id: string
  task_id: string
  action: string
  provider_id: string
  idempotency_key: string
  operation_id: string | null
  status: string
  result: string | null
  evidence: string | null
  order_index: number
  provider_profile_id: string | null
  fencing_token: number | null
  side_effecting: number
}

export interface RuntimeWorkflowDetail {
  workflow: RuntimeWorkflow
  tasks: Array<{
    task_id: string
    description: string
    status: string
    order_index: number
  }>
  steps: RuntimeWorkflowStep[]
  checkpoint: Record<string, unknown> | null
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

export class RuntimeApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'RuntimeApiError'
    this.status = status
  }
}

const API_BASE = (import.meta.env.VITE_ATRIN_API_URL || 'http://127.0.0.1:8765').replace(/\/$/, '')
const TOKEN_STORAGE_KEY = 'atrin.runtime.token'
const REQUEST_TIMEOUT_MS = 30_000

export function getRuntimeToken(): string | null {
  try {
    return window.sessionStorage.getItem(TOKEN_STORAGE_KEY)
  } catch {
    return null
  }
}

export function setRuntimeToken(token: string): void {
  try {
    window.sessionStorage.setItem(TOKEN_STORAGE_KEY, token)
  } catch {
    throw new Error('Browser session storage is unavailable; the runtime token cannot be persisted')
  }
}

export function clearRuntimeToken(): void {
  try {
    window.sessionStorage.removeItem(TOKEN_STORAGE_KEY)
  } catch {
    // Ignore unavailable session storage during logout/cleanup.
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getRuntimeToken()
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (token) headers.set('X-Atrin-Token', token)

  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  try {
    const response = await fetch(`${API_BASE}${path}`, { ...init, headers, signal: controller.signal })
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
      throw new RuntimeApiError(detail, response.status)
    }
    return payload as T
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error(`Runtime API request timed out after ${REQUEST_TIMEOUT_MS / 1000}s`, { cause: error })
    }
    throw error
  } finally {
    window.clearTimeout(timeout)
  }
}

export async function isRuntimeApiAvailable(): Promise<boolean> {
  try {
    await getStatus()
    return true
  } catch {
    return false
  }
}

export async function getStatus(): Promise<{ status: string; message: string; version: string }> {
  return request('/api/v1/status')
}

export async function getProviderCatalog(): Promise<RuntimeProviderCatalogItem[]> {
  const response = await request<{ items: RuntimeProviderCatalogItem[] }>('/api/v1/provider-catalog')
  return response.items
}

export async function createProviderProfile(input: {
  profile_id: string
  provider_id: string
  account_id: string
  name: string
}): Promise<RuntimeProvider> {
  try {
    await request(`/api/v1/providers`, {
      method: 'POST',
      headers: { 'Idempotency-Key': `provider-profile:${input.profile_id}` },
      body: JSON.stringify(input),
    })
  } catch (error) {
    if (error instanceof RuntimeApiError && error.status === 409) {
      try {
        const providers = await getProviders()
        const existing = providers.find((provider) => provider.profile_id === input.profile_id)
        if (
          existing &&
          existing.profile_id === input.profile_id &&
          existing.provider_id === input.provider_id &&
          existing.account_id === input.account_id &&
          existing.name === input.name
        ) {
          return existing
        }
      } catch {
        // Preserve the original conflict when the reconciliation lookup fails.
      }
    }
    throw error
  }
  const providers = await getProviders()
  const created = providers.find((provider) => provider.profile_id === input.profile_id)
  if (!created) throw new Error('Provider profile was created but could not be loaded')
  return created
}

export async function getProviders(limit = 100, offset = 0): Promise<RuntimeProvider[]> {
  const response = await request<{ items: RuntimeProvider[] }>(`/api/v1/providers?limit=${limit}&offset=${offset}`)
  return response.items
}

export async function getWorkflows(limit = 100, offset = 0): Promise<RuntimeWorkflow[]> {
  const response = await request<{ items: RuntimeWorkflow[] }>(`/api/v1/workflows?limit=${limit}&offset=${offset}`)
  return response.items
}

export async function getWorkflowDetail(workflowId: string): Promise<RuntimeWorkflowDetail> {
  return request(`/api/v1/workflows/${encodeURIComponent(workflowId)}`)
}

export async function createWorkflow(input: {
  goal: string
  taskId: string
  description: string
  stepId: string
  action: string
  providerId: string
  providerProfileId?: string | null
  sideEffecting?: boolean
}, idempotencyKey: string): Promise<{ workflow_id: string; state: string }> {
  return request('/api/v1/workflows', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({
      goal: input.goal,
      plan: [{
        task_id: input.taskId,
        description: input.description,
        steps: [{
          step_id: input.stepId,
          action: input.action,
          provider_id: input.providerId,
          provider_profile_id: input.providerProfileId ?? null,
          side_effecting: input.sideEffecting ?? true,
        }],
      }],
    }),
  })
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

// FIX (بند ۲/۱۵): give the retentionDays setting a real backend consumer
export async function runHousekeeping(retentionDays: number): Promise<{
  retention_days: number
  workflows_deleted: number
}> {
  return request(`/api/v1/housekeeping/run?retention_days=${encodeURIComponent(String(retentionDays))}`, {
    method: 'POST',
  })
}
