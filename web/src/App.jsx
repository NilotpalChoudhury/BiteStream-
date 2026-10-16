import { useCallback, useEffect, useState } from 'react'
import { Brand, Icon, Notice } from './components/ui'
import EntityPicker from './components/EntityPicker'
import { itemsOf } from './lib/api'
import { useResource } from './lib/hooks'
import { money } from './lib/format'
import Browse from './pages/Browse'
import Checkout from './pages/Checkout'
import Audit from './pages/Audit'
import Analytics from './pages/Analytics'
import Drivers from './pages/Drivers'
import Reviews from './pages/Reviews'
import './App.css'

const navigation = [
  { id: 'browse', name: 'Browse', group: 'Workspace' },
  { id: 'checkout', name: 'Place an order' },
  { id: 'audit', name: 'Wallet audit' },
  { id: 'analytics', name: 'Revenue analytics', group: 'Operations' },
  { id: 'drivers', name: 'Live drivers' },
  { id: 'reviews', name: 'Reviews & menus' },
]
const currentPage = () => navigation.some((n) => n.id === window.location.hash.slice(1)) ? window.location.hash.slice(1) : 'browse'
export default function App() {
  const [page, setPage] = useState(currentPage)
  const [revision, setRevision] = useState(0)
  const [selectedActorId, setActorId] = useState('')
  const [selectedRestaurantId, setRestaurantId] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const [toast, setToast] = useState('')
  const restaurantsResource = useResource('/restaurants?page=1&limit=50')
  const usersResource = useResource('/users?page=1&limit=1')
  const actorId = selectedActorId || itemsOf(usersResource.data)[0]?.id || ''
  const restaurantId = selectedRestaurantId || itemsOf(restaurantsResource.data)[0]?.id || ''
  const userResource = useResource(actorId ? `/users/${actorId}` : null, revision)
  const restaurantResource = useResource(restaurantId ? `/restaurants/${restaurantId}` : null, revision)
  const restaurants = [restaurantResource.data, ...itemsOf(restaurantsResource.data)].filter((row, i, rows) => row && rows.findIndex((other) => other?.id === row.id) === i)
  const update = useCallback((message) => { setRevision((r) => r + 1); if (message) setToast(message) }, [])
  useEffect(() => { const changed = () => { setPage(currentPage()); setMenuOpen(false) }; window.addEventListener('hashchange', changed); return () => window.removeEventListener('hashchange', changed) }, [])
  useEffect(() => { if (!toast) return; const timer = setTimeout(() => setToast(''), 5000); return () => clearTimeout(timer) }, [toast])
  const go = (id, restaurant) => { if (restaurant) setRestaurantId(restaurant); window.location.hash = id; setPage(id); setMenuOpen(false) }
  const shared = { revision, update, actorId, user: userResource.data, userResource, restaurantId, setRestaurantId, restaurants, restaurantsResource, go }
  const Component = { browse: Browse, checkout: Checkout, audit: Audit, analytics: Analytics, drivers: Drivers, reviews: Reviews }[page]
  return <div className="app-shell">
    {menuOpen && <button className="sidebar-overlay" aria-label="Close navigation" onClick={() => setMenuOpen(false)}/>}
    <aside className={`sidebar ${menuOpen ? 'open' : ''}`}>
      <Brand/>
      <nav aria-label="Main navigation">
        {navigation.map((item) => <div key={item.id}>
          {item.group && <div className="nav-group">{item.group}</div>}
          <a href={`#${item.id}`} className={`nav-link ${page === item.id ? 'active' : ''}`} aria-current={page === item.id ? 'page' : undefined}>{item.name}</a>
        </div>)}
      </nav>
    </aside>
    <div className="main-shell">
      <header className="topbar">
        <div className="breadcrumb">
          <button className="mobile-menu icon-button" aria-label="Open navigation" onClick={() => setMenuOpen(true)}><Icon name="menu"/></button>
          <b>{navigation.find((n) => n.id === page)?.name}</b>
        </div>
        <div className="topbar-right">
          <div className="actor-control">
            <div>
              <label htmlFor="actor">Customer</label>
              <EntityPicker entity="users" id="actor" selected={userResource.data} onChange={setActorId} label="Switch customer"/>
            </div>
          </div>
        </div>
      </header>
      <main id="main-content">
        {!actorId && usersResource.error && <Notice type="error">Customers could not be loaded. <button className="text-button" onClick={usersResource.reload}>Retry</button></Notice>}
        {userResource.error && <Notice type="error">The selected customer is unavailable. Choose another customer above or <button className="text-button" onClick={userResource.reload}>retry</button>.</Notice>}
        <Component key={`${page}:${actorId}`} {...shared}/>
      </main>
    </div>
    {toast && <div className="toast" role="status">{toast}<button aria-label="Dismiss notification" onClick={() => setToast('')}><Icon name="close" size={16}/></button></div>}
    <div className="sr-only" aria-live="polite">{userResource.data ? `Current wallet balance ${money(userResource.data.wallet_balance)}` : ''}</div>
  </div>
}
