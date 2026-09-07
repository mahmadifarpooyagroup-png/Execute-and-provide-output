import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { cancelWorkflow, pauseWorkflow, resumeWorkflow } from '../services/api'
import { useAppStore } from '../store/appStore'

export function WorkflowsPage() {
  const { t } = useTranslation()
  const { workflows, loadWorkflows } = useAppStore()
  const [busyWorkflow, setBusyWorkflow] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void loadWorkflows()
  }, [loadWorkflows])

  const refresh = async () => {
    await loadWorkflows()
  }

  const runAction = async (workflowId: string, action: () => Promise<unknown>) => {
    setBusyWorkflow(workflowId)
    setError(null)
    try {
      await action()
      await refresh()
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : String(actionError))
    } finally {
      setBusyWorkflow(null)
    }
  }

  return (
    <section className="panel">
      <h2>{t('workflow_engine')}</h2>
      {error && <div className="error-banner" role="alert">{error}</div>}
      <div className="list-block">
        {workflows.map((workflow) => {
          const busy = busyWorkflow === workflow.id
          const completed = workflow.status === 'completed'
          return (
            <div key={workflow.id} className="workflow-card">
              <div className="workflow-head">
                <div>
                  <div className="row-title">{workflow.name}</div>
                  <div className="muted">{t('owner')}: {workflow.owner}</div>
                </div>
                <span className={`badge ${workflow.status}`}>{workflow.status}</span>
              </div>
              <div className="progress-bar" aria-label={`${workflow.progress}% ${t('complete')}`}>
                <span style={{ width: `${workflow.progress}%` }} />
              </div>
              <div className="workflow-footer">
                <span>{workflow.progress}% {t('complete')}</span>
                <span>{workflow.updatedAt}</span>
              </div>
              {!completed && (
                <div className="workflow-actions">
                  <button
                    type="button"
                    className="primary-button"
                    disabled={busy || workflow.status !== 'paused'}
                    onClick={() => void runAction(workflow.id, () => resumeWorkflow(workflow.id))}
                  >
                    {t('resume')}
                  </button>
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={busy || workflow.status === 'paused'}
                    onClick={() => void runAction(workflow.id, () => pauseWorkflow(workflow.id, 'Paused from desktop control plane'))}
                  >
                    {t('pause')}
                  </button>
                  <button
                    type="button"
                    className="secondary-button danger-button"
                    disabled={busy}
                    onClick={() => void runAction(workflow.id, () => cancelWorkflow(workflow.id))}
                  >
                    {t('cancel')}
                  </button>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
