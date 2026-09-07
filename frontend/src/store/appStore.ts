import { create } from 'zustand'
import {
  getProviders as getRuntimeProviders,
  getRecoveryQueue as getRuntimeRecoveryQueue,
  getWorkflows as getRuntimeWorkflows,
  type RuntimeProvider,
  type RuntimeRecoveryItem,
  type RuntimeWorkflow,
} from '../services/api'

export type ProviderStatus = 'healthy' | 'warning' | 'offline'
export type WorkflowStatus = 'running' | 'paused' | 'cancelling' | 'cancelled' | 'retrying' | 'completed'
export type RecoveryPriority = 'high' | 'medium' | 'low'

export interface ProviderItem {
  id: string
  name: string
  type: string
  status: ProviderStatus
  lastSync: string
  capability: string
}

export interface WorkflowItem {
  id: string
  name: string
  status: WorkflowStatus
  progress: number
  owner: string
  updatedAt: string
}

export interface RecoveryItem {
  id: string
  title: string
  priority: RecoveryPriority
  eta: string
  owner: string
}

export interface DashboardOverview {
  totalProviders: number
  healthyProviders: number
  activeWorkflows: number
  alerts: number
  uptime: string
}

export interface AppSettings {
  theme: 'dark' | 'light'
  autoRecover: boolean
  retentionDays: number
  notifications: boolean
}

interface AppState {
  dashboard: DashboardOverview | null
  providers: ProviderItem[]
  workflows: WorkflowItem[]
  recoveryQueue: RecoveryItem[]
  settings: AppSettings
  isLoading: boolean
  loadDashboard: () => Promise<void>
  loadProviders: () => Promise<void>
  loadWorkflows: () => Promise<void>
  loadRecoveryQueue: () => Promise<void>
  loadSettings: () => Promise<void>
  saveSettings: (settings: AppSettings) => void
}

const SETTINGS_KEY = 'atrin.app.settings'
const defaultSettings: AppSettings = {
  theme: 'dark',
  autoRecover: true,
  retentionDays: 30,
  notifications: true,
}

function readSettings(): AppSettings {
  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY)
    if (!raw) return defaultSettings
    const parsed = JSON.parse(raw) as Partial<AppSettings>
    const retention = Number(parsed.retentionDays)
    return {
      theme: parsed.theme === 'light' ? 'light' : 'dark',
      autoRecover: parsed.autoRecover !== false,
      retentionDays: Number.isFinite(retention) && retention >= 1
        ? Math.min(3650, Math.trunc(retention))
        : defaultSettings.retentionDays,
      notifications: parsed.notifications !== false,
    }
  } catch {
    return defaultSettings
  }
}

function providerStatus(provider: RuntimeProvider): ProviderStatus {
  switch (provider.auth_state.toUpperCase()) {
    case 'AUTHENTICATED':
      return 'healthy'
    case 'AUTH_REQUIRED':
    case 'WAITING_FOR_AUTH':
      return 'warning'
    default:
      return 'offline'
  }
}

function mapProvider(provider: RuntimeProvider): ProviderItem {
  return {
    id: provider.profile_id,
    name: provider.name,
    type: provider.provider_id,
    status: providerStatus(provider),
    lastSync: provider.updated_at,
    capability: 'Runtime provider profile',
  }
}

function workflowStatus(state: string): WorkflowStatus {
  switch (state) {
    case 'COMPLETED':
      return 'completed'
    case 'CANCELLED':
      return 'cancelled'
    case 'CANCELLING':
      return 'cancelling'
    case 'WAITING_FOR_AUTH':
    case 'WAITING_FOR_NETWORK':
    case 'WAITING_FOR_PROVIDER':
    case 'WAITING_FOR_HUMAN_INTERACTION':
    case 'WAITING_FOR_HUMAN_APPROVAL':
      return 'paused'
    case 'FAILED':
    case 'REJECTED':
      return 'retrying'
    default:
      return 'running'
  }
}

function mapWorkflow(workflow: RuntimeWorkflow): WorkflowItem {
  return {
    id: workflow.workflow_id,
    name: workflow.goal,
    status: workflowStatus(workflow.state),
    progress: workflow.progress ?? (workflow.state === 'COMPLETED' ? 100 : 0),
    owner: 'Runtime',
    updatedAt: workflow.updated_at,
  }
}

function recoveryPriority(item: RuntimeRecoveryItem): RecoveryPriority {
  return item.state === 'WAITING_FOR_PROVIDER' ? 'high' : 'medium'
}

function mapRecoveryItem(item: RuntimeRecoveryItem): RecoveryItem {
  return {
    id: item.workflow_id,
    title: item.goal,
    priority: recoveryPriority(item),
    eta: '—',
    owner: 'Runtime',
  }
}

export const useAppStore = create<AppState>((set) => ({
  dashboard: null,
  providers: [],
  workflows: [],
  recoveryQueue: [],
  settings: defaultSettings,
  isLoading: false,

  loadDashboard: async () => {
    const [providers, workflows, recoveryQueue] = await Promise.all([
      getRuntimeProviders(),
      getRuntimeWorkflows(),
      getRuntimeRecoveryQueue(),
    ])
    const mappedProviders = providers.map(mapProvider)
    const mappedWorkflows = workflows.map(mapWorkflow)
    const dashboard: DashboardOverview = {
      totalProviders: providers.length,
      healthyProviders: mappedProviders.filter((provider) => provider.status === 'healthy').length,
      activeWorkflows: mappedWorkflows.filter((workflow) => !['completed', 'cancelled'].includes(workflow.status)).length,
      alerts: recoveryQueue.length,
      uptime: '—',
    }
    set({ dashboard })
  },

  loadProviders: async () => {
    const providers = await getRuntimeProviders()
    set({ providers: providers.map(mapProvider) })
  },

  loadWorkflows: async () => {
    const workflows = await getRuntimeWorkflows()
    set({ workflows: workflows.map(mapWorkflow) })
  },

  loadRecoveryQueue: async () => {
    const recoveryQueue = await getRuntimeRecoveryQueue()
    set({ recoveryQueue: recoveryQueue.map(mapRecoveryItem) })
  },

  loadSettings: async () => {
    set({ settings: readSettings() })
  },

  saveSettings: (settings: AppSettings) => {
    const retention = Number(settings.retentionDays)
    const normalized: AppSettings = {
      theme: settings.theme === 'light' ? 'light' : 'dark',
      autoRecover: Boolean(settings.autoRecover),
      retentionDays: Number.isFinite(retention)
        ? Math.min(3650, Math.max(1, Math.trunc(retention)))
        : defaultSettings.retentionDays,
      notifications: Boolean(settings.notifications),
    }
    window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(normalized))
    set({ settings: normalized })
  },
}))
