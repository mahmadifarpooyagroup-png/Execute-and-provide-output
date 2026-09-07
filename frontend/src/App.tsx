import { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { DashboardPage } from './pages/Dashboard'
import { FirstRunWizardPage } from './pages/FirstRunWizard'
import { ProvidersPage } from './pages/Providers'
import { RecoveryCenterPage } from './pages/RecoveryCenter'
import { SettingsPage } from './pages/Settings'
import { WorkflowsPage } from './pages/Workflows'
import { startDesktopRuntime } from './services/desktopRuntime'
import { isWizardComplete } from './services/wizardState'

function App() {
  useEffect(() => {
    void startDesktopRuntime().catch(() => {
      // The browser development build intentionally runs without the Tauri shell.
      // Runtime errors are surfaced through the normal API error path in the UI.
    })
  }, [])

  const wizardDone = isWizardComplete()

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route
            path="/"
            element={<Navigate to={wizardDone ? '/dashboard' : '/wizard'} replace />}
          />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/providers" element={<ProvidersPage />} />
          <Route path="/workflows" element={<WorkflowsPage />} />
          <Route path="/recovery" element={<RecoveryCenterPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/wizard" element={<FirstRunWizardPage />} />
          <Route path="/first-run" element={<FirstRunWizardPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
