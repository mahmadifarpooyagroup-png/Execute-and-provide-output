import { useTranslation } from 'react-i18next'

export function FirstRunWizardPage() {
  const { t } = useTranslation()
  return (
    <section className="panel wizard-panel">
      <h2>{t('first_run_wizard')}</h2>
      <div className="wizard-card">
        <div className="wizard-step complete">1. {t('connect_providers')}</div>
        <div className="wizard-step complete">2. {t('validate_permissions')}</div>
        <div className="wizard-step active">3. {t('choose_workflow_defaults')}</div>
        <div className="wizard-step">4. {t('launch_control_plane')}</div>
      </div>
      <button type="button" className="primary-button">
        {t('continue_setup')}
      </button>
    </section>
  )
}
