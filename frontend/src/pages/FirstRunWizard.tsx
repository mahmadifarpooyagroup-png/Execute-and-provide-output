export function FirstRunWizardPage() {
  return (
    <section className="panel wizard-panel">
      <h2>First run wizard</h2>
      <div className="wizard-card">
        <div className="wizard-step complete">1. Connect providers</div>
        <div className="wizard-step complete">2. Validate permissions</div>
        <div className="wizard-step active">3. Choose workflow defaults</div>
        <div className="wizard-step">4. Launch control plane</div>
      </div>
      <button type="button" className="primary-button">
        Continue setup
      </button>
    </section>
  )
}
