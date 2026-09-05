import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useAppStore } from '../store/appStore'

export function WorkflowsPage() {
  const { t } = useTranslation()
  const { workflows, loadWorkflows } = useAppStore()

  useEffect(() => {
    void loadWorkflows()
  }, [loadWorkflows])

  return (
    <section className="panel">
      <h2>{t('workflow_engine')}</h2>
      <div className="list-block">
        {workflows.map((workflow) => (
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
          </div>
        ))}
      </div>
    </section>
  )
}
