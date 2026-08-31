import { create } from 'zustand'
import {
  getDashboardOverview,
  getProviders,
  getRecoveryQueue,
  getSettings,
  getWorkflows,
} from '../services/mockApi'

export type ProviderStatus = 'healthy' | 'warning' | 'offline'
export type WorkflowStatus = 'running' | 'paused' | 'retrying' | 'completed'
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
}

const defaultSettings: AppSettings = {
  theme: 'dark',
  autoRecover: true,
  retentionDays: 30,
  notifications: true,
}

export const useAppStore = create<AppState>((set) => ({
  dashboard: null,
  providers: [],
  workflows: [],
  recoveryQueue: [],
  settings: defaultSettings,
  isLoading: false,

  loadDashboard: async () => {
    const dashboard = await getDashboardOverview()
    set({ dashboard })
  },

  loadProviders: async () => {
    const providers = await getProviders()
    set({ providers })
  },

  loadWorkflows: async () => {
    const workflows = await getWorkflows()
    set({ workflows })
  },

  loadRecoveryQueue: async () => {
    const recoveryQueue = await getRecoveryQueue()
    set({ recoveryQueue })
  },

  loadSettings: async () => {
    const settings = await getSettings()
    set({ settings })
  },
}))
