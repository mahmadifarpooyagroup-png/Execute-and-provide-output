import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { clearRuntimeToken, getRuntimeToken, setRuntimeToken } from '../services/api'
import { useAppStore } from '../store/appStore'

export function SettingsPage() {
  const { t } = useTranslation()
  const { settings, loadSettings } = useAppStore()
  const [token, setToken] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    void loadSettings()
    setToken(getRuntimeToken() ?? '')
  }, [loadSettings])

  const saveToken = () => {
    if (token.trim()) {
      setRuntimeToken(token.trim())
    } else {
      clearRuntimeToken()
    }
    setSaved(true)
    window.setTimeout(() => setSaved(false), 2000)
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
          <strong>{settings.theme}</strong>
        </div>
        <div className="setting-row">
          <span>{t('auto_recovery')}</span>
          <strong>{settings.autoRecover ? t('enabled') : t('disabled')}</strong>
        </div>
        <div className="setting-row">
          <span>{t('retention_period')}</span>
          <strong>{settings.retentionDays} {t('days')}</strong>
        </div>
        <div className="setting-row">
          <span>{t('notifications')}</span>
          <strong>{settings.notifications ? t('enabled') : t('disabled')}</strong>
        </div>
      </div>
    </section>
  )
}
