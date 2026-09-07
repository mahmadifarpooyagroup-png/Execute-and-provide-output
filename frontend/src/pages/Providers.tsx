import { FormEvent, useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { createProviderProfile, getProviderCatalog, type RuntimeProviderCatalogItem } from '../services/api'
import { useAppStore } from '../store/appStore'

export function ProvidersPage() {
  const { t } = useTranslation()
  const { providers, loadProviders, isLoading, error } = useAppStore()
  const [catalog, setCatalog] = useState<RuntimeProviderCatalogItem[]>([])
  const [catalogLoading, setCatalogLoading] = useState(true)
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [profileId, setProfileId] = useState('')
  const [accountId, setAccountId] = useState('')
  const [name, setName] = useState('')
  const [providerId, setProviderId] = useState('')
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const loadCatalog = useCallback(async () => {
    setCatalogLoading(true)
    setCatalogError(null)
    try {
      const items = await getProviderCatalog()
      setCatalog(items)
      if (!providerId && items.length > 0) setProviderId(items[0].id)
    } catch (catalogLoadError) {
      setCatalogError(catalogLoadError instanceof Error ? catalogLoadError.message : String(catalogLoadError))
    } finally {
      setCatalogLoading(false)
    }
  }, [providerId])

  useEffect(() => {
    void loadProviders().catch(() => undefined)
    void loadCatalog()
  }, [loadCatalog, loadProviders])

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSaving(true)
    setFormError(null)
    try {
      await createProviderProfile({ profile_id: profileId.trim(), provider_id: providerId, account_id: accountId.trim(), name: name.trim() })
      setProfileId('')
      setAccountId('')
      setName('')
      await loadProviders()
    } catch (saveError) {
      setFormError(saveError instanceof Error ? saveError.message : String(saveError))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="page-grid">
      <div className="panel">
        <h2>{t('connect_providers')}</h2>
        {formError && <div className="error-banner" role="alert">{formError}</div>}
        {catalogError && <div className="error-banner" role="alert">{catalogError}</div>}
        {catalogLoading ? (
          <div role="status" className="muted">{t('loading')}</div>
        ) : catalog.length === 0 ? (
          <div className="muted">{t('no_provider_adapters')}</div>
        ) : (
          <form className="form-grid" onSubmit={submit}>
            <label>
              <span>{t('provider')}</span>
              <select className="setting-input" value={providerId} onChange={(event) => setProviderId(event.target.value)} required>
                {catalog.map((item) => (
                  <option key={item.id} value={item.id}>{item.name} · {item.adapter_id}</option>
                ))}
              </select>
            </label>
            <label>
              <span>{t('profile_id')}</span>
              <input className="setting-input" value={profileId} onChange={(event) => setProfileId(event.target.value)} placeholder={t('profile_id_placeholder')} required />
            </label>
            <label>
              <span>{t('account_id')}</span>
              <input className="setting-input" value={accountId} onChange={(event) => setAccountId(event.target.value)} placeholder={t('account_id_placeholder')} required />
            </label>
            <label>
              <span>{t('display_name')}</span>
              <input className="setting-input" value={name} onChange={(event) => setName(event.target.value)} placeholder={t('display_name_placeholder')} required />
            </label>
            <button className="primary-button" type="submit" disabled={saving || !providerId}>
              {saving ? t('saving') : t('add_provider')}
            </button>
          </form>
        )}
      </div>

      <div className="panel">
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
                <div className="muted">{provider.type} · {provider.accountId}</div>
                <div className="muted">{provider.id}</div>
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
      </div>
    </section>
  )
}
