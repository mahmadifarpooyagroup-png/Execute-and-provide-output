import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useAppStore } from '../store/appStore'

export function RecoveryCenterPage() {
  const { t } = useTranslation()
  const { recoveryQueue, loadRecoveryQueue } = useAppStore()

  useEffect(() => {
    void loadRecoveryQueue()
  }, [loadRecoveryQueue])

  return (
    <section className="panel">
      <h2>{t('recovery_center')}</h2>
      <div className="list-block">
        {recoveryQueue.map((item) => (
          <div key={item.id} className="row-item wide-row">
            <div>
              <div className="row-title">{item.title}</div>
                <div className="muted">{t('owner')}: {item.owner}</div>
            </div>
            <div className="row-meta">
              <span className={`badge ${item.priority}`}>{item.priority}</span>
              <span className="muted">{t('eta')} {item.eta}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
