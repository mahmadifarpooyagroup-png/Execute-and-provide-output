import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useAppStore } from '../store/appStore'

export function ProvidersPage() {
  const { t } = useTranslation()
  const { providers, loadProviders } = useAppStore()

  useEffect(() => {
    void loadProviders()
  }, [loadProviders])

  return (
    <section className="panel">
      <h2>{t('connected_providers')}</h2>
      <div className="list-block">
        {providers.map((provider) => (
          <div key={provider.id} className="row-item provider-row">
            <div>
              <div className="row-title">{provider.name}</div>
              <div className="muted">{provider.capability}</div>
            </div>
            <div className="row-meta">
              <span className={`badge ${provider.status}`}>{provider.status}</span>
              <span className="muted">{provider.lastSync}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
