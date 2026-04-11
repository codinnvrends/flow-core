import React, { useState } from 'react'
import { Routes, Route, Link, useLocation } from 'react-router-dom'
import {
  Box, AppBar, Toolbar, Typography, Tabs, Tab, Chip,
  IconButton, Tooltip, CircularProgress,
} from '@mui/material'
import {
  GridView as GridIcon,
  BugReport as DriftIcon,
  DeviceHub as ClassIcon,
  Refresh as RefreshIcon,
} from '@mui/icons-material'
import RackHealthGrid from './pages/RackHealthGrid'
import RackDetail from './pages/RackDetail'
import DriftDashboard from './pages/DriftDashboard'
import ClassificationReview from './pages/ClassificationReview'

const TENANT_ID = import.meta.env.VITE_DEFAULT_TENANT_ID || '48041f5f-cba7-466e-807a-b2fe85bd20ae'

const NAV_TABS = [
  { path: '/',              label: 'Rack Health',   icon: <GridIcon fontSize="small" /> },
  { path: '/drift',         label: 'Drift & Hygiene', icon: <DriftIcon fontSize="small" /> },
  { path: '/classification', label: 'Classification', icon: <ClassIcon fontSize="small" /> },
]

export default function App() {
  const location = useLocation()
  const activeTab = NAV_TABS.findIndex(t =>
    t.path === '/' ? location.pathname === '/' : location.pathname.startsWith(t.path)
  )

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100vh', bgcolor: 'background.default' }}>
      {/* ── Top bar ── */}
      <AppBar position="static" elevation={0}
              sx={{ bgcolor: '#0D1B2A', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <Toolbar variant="dense" sx={{ gap: 2 }}>
          {/* Logo */}
          <Typography variant="h4" sx={{ fontWeight: 700, color: '#0891B2', mr: 1, letterSpacing: '-0.5px' }}>
            FlowCore
          </Typography>
          <Chip label="NOC" size="small"
                sx={{ bgcolor: 'rgba(8,145,178,0.15)', color: '#0891B2', fontWeight: 700, fontSize: '0.65rem' }} />
          <Box sx={{ flex: 1 }} />
          <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.7rem' }}>
            Tenant: {TENANT_ID.slice(0, 8)}…
          </Typography>
          <Chip label="LIVE" size="small"
                sx={{ bgcolor: 'rgba(5,150,105,0.2)', color: '#059669', fontSize: '0.65rem', fontWeight: 700,
                      animation: 'pulse 2s infinite',
                      '@keyframes pulse': { '0%,100%': { opacity: 1 }, '50%': { opacity: 0.6 } } }} />
        </Toolbar>

        {/* Nav tabs */}
        <Tabs value={activeTab >= 0 ? activeTab : 0}
              sx={{ px: 2, minHeight: 40,
                    '& .MuiTab-root': { minHeight: 40, fontSize: '0.78rem', py: 0 },
                    '& .MuiTabs-indicator': { bgcolor: '#0891B2', height: 2 } }}>
          {NAV_TABS.map((tab) => (
            <Tab key={tab.path}
                 component={Link} to={tab.path}
                 icon={tab.icon} iconPosition="start"
                 label={tab.label} />
          ))}
        </Tabs>
      </AppBar>

      {/* ── Page content ── */}
      <Box sx={{ flex: 1, overflow: 'auto' }}>
        <Routes>
          <Route path="/"                element={<RackHealthGrid tenantId={TENANT_ID} />} />
          <Route path="/rack/:entityId"  element={<RackDetail tenantId={TENANT_ID} />} />
          <Route path="/drift"           element={<DriftDashboard tenantId={TENANT_ID} />} />
          <Route path="/classification"  element={<ClassificationReview tenantId={TENANT_ID} />} />
        </Routes>
      </Box>

      {/* ── Status bar ── */}
      <Box sx={{ px: 2, py: 0.5, borderTop: '1px solid rgba(255,255,255,0.05)',
                 display: 'flex', gap: 2, alignItems: 'center' }}>
        <Typography variant="caption">FlowCore v1.0.0</Typography>
        <Box sx={{ flex: 1 }} />
        <Typography variant="caption" sx={{ color: 'text.secondary' }}>
          {new Date().toISOString().slice(0, 19).replace('T', ' ')} UTC
        </Typography>
      </Box>
    </Box>
  )
}
