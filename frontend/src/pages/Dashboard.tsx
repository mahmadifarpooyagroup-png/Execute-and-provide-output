import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useAppStore } from '../store/appStore'

export function DashboardPage() {
  const { t } = useTranslation()
  const { dashboard, loadDashboard, providers, loadProviders } = useAppStore()

  useEffect(() => {
    void loadDashboard()
    void loadProviders()
  }, [loadDashboard, loadProviders])

  return (
    <section className="page-grid">
      <div className="panel stats-grid">
        <div className="stat-card">
          <span>{t('total_providers')}</span>
          <strong>{dashboard?.totalProviders ?? 0}</strong>
        </div>
        <div className="stat-card">
          <span>{t('healthy')}</span>
          <strong>{dashboard?.healthyProviders ?? 0}</strong>
        </div>
        <div className="stat-card">
          <span>{t('active_workflows')}</span>
          <strong>{dashboard?.activeWorkflows ?? 0}</strong>
        </div>
        <div className="stat-card">
          <span>{t('uptime')}</span>
          <strong>{dashboard?.uptime ?? '0%'}</strong>
        </div>
      </div>

      <div className="panel">
        <h2>{t('provider_health')}</h2>
        <div className="list-block">
          {providers.slice(0, 4).map((provider) => (
            <div key={provider.id} className="row-item">
              <div>
                <div className="row-title">{provider.name}</div>
                <div className="muted">{provider.type}</div>
              </div>
              <span className={`badge ${provider.status}`}>{provider.status}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
