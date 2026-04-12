/**
 * components/layout/Sidebar.tsx
 * Fixed 260px dark sidebar with three collapsible sections:
 * MONITORING, OPERATIONS, CONFIGURATION
 */
import React, { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Box, Typography, List, ListItemButton, ListItemIcon, ListItemText,
  Chip, Collapse, Divider,
} from '@mui/material'
import {
  GridView as DashboardIcon,
  Thermostat as ThermalIcon,
  FlashOn as PowerIcon,
  BarChart as AnalyticsIcon,
  NotificationsNone as AlertsIcon,
  Description as ReportsIcon,
  Hub as ScenarioIcon,
  AccountTree as DriftIcon,
  DeviceHub as ClassIcon,
  Settings as SettingsIcon,
  LinkOutlined as IntegrationsIcon,
  Security as SecurityIcon,
  ExpandLess, ExpandMore,
  Circle as DotIcon,
} from '@mui/icons-material'
import { SIDEBAR_WIDTH } from '../../lib/theme'

interface NavItem {
  label: string
  path: string
  icon: React.ReactNode
  badge?: number
}

interface NavSection {
  id: string
  title: string
  items: NavItem[]
}

interface SidebarProps {
  alertCount?: number
}

const buildSections = (alertCount = 0): NavSection[] => [
  {
    id: 'monitoring',
    title: 'MONITORING',
    items: [
      { label: 'Dashboard',          path: '/',           icon: <DashboardIcon sx={{ fontSize: 18 }} /> },
      { label: 'ThermalFlow',        path: '/thermal',    icon: <ThermalIcon   sx={{ fontSize: 18 }} /> },
      { label: 'PowerFlow',          path: '/power',      icon: <PowerIcon     sx={{ fontSize: 18 }} /> },
      { label: 'Analytics & Insights', path: '/analytics', icon: <AnalyticsIcon sx={{ fontSize: 18 }} /> },
    ],
  },
  {
    id: 'operations',
    title: 'OPERATIONS',
    items: [
      { label: 'Alerts',            path: '/alerts',         icon: <AlertsIcon  sx={{ fontSize: 18 }} />, badge: alertCount || undefined },
      { label: 'Reports',           path: '/reports',        icon: <ReportsIcon sx={{ fontSize: 18 }} /> },
      { label: 'Scenario Planning', path: '/scenarios',      icon: <ScenarioIcon sx={{ fontSize: 18 }} /> },
      { label: 'Drift & Hygiene',   path: '/drift',          icon: <DriftIcon   sx={{ fontSize: 18 }} /> },
      { label: 'Classification',    path: '/classification', icon: <ClassIcon   sx={{ fontSize: 18 }} /> },
    ],
  },
  {
    id: 'configuration',
    title: 'CONFIGURATION',
    items: [
      { label: 'Settings',     path: '/settings',     icon: <SettingsIcon     sx={{ fontSize: 18 }} /> },
      { label: 'Integrations', path: '/integrations', icon: <IntegrationsIcon sx={{ fontSize: 18 }} /> },
      { label: 'Security',     path: '/security',     icon: <SecurityIcon     sx={{ fontSize: 18 }} /> },
    ],
  },
]

export default function Sidebar({ alertCount = 0 }: SidebarProps) {
  const navigate  = useNavigate()
  const location  = useLocation()
  const sections  = buildSections(alertCount)

  const [open, setOpen] = useState<Record<string, boolean>>({
    monitoring: true, operations: true, configuration: true,
  })

  const toggle = (id: string) => setOpen(prev => ({ ...prev, [id]: !prev[id] }))

  const isActive = (path: string) =>
    path === '/' ? location.pathname === '/' : location.pathname.startsWith(path)

  return (
    <Box sx={{
      width: SIDEBAR_WIDTH,
      minWidth: SIDEBAR_WIDTH,
      height: '100vh',
      bgcolor: '#0D1B2A',
      borderRight: '1px solid rgba(255,255,255,0.06)',
      display: 'flex',
      flexDirection: 'column',
      position: 'fixed',
      top: 0,
      left: 0,
      zIndex: 1200,
      overflowY: 'auto',
      '&::-webkit-scrollbar': { width: 4 },
      '&::-webkit-scrollbar-thumb': { bgcolor: 'rgba(255,255,255,0.08)', borderRadius: 2 },
    }}>
      {/* Logo area */}
      <Box sx={{ px: 3, py: 2.5, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <Typography sx={{ fontWeight: 700, fontSize: '1.25rem', color: '#0891B2', letterSpacing: '-0.3px' }}>
          FlowCore
        </Typography>
        <Typography sx={{ fontSize: '0.72rem', color: '#94A3B8', mt: 0.25 }}>
          EU-Compliant Operations
        </Typography>
      </Box>

      {/* Nav sections */}
      <Box sx={{ flex: 1, py: 1 }}>
        {sections.map((section, si) => (
          <Box key={section.id}>
            {si > 0 && <Divider sx={{ borderColor: 'rgba(255,255,255,0.04)', my: 0.5 }} />}

            {/* Section header — clickable to collapse */}
            <Box
              onClick={() => toggle(section.id)}
              sx={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                px: 3, py: 1, cursor: 'pointer',
                '&:hover': { bgcolor: 'rgba(255,255,255,0.02)' },
              }}
            >
              <Typography sx={{
                fontSize: '0.68rem', fontWeight: 600, color: '#94A3B8',
                letterSpacing: '0.8px', userSelect: 'none',
              }}>
                {section.title}
              </Typography>
              {open[section.id]
                ? <ExpandLess sx={{ fontSize: 14, color: '#64748B' }} />
                : <ExpandMore sx={{ fontSize: 14, color: '#64748B' }} />}
            </Box>

            <Collapse in={open[section.id]}>
              <List dense disablePadding>
                {section.items.map(item => {
                  const active = isActive(item.path)
                  return (
                    <ListItemButton
                      key={item.path}
                      onClick={() => navigate(item.path)}
                      sx={{
                        pl: 3, pr: 2, py: 0.75,
                        borderLeft: active
                          ? '3px solid #0891B2'
                          : '3px solid transparent',
                        bgcolor: active
                          ? 'rgba(8,145,178,0.12)'
                          : 'transparent',
                        '&:hover': {
                          bgcolor: active
                            ? 'rgba(8,145,178,0.18)'
                            : 'rgba(255,255,255,0.04)',
                        },
                        borderRadius: 0,
                      }}
                    >
                      <ListItemIcon sx={{
                        minWidth: 32,
                        color: active ? '#0891B2' : '#64748B',
                      }}>
                        {item.icon}
                      </ListItemIcon>
                      <ListItemText
                        primary={item.label}
                        primaryTypographyProps={{
                          fontSize: '0.82rem',
                          fontWeight: active ? 600 : 400,
                          color: active ? '#E2E8F0' : '#94A3B8',
                        }}
                      />
                      {item.badge !== undefined && item.badge > 0 && (
                        <Chip
                          label={item.badge}
                          size="small"
                          sx={{
                            bgcolor: '#E05A5A', color: '#fff',
                            height: 18, fontSize: '0.65rem', fontWeight: 700,
                            '& .MuiChip-label': { px: 0.75 },
                          }}
                        />
                      )}
                    </ListItemButton>
                  )
                })}
              </List>
            </Collapse>
          </Box>
        ))}
      </Box>

      {/* Footer */}
      <Box sx={{ px: 3, py: 1.5, borderTop: '1px solid rgba(255,255,255,0.06)' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <DotIcon sx={{ fontSize: 8, color: '#059669' }} />
          <Typography sx={{ fontSize: '0.7rem', color: '#64748B' }}>
            FlowCore v2.0.0
          </Typography>
        </Box>
      </Box>
    </Box>
  )
}
