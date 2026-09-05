import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useAppStore } from '../store/appStore'

export function SettingsPage() {
  const { t } = useTranslation()
  const { settings, loadSettings } = useAppStore()

  useEffect(() => {
    void loadSettings()
  }, [loadSettings])

  return (
    <section className="panel settings-panel">
      <h2>{t('system_settings')}</h2>
      <div className="settings-list">
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
