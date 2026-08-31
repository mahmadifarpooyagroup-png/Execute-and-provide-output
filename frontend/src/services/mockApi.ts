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

const dashboardOverview: DashboardOverview = {
  totalProviders: 6,
  healthyProviders: 5,
  activeWorkflows: 12,
  alerts: 3,
  uptime: '99.94%',
}

const providers: ProviderItem[] = [
  {
    id: 'web-01',
    name: 'Airtable Web',
    type: 'Web Automation',
    status: 'healthy',
    lastSync: '2 min ago',
    capability: 'Browser automation',
  },
  {
    id: 'desktop-01',
    name: 'Acme Desktop',
    type: 'Desktop Adapter',
    status: 'warning',
    lastSync: '11 min ago',
    capability: 'UI interactions',
  },
  {
    id: 'api-01',
    name: 'HubSpot API',
    type: 'API Connector',
    status: 'healthy',
    lastSync: '1 min ago',
    capability: 'REST + OAuth',
  },
  {
    id: 'desktop-02',
    name: 'Finance Desktop',
    type: 'Desktop Adapter',
    status: 'offline',
    lastSync: '34 min ago',
    capability: 'Legacy desktop flow',
  },
  {
    id: 'api-02',
    name: 'Mailgun',
    type: 'Email API',
    status: 'healthy',
    lastSync: '3 min ago',
    capability: 'Outbound mail',
  },
]

const workflows: WorkflowItem[] = [
  {
    id: 'wf-103',
    name: 'Customer onboarding sync',
    status: 'running',
    progress: 72,
    owner: 'Ops',
    updatedAt: '2 mins ago',
  },
  {
    id: 'wf-114',
    name: 'Vendor compliance review',
    status: 'paused',
    progress: 41,
    owner: 'Compliance',
    updatedAt: '14 mins ago',
  },
  {
    id: 'wf-118',
    name: 'Billing reconciliation',
    status: 'retrying',
    progress: 61,
    owner: 'Finance',
    updatedAt: '5 mins ago',
  },
  {
    id: 'wf-121',
    name: 'Email campaign handoff',
    status: 'completed',
    progress: 100,
    owner: 'Marketing',
    updatedAt: '1 hour ago',
  },
]

const recoveryQueue: RecoveryItem[] = [
  {
    id: 'rec-01',
    title: 'Session dropped in Finance Desktop',
    priority: 'high',
    eta: '6 min',
    owner: 'Recovery Bot',
  },
  {
    id: 'rec-02',
    title: 'OAuth refresh required for HubSpot',
    priority: 'medium',
    eta: '18 min',
    owner: 'Identity',
  },
  {
    id: 'rec-03',
    title: 'Browser profile mismatch on Airtable',
    priority: 'low',
    eta: '45 min',
    owner: 'Support',
  },
]

const settings: AppSettings = {
  theme: 'dark',
  autoRecover: true,
  retentionDays: 30,
  notifications: true,
}

export async function getDashboardOverview(): Promise<DashboardOverview> {
  return Promise.resolve(dashboardOverview)
}

export async function getProviders(): Promise<ProviderItem[]> {
  return Promise.resolve(providers)
}

export async function getWorkflows(): Promise<WorkflowItem[]> {
  return Promise.resolve(workflows)
}

export async function getRecoveryQueue(): Promise<RecoveryItem[]> {
  return Promise.resolve(recoveryQueue)
}

export async function getSettings(): Promise<AppSettings> {
  return Promise.resolve(settings)
}
