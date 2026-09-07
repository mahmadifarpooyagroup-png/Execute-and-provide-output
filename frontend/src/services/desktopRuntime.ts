import { invoke } from '@tauri-apps/api/core'

export type RuntimeStatus = 'running' | 'starting' | 'stopped'

function isTauri(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

export async function startDesktopRuntime(): Promise<string> {
  if (!isTauri()) return 'browser'
  return invoke<string>('start_runtime')
}

export async function getDesktopRuntimeStatus(): Promise<RuntimeStatus | 'browser'> {
  if (!isTauri()) return 'browser'
  return invoke<RuntimeStatus>('runtime_status')
}

export async function stopDesktopRuntime(): Promise<string> {
  if (!isTauri()) return 'browser'
  return invoke<string>('stop_runtime')
}
