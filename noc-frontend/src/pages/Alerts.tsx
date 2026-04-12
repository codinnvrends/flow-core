/**
 * pages/Alerts.tsx
 * Screens 5, 5.1 — Critical/Warning/Info/Resolved counts, search, tab filter,
 * alert cards with Acknowledge / Resolve / View Details actions.
 */
import React, { useState, useMemo } from 'react'
import {
  Box, Typography, Chip, TextField, InputAdornment, Button,
  Tabs, Tab, Card, CardContent, IconButton, Tooltip, Snackbar,
  Dialog, DialogTitle, DialogContent, DialogActions,
} from '@mui/material'
import {
  Search, CheckCircle, Cancel, Info, Visibility,
  NotificationsNone,
} from '@mui/icons-material'
import { api } from '../lib/api'
import { mockAlerts } from '../mocks'
import { usePollingApi } from '../hooks/useApi'
import {
  PageShell, KpiTile, KpiRow, SectionCard, StatusChip,
  MockBanner, LoadingOverlay, ErrorAlert,
} from '../components/shared'
import { severityColor } from '../lib/theme'
import type { AlertItem } from '../lib/api'

const TABS = ['All', 'Active', 'Critical', 'Warnings', 'Resolved']

function AlertCard({
  alert,
  onAcknowledge,
  onResolve,
}: {
  alert: AlertItem
  onAcknowledge: (id: string) => void
  onResolve: (id: string) => void
}) {
  const [detailOpen, setDetailOpen] = useState(false)
  const border = severityColor(alert.severity)
  const age    = Math.round((Date.now() - new Date(alert.event_ts).getTime()) / 60000)
  const ageStr = age < 60 ? `${age}m ago` : `${Math.round(age / 60)}h ago`

  return (
    <>
      <Card sx={{
        bgcolor: '#111E2D',
        mb: 1.5,
        borderLeft: `3px solid ${border}`,
        transition: 'box-shadow 0.15s',
        '&:hover': { boxShadow: '0 0 0 1px rgba(8,145,178,0.2)' },
      }}>
        <CardContent sx={{ p: '12px !important' }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 0.5 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <StatusChip status={alert.severity} />
              <Typography sx={{ fontSize: '0.85rem', fontWeight: 600, color: '#E2E8F0' }}>
                {alert.title}
              </Typography>
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography sx={{ fontSize: '0.7rem', color: '#64748B', whiteSpace: 'nowrap' }}>{ageStr}</Typography>
              <StatusChip status={alert.status} />
            </Box>
          </Box>

          <Typography sx={{ fontSize: '0.75rem', color: '#64748B', mb: 0.75 }}>
            {alert.zone} · {alert.device} · {alert.description}
          </Typography>

          <Box sx={{ display: 'flex', gap: 1, mt: 0.5 }}>
            {alert.status === 'ACTIVE' && (
              <>
                <Button
                  size="small"
                  startIcon={<CheckCircle sx={{ fontSize: 13 }} />}
                  onClick={() => onAcknowledge(alert.alert_id)}
                  sx={{ fontSize: '0.7rem', py: 0.25, px: 1, color: '#F59E0B', border: '1px solid rgba(245,158,11,0.3)', '&:hover': { bgcolor: 'rgba(245,158,11,0.08)' } }}
                >
                  Acknowledge
                </Button>
                <Button
                  size="small"
                  startIcon={<Cancel sx={{ fontSize: 13 }} />}
                  onClick={() => onResolve(alert.alert_id)}
                  sx={{ fontSize: '0.7rem', py: 0.25, px: 1, color: '#059669', border: '1px solid rgba(5,150,105,0.3)', '&:hover': { bgcolor: 'rgba(5,150,105,0.08)' } }}
                >
                  Resolve
                </Button>
              </>
            )}
            <Button
              size="small"
              startIcon={<Visibility sx={{ fontSize: 13 }} />}
              onClick={() => setDetailOpen(true)}
              sx={{ fontSize: '0.7rem', py: 0.25, px: 1, color: '#64748B', border: '1px solid rgba(255,255,255,0.08)', '&:hover': { bgcolor: 'rgba(255,255,255,0.04)' } }}
            >
              View Details
            </Button>
          </Box>
        </CardContent>
      </Card>

      {/* Detail Dialog */}
      <Dialog open={detailOpen} onClose={() => setDetailOpen(false)} maxWidth="sm" fullWidth
        PaperProps={{ sx: { bgcolor: '#111E2D', border: '1px solid rgba(255,255,255,0.08)' } }}>
        <DialogTitle sx={{ color: '#E2E8F0', fontSize: '0.95rem', pb: 1 }}>
          Alert Detail — {alert.title}
        </DialogTitle>
        <DialogContent>
          {[
            ['ID',          alert.alert_id],
            ['Severity',    alert.severity],
            ['Status',      alert.status],
            ['Zone',        alert.zone],
            ['Device',      alert.device],
            ['Description', alert.description],
            ['Detected',    new Date(alert.event_ts).toLocaleString()],
          ].map(([k, v]) => (
            <Box key={k as string} sx={{ display: 'flex', gap: 2, py: 0.75, borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
              <Typography sx={{ width: 100, fontSize: '0.75rem', color: '#64748B', flexShrink: 0 }}>{k}</Typography>
              <Typography sx={{ fontSize: '0.75rem', color: '#E2E8F0' }}>{v}</Typography>
            </Box>
          ))}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDetailOpen(false)} sx={{ color: '#94A3B8', fontSize: '0.78rem' }}>Close</Button>
        </DialogActions>
      </Dialog>
    </>
  )
}

export default function Alerts() {
  const [search,  setSearch]  = useState('')
  const [tabIdx,  setTabIdx]  = useState(0)
  const [snack,   setSnack]   = useState('')
  const [alerts,  setAlerts]  = useState<AlertItem[]>([])
  const [counts,  setCounts]  = useState({ critical: 0, warning: 0, info: 0, resolved_today: 0 })
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState<string | null>(null)

  const { data, loading: ld, error: le } = usePollingApi(
    () => api.alerts.list(),
    mockAlerts,
    30000,
  )

  React.useEffect(() => {
    if (data) {
      setAlerts(data.items)
      setCounts(data.counts)
    }
    setLoading(ld)
    setError(le)
  }, [data, ld, le])

  const handleAck = async (id: string) => {
    try { await api.alerts.acknowledge(id) } catch { /* mock */ }
    setAlerts(prev => prev.map(a => a.alert_id === id ? { ...a, status: 'ACKNOWLEDGED' as const } : a))
    setSnack('Alert acknowledged')
  }

  const handleResolve = async (id: string) => {
    try { await api.alerts.resolve(id) } catch { /* mock */ }
    setAlerts(prev => prev.map(a => a.alert_id === id ? { ...a, status: 'RESOLVED' as const } : a))
    setSnack('Alert resolved')
  }

  const filtered = useMemo(() => {
    let list = alerts
    if (search) list = list.filter(a =>
      a.title.toLowerCase().includes(search.toLowerCase()) ||
      a.zone.toLowerCase().includes(search.toLowerCase()) ||
      a.device.toLowerCase().includes(search.toLowerCase())
    )
    if (tabIdx === 1) list = list.filter(a => a.status === 'ACTIVE')
    if (tabIdx === 2) list = list.filter(a => a.severity === 'CRITICAL')
    if (tabIdx === 3) list = list.filter(a => a.severity === 'WARNING')
    if (tabIdx === 4) list = list.filter(a => a.status === 'RESOLVED')
    return list
  }, [alerts, search, tabIdx])

  return (
    <PageShell title="Alerts & Notifications" subtitle="Real-time alert management with acknowledge and resolve workflows">
      <MockBanner />
      {le && <ErrorAlert message={le} />}

      {/* Count KPIs */}
      <KpiRow>
        <KpiTile label="Critical"      value={counts.critical}      color="#E05A5A" />
        <KpiTile label="Warnings"      value={counts.warning}       color="#F59E0B" />
        <KpiTile label="Info"          value={counts.info}          color="#0891B2" />
        <KpiTile label="Resolved Today" value={counts.resolved_today} color="#059669" />
      </KpiRow>

      {/* Search + tabs */}
      <Box sx={{ display: 'flex', gap: 2, mb: 2, alignItems: 'center', flexWrap: 'wrap' }}>
        <TextField
          placeholder="Search alerts…"
          size="small"
          value={search}
          onChange={e => setSearch(e.target.value)}
          InputProps={{
            startAdornment: <InputAdornment position="start"><Search sx={{ fontSize: 16, color: '#64748B' }} /></InputAdornment>,
            sx: { bgcolor: '#111E2D', borderRadius: 2, fontSize: '0.8rem', '& fieldset': { borderColor: 'rgba(255,255,255,0.08)' } },
          }}
          sx={{ width: 280 }}
        />
        <Tabs
          value={tabIdx}
          onChange={(_, v) => setTabIdx(v)}
          sx={{
            '& .MuiTab-root': { fontSize: '0.75rem', minHeight: 36, py: 0, textTransform: 'none', color: '#64748B' },
            '& .Mui-selected': { color: '#0891B2' },
            '& .MuiTabs-indicator': { bgcolor: '#0891B2', height: 2 },
          }}
        >
          {TABS.map(t => <Tab key={t} label={t} />)}
        </Tabs>
        <Box sx={{ ml: 'auto' }}>
          <Chip label={`${filtered.length} alerts`} size="small" sx={{ bgcolor: 'rgba(8,145,178,0.12)', color: '#0891B2' }} />
        </Box>
      </Box>

      {/* Alert list */}
      {loading ? <LoadingOverlay /> : (
        filtered.length === 0 ? (
          <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', py: 8, gap: 1.5, color: '#64748B' }}>
            <NotificationsNone sx={{ fontSize: 40 }} />
            <Typography sx={{ fontSize: '0.85rem' }}>No alerts match your filters</Typography>
          </Box>
        ) : (
          <Box>
            {filtered.map(a => (
              <AlertCard
                key={a.alert_id}
                alert={a}
                onAcknowledge={handleAck}
                onResolve={handleResolve}
              />
            ))}
          </Box>
        )
      )}

      <Snackbar open={!!snack} autoHideDuration={3000} onClose={() => setSnack('')}
        message={snack} anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }} />
    </PageShell>
  )
}
