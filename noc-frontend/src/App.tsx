/**
 * App.tsx — FlowCore NOC v2
 * New layout: fixed 260px sidebar + 64px top bar + content area.
 * Replaces the old tab-based layout entirely.
 */
import React, { useEffect } from 'react'
import { Routes, Route } from 'react-router-dom'
import { ThemeProvider, CssBaseline } from '@mui/material'
import { ApolloProvider } from '@apollo/client'

import { nocTheme } from './lib/theme'
import { apolloClient } from './lib/apollo'
import { setTenant } from './lib/api'

import Sidebar from './components/layout/Sidebar'
import TopBar  from './components/layout/TopBar'

import Dashboard      from './pages/Dashboard'
import ThermalFlow    from './pages/ThermalFlow'
import PowerFlow      from './pages/PowerFlow'
import Analytics      from './pages/Analytics'
import Alerts         from './pages/Alerts'
import Reports        from './pages/Reports'
import DriftHygiene   from './pages/DriftHygiene'
import Classification from './pages/Classification'
import { ScenarioPlanning, Settings, Integrations, Security } from './pages/stubs'

// Keep RackDetail accessible as a drill-down from the heatmap
import RackDetail from './pages/RackDetail'

const TENANT_ID = import.meta.env.VITE_DEFAULT_TENANT_ID || '25cb8c81-57ed-4d85-9c79-00168e8cb3cc'

// Lightweight hook to read live alert count for sidebar badge + topbar
function useAlertCount(): number {
  const [count, setCount] = React.useState(0)
  useEffect(() => {
    // Initial fetch
    fetch(`/api/alerts?tenant_id=${TENANT_ID}`)
      .then(r => r.json())
      .then(d => setCount(d?.counts?.critical ?? 0))
      .catch(() => setCount(7)) // mock fallback

    // Poll every 60s
    const id = setInterval(() => {
      fetch(`/api/alerts?tenant_id=${TENANT_ID}`)
        .then(r => r.json())
        .then(d => setCount(d?.counts?.critical ?? 0))
        .catch(() => {})
    }, 60000)
    return () => clearInterval(id)
  }, [])
  return count
}

export default function App() {
  // Inject tenant_id into all API calls at startup
  useEffect(() => { setTenant(TENANT_ID) }, [])

  const alertCount = useAlertCount()

  return (
    <ApolloProvider client={apolloClient}>
      <ThemeProvider theme={nocTheme}>
        <CssBaseline />

        {/* Fixed sidebar */}
        <Sidebar alertCount={alertCount} />

        {/* Fixed top bar */}
        <TopBar
          facilityName="FlowCore EU-West Alpha"
          alertCount={alertCount}
          pue={1.43}
        />

        {/* Page content — offset left + top */}
        <Routes>
          <Route path="/"               element={<Dashboard />} />
          <Route path="/thermal"        element={<ThermalFlow />} />
          <Route path="/power"          element={<PowerFlow />} />
          <Route path="/analytics"      element={<Analytics />} />
          <Route path="/alerts"         element={<Alerts />} />
          <Route path="/reports"        element={<Reports />} />
          <Route path="/scenarios"      element={<ScenarioPlanning />} />
          <Route path="/settings"       element={<Settings />} />
          <Route path="/integrations"   element={<Integrations />} />
          <Route path="/security"       element={<Security />} />
          <Route path="/drift"          element={<DriftHygiene />} />
          <Route path="/classification" element={<Classification />} />
          {/* Rack detail — drill-down from heatmap */}
          <Route path="/rack/:entityId" element={<RackDetail tenantId={TENANT_ID} />} />
        </Routes>
      </ThemeProvider>
    </ApolloProvider>
  )
}
