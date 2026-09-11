import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { resumeWorkflow } from '../services/api'
import { useAppStore } from '../store/appStore'

export function RecoveryCenterPage() {
  const { t } = useTranslation()
  const { recoveryQueue, loadRecoveryQueue, settings } = useAppStore()
  const [busyWorkflow, setBusyWorkflow] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // FIX (بند ۲/۱۵): track which items auto-recovery has already attempted
  // this session so a failed auto-attempt doesn't retry in a tight loop.
  const autoAttempted = useRef<Set<string>>(new Set())

  useEffect(() => {
    void loadRecoveryQueue()
  }, [loadRecoveryQueue])

  const recover = async (workflowId: string) => {
    setBusyWorkflow(workflowId)
    setError(null)
    try {
      await resumeWorkflow(workflowId)
      await loadRecoveryQueue()
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : String(actionError))
    } finally {
      setBusyWorkflow(null)
    }
  }

  // FIX (בند ۲/۱۵): honor the 'autoRecover' setting instead of leaving it
  // as inert stored state — automatically attempt recovery for queued items
  // the first time they appear, without re-attempting known failures.
  useEffect(() => {
    if (!settings.autoRecover || busyWorkflow) return
    const next = recoveryQueue.find((item) => !autoAttempted.current.has(item.id))
    if (!next) return
    autoAttempted.current.add(next.id)
    void recover(next.id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings.autoRecover, recoveryQueue, busyWorkflow])

  return (
    <section className="panel">
      <h2>{t('recovery_center')}</h2>
      {settings.autoRecover && (
        <div className="muted" role="status">{t('auto_recovery_active')}</div>
      )}
      {error && <div className="error-banner" role="alert">{error}</div>}
      <div className="list-block">
        {recoveryQueue.map((item) => {
          const busy = busyWorkflow === item.id
          return (
            <div key={item.id} className="row-item wide-row">
              <div>
                <div className="row-title">{item.title}</div>
                <div className="muted">{t('owner')}: {item.owner}</div>
              </div>
              <div className="row-meta">
                <span className={`badge ${item.priority}`}>{item.priority}</span>
                <span className="muted">{t('eta')} {item.eta}</span>
                <button
                  type="button"
                  className="primary-button"
                  disabled={busy}
                  onClick={() => void recover(item.id)}
                >
                  {t('recover')}
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
