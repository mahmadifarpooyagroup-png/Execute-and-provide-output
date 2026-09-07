import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { clearRuntimeToken, getRuntimeToken, setRuntimeToken } from '../services/api'
import { useAppStore } from '../store/appStore'

export function SettingsPage() {
  const { t } = useTranslation()
  const { settings, loadSettings, saveSettings } = useAppStore()
  const [token, setToken] = useState(() => getRuntimeToken() ?? '')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    void loadSettings()
  }, [loadSettings])

  const saveToken = () => {
    if (token.trim()) setRuntimeToken(token.trim())
    else clearRuntimeToken()
    setSaved(true)
    window.setTimeout(() => setSaved(false), 2000)
  }

  const updateSetting = <K extends keyof typeof settings>(key: K, value: (typeof settings)[K]) => {
    saveSettings({ ...settings, [key]: value })
  }

  return (
    <section className="panel settings-panel">
      <h2>{t('system_settings')}</h2>
      <div className="settings-list">
        <div className="setting-row">
          <span>{t('runtime_token')}</span>
          <div>
            <input
              className="setting-input"
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder={t('runtime_token_placeholder')}
              autoComplete="off"
            />
            <button type="button" className="primary-button" onClick={saveToken}>
              {t('save_token')}
            </button>
            {saved && <span className="muted"> {t('saved')}</span>}
          </div>
        </div>
        <div className="setting-row">
          <span>{t('theme')}</span>
          <select
            className="setting-input"
            value={settings.theme}
            onChange={(event) => updateSetting('theme', event.target.value === 'light' ? 'light' : 'dark')}
          >
            <option value="dark">dark</option>
            <option value="light">light</option>
          </select>
        </div>
        <div className="setting-row">
          <span>{t('auto_recovery')}</span>
          <input
            type="checkbox"
            checked={settings.autoRecover}
            onChange={(event) => updateSetting('autoRecover', event.target.checked)}
            aria-label={t('auto_recovery')}
          />
        </div>
        <div className="setting-row">
          <span>{t('retention_period')}</span>
          <input
            className="setting-input"
            type="number"
            min={1}
            max={3650}
            value={settings.retentionDays}
            onChange={(event) => updateSetting('retentionDays', Number(event.target.value))}
          />
          <span className="muted">{t('days')}</span>
        </div>
        <div className="setting-row">
          <span>{t('notifications')}</span>
          <input
            type="checkbox"
            checked={settings.notifications}
            onChange={(event) => updateSetting('notifications', event.target.checked)}
            aria-label={t('notifications')}
          />
        </div>
      </div>
    </section>
  )
}
