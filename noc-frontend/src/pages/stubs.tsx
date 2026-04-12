/**
 * pages/stubs.tsx
 * Sprint 2 / Sprint 3 pages — fully structured shells with placeholder content.
 * Data models and API endpoints are documented in the migration guide.
 * Replace the stub content blocks with real components per the sprint plan.
 */
import React from 'react'
import { Box, Typography, Button, Chip } from '@mui/material'
import {
  Hub, Settings as SettingsIcon, LinkOutlined, Security as SecurityIcon,
  Construction,
} from '@mui/icons-material'
import { PageShell, MockBanner } from '../components/shared'

function ComingSoon({ icon, title, description, sprint }: {
  icon: React.ReactNode
  title: string
  description: string
  sprint: string
}) {
  return (
    <PageShell title={title}>
      <MockBanner />
      <Box sx={{
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', minHeight: 400, gap: 2, textAlign: 'center',
      }}>
        <Box sx={{ color: '#1E3A4A', fontSize: 64 }}>{icon}</Box>
        <Typography sx={{ fontSize: '1.1rem', fontWeight: 600, color: '#E2E8F0' }}>{title}</Typography>
        <Typography sx={{ fontSize: '0.82rem', color: '#64748B', maxWidth: 420 }}>{description}</Typography>
        <Chip
          icon={<Construction sx={{ fontSize: '14px !important' }} />}
          label={`Planned: ${sprint}`}
          sx={{ bgcolor: 'rgba(167,139,250,0.12)', color: '#A78BFA', fontWeight: 600 }}
        />
      </Box>
    </PageShell>
  )
}

export function ScenarioPlanning() {
  return (
    <ComingSoon
      icon={<Hub sx={{ fontSize: 'inherit' }} />}
      title="Scenario Planning"
      description="Run what-if simulations for rack failures, capacity expansion, and network topology changes. Results visualised as a Cytoscape.js graph overlay with impact tables."
      sprint="Frontend Sprint 3"
    />
  )
}

export function Settings() {
  return (
    <ComingSoon
      icon={<SettingsIcon sx={{ fontSize: 'inherit' }} />}
      title="Settings"
      description="Configure POC period dates, PUE targets, energy tariff rates, peak hour windows, alerting thresholds, and other platform-level settings stored in platform_config."
      sprint="Frontend Sprint 2"
    />
  )
}

export function Integrations() {
  return (
    <ComingSoon
      icon={<LinkOutlined sx={{ fontSize: 'inherit' }} />}
      title="Integrations"
      description="Configure ServiceNow, Jira, PagerDuty, and webhook integrations for alert escalation and ITSM ticket creation. Maps to itsm_integration_config table."
      sprint="Frontend Sprint 2"
    />
  )
}

export function Security() {
  return (
    <ComingSoon
      icon={<SecurityIcon sx={{ fontSize: 'inherit' }} />}
      title="Security"
      description="User management, RBAC role assignments, and audit log viewer. Maps to the user table and audit_log_entry hypertable in TimescaleDB."
      sprint="Frontend Sprint 2"
    />
  )
}
