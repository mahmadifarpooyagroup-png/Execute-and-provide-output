import { NavLink, Outlet } from 'react-router-dom'

const navItems = [
  { label: 'Dashboard', to: '/' },
  { label: 'Providers', to: '/providers' },
  { label: 'Workflows', to: '/workflows' },
  { label: 'Recovery Center', to: '/recovery' },
  { label: 'Settings', to: '/settings' },
  { label: 'First Run Wizard', to: '/wizard' },
]

export function Layout() {
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand-block">
          <div className="brand-mark">A</div>
          <div>
            <div className="brand-name">Atrin</div>
            <div className="brand-subtitle">Control Plane</div>
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
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div>
            <p className="eyebrow">Operations</p>
            <h1>Atrin orchestration</h1>
          </div>
          <div className="status-pill">System nominal</div>
        </header>

        <Outlet />
      </main>
    </div>
  )
}
