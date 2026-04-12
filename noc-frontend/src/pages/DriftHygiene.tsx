/**
 * pages/DriftHygiene.tsx
 * Drift & Hygiene — replaces DriftDashboard.tsx in new dark sidebar design.
 * Shows: topology agent health banner, drift summary counts, type filter chips,
 * drift event cards with source A vs B comparison, Accept/Dismiss/Escalate actions.
 */
import React, { useState, useMemo } from 'react'
import {
  Box, Typography, Chip, Card, CardContent, Button,
  LinearProgress, Snackbar, Tooltip,
} from '@mui/material'
import {
  CheckCircle, Cancel, Launch, AccountTree,
  Circle as DotIcon, Warning,
} from '@mui/icons-material'
import { api } from '../lib/api'
import { mockDriftEvents, mockDriftSummary, mockTopologyStatus } from '../mocks'
import { useApi, usePollingApi } from '../hooks/useApi'
import {
  PageShell, KpiTile, KpiRow, SectionCard, StatusChip,
  MockBanner, LoadingOverlay,
} from '../components/shared'
import { severityColor } from '../lib/theme'
import type { DriftEvent } from '../lib/api'

const DRIFT_TYPE_LABELS: Record<string, string> = {
  MISSING_IN_DCIM:      'Missing in DCIM',
  MISSING_IN_REALITY:   'Missing in Reality',
  POSITION_MISMATCH:    'Position Mismatch',
  ATTRIBUTE_CONFLICT:   'Attribute Conflict',
  CAPACITY_DISCREPANCY: 'Capacity Discrepancy',
  POWER_PATH_MISMATCH:  'Power Path Mismatch',
}
const ALL_TYPES = Object.keys(DRIFT_TYPE_LABELS)

function DriftCard({
  event,
  onAccept,
  onDismiss,
  onEscalate,
}: {
  event: DriftEvent
  onAccept: (id: string) => void
  onDismiss: (id: string) => void
  onEscalate: (id: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const border = severityColor(event.severity)
  const age    = Math.round((Date.now() - new Date(event.detected_at).getTime()) / 60000)
  const ageStr = age < 60 ? `${age}m ago` : `${Math.round(age / 60)}h ago`

  return (
    <Card sx={{ bgcolor: '#111E2D', mb: 1.5, borderLeft: `3px solid ${border}`, transition: 'box-shadow 0.15s', '&:hover': { boxShadow: '0 0 0 1px rgba(8,145,178,0.15)' } }}>
      <CardContent sx={{ p: '12px 14px !important' }}>
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 0.5 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <StatusChip status={event.severity} />
            <Chip label={DRIFT_TYPE_LABELS[event.drift_type] || event.drift_type} size="small"
              sx={{ bgcolor: 'rgba(8,145,178,0.12)', color: '#0891B2', fontSize: '0.62rem', height: 18 }} />
          </Box>
          <Typography sx={{ fontSize: '0.7rem', color: '#64748B', whiteSpace: 'nowrap' }}>{ageStr}</Typography>
        </Box>

        <Typography sx={{ fontSize: '0.82rem', color: '#E2E8F0', mb: 0.25 }}>{event.description}</Typography>
        <Typography sx={{ fontSize: '0.7rem', color: '#64748B', mb: 0.75 }}>
          Entity: {event.affected_entity_id} · Class: {event.affected_entity_class} ·{' '}
          Confidence: {(event.detection_confidence * 100).toFixed(0)}%
        </Typography>

        {/* Source A vs B comparison (collapsible) */}
        <Button size="small" onClick={() => setExpanded(e => !e)}
          sx={{ fontSize: '0.68rem', py: 0, px: 0.5, color: '#64748B', mb: expanded ? 1 : 0 }}>
          {expanded ? 'Hide' : 'Show'} source comparison
        </Button>

        {expanded && (
          <Box sx={{ display: 'flex', gap: 2, mb: 1 }}>
            {[
              { label: 'DCIM (Source A)',      state: event.source_a_state },
              { label: 'Discovered (Source B)', state: event.source_b_state },
            ].map(({ label, state }) => (
              <Box key={label} sx={{ flex: 1, bgcolor: '#0D1B2A', borderRadius: 1.5, p: 1.25, border: '1px solid rgba(255,255,255,0.06)' }}>
                <Typography sx={{ fontSize: '0.68rem', color: '#64748B', mb: 0.5, fontWeight: 600 }}>{label}</Typography>
                {Object.entries(state || {}).map(([k, v]) => (
                  <Box key={k} sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.25 }}>
                    <Typography sx={{ fontSize: '0.68rem', color: '#64748B' }}>{k}</Typography>
                    <Typography sx={{ fontSize: '0.68rem', color: k === event.conflict_field ? '#E05A5A' : '#E2E8F0', fontWeight: k === event.conflict_field ? 700 : 400 }}>
                      {String(v)}
                    </Typography>
                  </Box>
                ))}
              </Box>
            ))}
          </Box>
        )}

        {/* Actions */}
        <Box sx={{ display: 'flex', gap: 0.75 }}>
          <Button size="small" startIcon={<CheckCircle sx={{ fontSize: 13 }} />}
            onClick={() => onAccept(event.drift_id)}
            sx={{ fontSize: '0.68rem', py: 0.25, px: 0.75, color: '#059669', border: '1px solid rgba(5,150,105,0.3)', '&:hover': { bgcolor: 'rgba(5,150,105,0.08)' } }}>
            Accept
          </Button>
          <Button size="small" startIcon={<Cancel sx={{ fontSize: 13 }} />}
            onClick={() => onDismiss(event.drift_id)}
            sx={{ fontSize: '0.68rem', py: 0.25, px: 0.75, color: '#64748B', border: '1px solid rgba(255,255,255,0.08)', '&:hover': { bgcolor: 'rgba(255,255,255,0.04)' } }}>
            Dismiss
          </Button>
          <Button size="small" startIcon={<Launch sx={{ fontSize: 13 }} />}
            onClick={() => onEscalate(event.drift_id)}
            sx={{ fontSize: '0.68rem', py: 0.25, px: 0.75, color: '#F59E0B', border: '1px solid rgba(245,158,11,0.3)', '&:hover': { bgcolor: 'rgba(245,158,11,0.06)' } }}>
            Escalate (ITSM)
          </Button>
        </Box>
      </CardContent>
    </Card>
  )
}

export default function DriftHygiene() {
  const [typeFilter, setTypeFilter] = useState<string>('ALL')
  const [events, setEvents]         = useState<DriftEvent[]>([])
  const [snack, setSnack]           = useState('')

  const { data: summary } = usePollingApi(() => api.drift.summary(), mockDriftSummary, 30000)
  const { data: topoStatus } = useApi(() => api.topology.status(), mockTopologyStatus)
  const { data: eventsData, loading } = usePollingApi(
    () => api.drift.events({ status: 'OPEN', limit: 50 }),
    () => ({ items: mockDriftEvents(), total: 14 }),
    30000,
  )

  React.useEffect(() => {
    if (eventsData) setEvents(eventsData.items)
  }, [eventsData])

  const filtered = useMemo(() =>
    typeFilter === 'ALL' ? events : events.filter(e => e.drift_type === typeFilter),
    [events, typeFilter]
  )

  const handle = (id: string, action: 'ACCEPTED' | 'DISMISSED', label: string) => {
    setEvents(prev => prev.filter(e => e.drift_id !== id))
    setSnack(`Drift event ${label}`)
  }

  const handleEscalate = async (id: string) => {
    try { await api.drift.escalate(id) } catch { /* mock */ }
    setSnack('ITSM ticket created')
  }

  return (
    <PageShell title="Drift & Hygiene" subtitle="Topology reconciliation — open drift events with accept, dismiss, and escalate workflow">
      <MockBanner />

      {/* Topology agent health banner */}
      <Box sx={{ display: 'flex', gap: 3, mb: 2, p: 1.5, bgcolor: '#111E2D', borderRadius: 2, border: '1px solid rgba(255,255,255,0.06)', flexWrap: 'wrap' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
          <DotIcon sx={{ fontSize: 10, color: topoStatus?.consumer_running ? '#059669' : '#E05A5A' }} />
          <Typography sx={{ fontSize: '0.75rem', color: '#94A3B8' }}>Consumer: <span style={{ color: '#E2E8F0', fontWeight: 600 }}>{topoStatus?.consumer_running ? 'Running' : 'Stopped'}</span></Typography>
        </Box>
        <Typography sx={{ fontSize: '0.75rem', color: '#94A3B8' }}>
          DCIM Cache: <span style={{ color: '#E2E8F0', fontWeight: 600 }}>{topoStatus?.dcim_cache_size?.toLocaleString()}</span>
        </Typography>
        <Typography sx={{ fontSize: '0.75rem', color: '#94A3B8' }}>
          Events Generated: <span style={{ color: '#E2E8F0', fontWeight: 600 }}>{topoStatus?.drift_events_generated?.toLocaleString()}</span>
        </Typography>
        {(topoStatus?.errors ?? 0) > 0 && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Warning sx={{ fontSize: 14, color: '#F59E0B' }} />
            <Typography sx={{ fontSize: '0.75rem', color: '#F59E0B' }}>{topoStatus?.errors} errors</Typography>
          </Box>
        )}
      </Box>

      {/* Summary KPIs */}
      <KpiRow>
        <KpiTile label="Total Open"  value={summary?.total_open ?? 0}                color="#0891B2" />
        <KpiTile label="Critical"    value={summary?.by_severity?.CRITICAL ?? 0}     color="#E05A5A" />
        <KpiTile label="Major"       value={summary?.by_severity?.MAJOR ?? 0}        color="#F59E0B" />
        <KpiTile label="Minor"       value={summary?.by_severity?.MINOR ?? 0}        color="#64748B" />
      </KpiRow>

      {/* Type filter chips */}
      <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap' }}>
        {['ALL', ...ALL_TYPES].map(t => (
          <Chip
            key={t}
            label={t === 'ALL' ? `All (${summary?.total_open ?? 0})` : `${DRIFT_TYPE_LABELS[t]} (${summary?.by_type?.[t] ?? 0})`}
            size="small"
            clickable
            onClick={() => setTypeFilter(t)}
            sx={typeFilter === t
              ? { bgcolor: 'rgba(8,145,178,0.2)', color: '#0891B2', fontWeight: 600 }
              : { bgcolor: 'rgba(255,255,255,0.04)', color: '#94A3B8' }}
          />
        ))}
      </Box>

      {/* Event list */}
      {loading ? <LoadingOverlay /> : (
        filtered.length === 0 ? (
          <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', py: 8, gap: 1.5 }}>
            <AccountTree sx={{ fontSize: 40, color: '#64748B' }} />
            <Typography sx={{ fontSize: '0.85rem', color: '#64748B' }}>
              {typeFilter === 'ALL' ? 'No open drift events' : 'No events of this type'}
            </Typography>
          </Box>
        ) : (
          filtered.map(e => (
            <DriftCard
              key={e.drift_id}
              event={e}
              onAccept={id => handle(id, 'ACCEPTED', 'accepted')}
              onDismiss={id => handle(id, 'DISMISSED', 'dismissed')}
              onEscalate={handleEscalate}
            />
          ))
        )
      )}

      <Snackbar open={!!snack} autoHideDuration={3000} onClose={() => setSnack('')}
        message={snack} anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }} />
    </PageShell>
  )
}
