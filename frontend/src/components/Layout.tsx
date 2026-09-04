import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, Outlet } from 'react-router-dom'

const navItems = [
  { key: 'dashboard', to: '/' },
  { key: 'Providers', to: '/providers' },
  { key: 'workflows', to: '/workflows' },
  { key: 'Recovery Center', to: '/recovery' },
  { key: 'Settings', to: '/settings' },
  { key: 'first_run_wizard', to: '/wizard' },
]

export function Layout() {
  const { t, i18n } = useTranslation()
  const isPersian = i18n.language === 'fa'

  useEffect(() => {
    document.documentElement.lang = i18n.language
    document.documentElement.dir = isPersian ? 'rtl' : 'ltr'
  }, [i18n.language, isPersian])

  const toggleLanguage = () => {
    void i18n.changeLanguage(isPersian ? 'en' : 'fa')
  }

  return (
    <div className="shell" dir={isPersian ? 'rtl' : 'ltr'}>
      <aside className="sidebar">
        <div className="brand-block">
          <div className="brand-mark">A</div>
          <div>
            <div className="brand-name">Atrin</div>
            <div className="brand-subtitle">{t('app_title')}</div>
          </div>
        </div>

        <nav className="nav" aria-label="Main navigation">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `nav-item ${isActive ? 'nav-item-active' : ''}`
              }
            >
              {t(item.key)}
            </NavLink>
          ))}
        </nav>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div>
            <p className="eyebrow">{t('operations')}</p>
            <h1>{t('welcome_message')}</h1>
          </div>
          <div className="topbar-actions">
            <button className="language-toggle" type="button" onClick={toggleLanguage}>
              {t('language_toggle')}: {isPersian ? 'FA' : 'EN'}
            </button>
            <div className="status-pill">{t('system_nominal')}</div>
          </div>
        </header>

        <Outlet />
      </main>
    </div>
  )
}
