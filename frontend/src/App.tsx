import { Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { DashboardPage } from './pages/Dashboard'
import { FirstRunWizardPage } from './pages/FirstRunWizard'
import { ProvidersPage } from './pages/Providers'
import { RecoveryCenterPage } from './pages/RecoveryCenter'
import { SettingsPage } from './pages/Settings'
import { WorkflowsPage } from './pages/Workflows'

function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/providers" element={<ProvidersPage />} />
        <Route path="/workflows" element={<WorkflowsPage />} />
        <Route path="/recovery" element={<RecoveryCenterPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/first-run" element={<FirstRunWizardPage />} />
      </Route>
    </Routes>
  )
}

export default App
