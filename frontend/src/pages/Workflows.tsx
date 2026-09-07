import { FormEvent, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { cancelWorkflow, createWorkflow, getWorkflowDetail, pauseWorkflow, resumeWorkflow, runWorkflowStep } from '../services/api'
import { useAppStore } from '../store/appStore'

export function WorkflowsPage() {
  const { t } = useTranslation()
  const { workflows, providers, loadWorkflows } = useAppStore()
  const [busyWorkflow, setBusyWorkflow] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [goal, setGoal] = useState('')
  const [action, setAction] = useState('')
  const [providerId, setProviderId] = useState('')
  const [creating, setCreating] = useState(false)

  const selectedProvider = useMemo(
    () => providers.find((provider) => provider.id === providerId) ?? providers[0],
    [providers, providerId],
  )

  useEffect(() => {
    void loadWorkflows().catch(() => undefined)
  }, [loadWorkflows])

  useEffect(() => {
    if (!providerId && providers.length > 0) setProviderId(providers[0].id)
  }, [providerId, providers])

  useEffect(() => {
    const hasActive = workflows.some((workflow) => !['completed', 'cancelled'].includes(workflow.status))
    if (!hasActive) return undefined
    const interval = window.setInterval(() => {
      void loadWorkflows().catch(() => undefined)
    }, 2000)
    return () => window.clearInterval(interval)
  }, [loadWorkflows, workflows])

  const refresh = async () => {
    await loadWorkflows()
  }

  const runAction = async (workflowId: string, actionFn: () => Promise<unknown>) => {
    setBusyWorkflow(workflowId)
    setError(null)
    try {
      await actionFn()
      await refresh()
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : String(actionError))
    } finally {
      setBusyWorkflow(null)
    }
  }

  const createNewWorkflow = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedProvider) {
      setError(t('no_provider_adapters'))
      return
    }
    setCreating(true)
    setError(null)
    try {
      await createWorkflow({
        goal: goal.trim(),
        taskId: `task-${crypto.randomUUID()}`,
        description: goal.trim(),
        stepId: `step-${crypto.randomUUID()}`,
        action: action.trim(),
        providerId: selectedProvider.type,
        providerProfileId: selectedProvider.id,
        sideEffecting: false,
      }, `workflow-${crypto.randomUUID()}`)
      setGoal('')
      setAction('')
      await refresh()
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : String(createError))
    } finally {
      setCreating(false)
    }
  }

  const runNext = async (workflowId: string) => {
    setBusyWorkflow(workflowId)
    setError(null)
    try {
      const detail = await getWorkflowDetail(workflowId)
      const pending = detail.steps.find((step) => step.status === 'PENDING' || step.status === 'FAILED' || step.status === 'AMBIGUOUS')
      if (!pending) throw new Error(t('no_runnable_step'))
      await runWorkflowStep(workflowId, pending.step_id)
      await refresh()
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : String(runError))
    } finally {
      setBusyWorkflow(null)
    }
  }

  return (
    <section className="page-grid">
      <div className="panel">
        <h2>{t('create_workflow')}</h2>
        {error && <div className="error-banner" role="alert">{error}</div>}
        {providers.length === 0 ? (
          <div className="muted">{t('no_provider_profiles')}</div>
        ) : (
          <form className="form-grid" onSubmit={createNewWorkflow}>
            <label>
              <span>{t('provider')}</span>
              <select className="setting-input" value={providerId} onChange={(event) => setProviderId(event.target.value)} required>
                {providers.map((provider) => (
                  <option key={provider.id} value={provider.id}>{provider.name} · {provider.type}</option>
                ))}
              </select>
            </label>
            <label>
              <span>{t('workflow_goal')}</span>
              <input className="setting-input" value={goal} onChange={(event) => setGoal(event.target.value)} placeholder={t('workflow_goal_placeholder')} required />
            </label>
            <label>
              <span>{t('workflow_action')}</span>
              <textarea className="setting-input" rows={5} value={action} onChange={(event) => setAction(event.target.value)} placeholder={t('workflow_action_placeholder')} required />
            </label>
            <button className="primary-button" type="submit" disabled={creating || !selectedProvider}>
              {creating ? t('saving') : t('create_workflow')}
            </button>
          </form>
        )}
      </div>

      <div className="panel">
        <h2>{t('workflow_engine')}</h2>
        <div className="list-block">
          {workflows.map((workflow) => {
            const busy = busyWorkflow === workflow.id
            const completed = workflow.status === 'completed'
            const paused = workflow.status === 'paused'
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
                      disabled={busy || !paused}
                      onClick={() => void runAction(workflow.id, () => resumeWorkflow(workflow.id))}
                    >
                      {t('resume')}
                    </button>
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={busy || paused}
                      onClick={() => void runNext(workflow.id)}
                    >
                      {t('run_next')}
                    </button>
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={busy || paused}
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
          {workflows.length === 0 && <div className="muted">{t('no_data')}</div>}
        </div>
      </div>
    </section>
  )
}
