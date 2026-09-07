import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useAppStore } from '../store/appStore'

export function ProvidersPage() {
  const { t } = useTranslation()
  const { providers, loadProviders, isLoading, error } = useAppStore()

  useEffect(() => {
    void loadProviders().catch(() => undefined)
  }, [loadProviders])

  return (
    <section className="panel">
      <h2>{t('connected_providers')}</h2>
      {isLoading && <div role="status" className="muted">{t('loading')}</div>}
      {error && (
        <div role="alert">
          <strong>{t('error')}</strong>
          <div className="muted">{error}</div>
        </div>
      )}
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
        {!isLoading && !error && providers.length === 0 && (
          <div className="muted">{t('no_data')}</div>
        )}
      </div>
    </section>
  )
}
