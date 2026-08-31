import { useEffect } from 'react'
import { useAppStore } from '../store/appStore'

export function WorkflowsPage() {
  const { workflows, loadWorkflows } = useAppStore()

  useEffect(() => {
    void loadWorkflows()
  }, [loadWorkflows])

  return (
    <section className="panel">
      <h2>Workflow engine</h2>
      <div className="list-block">
        {workflows.map((workflow) => (
          <div key={workflow.id} className="workflow-card">
            <div className="workflow-head">
              <div>
                <div className="row-title">{workflow.name}</div>
                <div className="muted">Owner: {workflow.owner}</div>
              </div>
              <span className={`badge ${workflow.status}`}>{workflow.status}</span>
            </div>
            <div className="progress-bar" aria-label={`${workflow.progress}% complete`}>
              <span style={{ width: `${workflow.progress}%` }} />
            </div>
            <div className="workflow-footer">
              <span>{workflow.progress}% complete</span>
              <span>{workflow.updatedAt}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
