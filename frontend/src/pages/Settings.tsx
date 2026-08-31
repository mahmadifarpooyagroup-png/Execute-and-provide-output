import { useEffect } from 'react'
import { useAppStore } from '../store/appStore'

export function SettingsPage() {
  const { settings, loadSettings } = useAppStore()

  useEffect(() => {
    void loadSettings()
  }, [loadSettings])

  return (
    <section className="panel settings-panel">
      <h2>System settings</h2>
      <div className="settings-list">
        <div className="setting-row">
          <span>Theme</span>
          <strong>{settings.theme}</strong>
        </div>
        <div className="setting-row">
          <span>Auto recovery</span>
          <strong>{settings.autoRecover ? 'Enabled' : 'Disabled'}</strong>
        </div>
        <div className="setting-row">
          <span>Retention period</span>
          <strong>{settings.retentionDays} days</strong>
        </div>
        <div className="setting-row">
          <span>Notifications</span>
          <strong>{settings.notifications ? 'Enabled' : 'Disabled'}</strong>
        </div>
      </div>
    </section>
  )
}
