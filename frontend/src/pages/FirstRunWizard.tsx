import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { markWizardComplete } from '../services/wizardState'

type StepId = 'connect' | 'validate' | 'defaults' | 'launch'

interface WizardStep {
  id: StepId
  labelKey: string
}

const STEPS: WizardStep[] = [
  { id: 'connect', labelKey: 'connect_providers' },
  { id: 'validate', labelKey: 'validate_permissions' },
  { id: 'defaults', labelKey: 'choose_workflow_defaults' },
  { id: 'launch', labelKey: 'launch_control_plane' },
]

export function FirstRunWizardPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [activeIndex, setActiveIndex] = useState(0)

  const isLastStep = activeIndex === STEPS.length - 1

  function handleContinue() {
    if (isLastStep) {
      if (markWizardComplete()) {
        navigate('/dashboard', { replace: true })
      }
      return
    }

    setActiveIndex((prev) => Math.min(prev + 1, STEPS.length - 1))
  }

  return (
    <section className="panel wizard-panel">
      <h2>{t('first_run_wizard')}</h2>
      <div className="wizard-card">
        {STEPS.map((step, index) => {
          const className =
            index < activeIndex
              ? 'wizard-step complete'
              : index === activeIndex
                ? 'wizard-step active'
                : 'wizard-step'

          return (
            <div key={step.id} className={className} aria-current={index === activeIndex ? 'step' : undefined}>
              {index + 1}. {t(step.labelKey)}
            </div>
          )
        })}
      </div>
      <button
        type="button"
        className="primary-button"
        onClick={handleContinue}
        data-testid="wizard-continue"
      >
        {isLastStep ? t('launch_control_plane') : t('continue_setup')}
      </button>
    </section>
  )
}
