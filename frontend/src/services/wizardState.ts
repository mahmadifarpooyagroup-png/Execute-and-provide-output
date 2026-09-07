/**
 * First-run wizard completion persistence.
 * Kept separate from React components so it can be shared by routing and the wizard
 * without triggering react-refresh/only-export-components.
 */
const WIZARD_COMPLETE_KEY = 'atrin.wizard.complete'

export function isWizardComplete(): boolean {
  if (typeof window === 'undefined') {
    return false
  }

  try {
    return window.localStorage.getItem(WIZARD_COMPLETE_KEY) === 'true'
  } catch {
    return false
  }
}

export function markWizardComplete(): boolean {
  if (typeof window === 'undefined') {
    return false
  }

  try {
    window.localStorage.setItem(WIZARD_COMPLETE_KEY, 'true')
    return true
  } catch {
    return false
  }
}

export function clearWizardCompletion(): void {
  if (typeof window === 'undefined') {
    return
  }

  try {
    window.localStorage.removeItem(WIZARD_COMPLETE_KEY)
  } catch {
    // localStorage may be unavailable in restricted browser contexts.
  }
}
