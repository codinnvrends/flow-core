import React, { useState } from 'react'
import {
  Box, Typography, Chip, Card, CardContent, Table, TableBody,
  TableCell, TableHead, TableRow, Select, MenuItem, FormControl,
  InputLabel, TextField, Button, Alert, CircularProgress, Tooltip,
  Dialog, DialogTitle, DialogContent, DialogActions,
} from '@mui/material'
import { BugReport as DriftIcon, CheckCircle, Cancel, Launch } from '@mui/icons-material'
import { severityColor } from '../lib/theme'
import axios from 'axios'

const INSIGHTS_BASE = import.meta.env.VITE_INSIGHTS_API_URL || 'http://localhost:8888/api/insights'

interface DriftEvent {
  drift_id: string
  tenant_id: string
  drift_type: string
  severity: string
  affected_entity_id: string
  affected_entity_class: string
  source_a_id: string
  source_b_id: string
  conflict_field: string | null
  description: string
  detection_confidence: number
  status: string
  agent_version: string
  detected_at: string
  resolved_at: string | null
  itsm_ticket_ref: string | null
}

const DRIFT_TYPE_LABELS: Record<string, string> = {
  MISSING_IN_DCIM:      'Missing in DCIM',
  MISSING_IN_REALITY:   'Missing in reality',
  POSITION_MISMATCH:    'Position mismatch',
  ATTRIBUTE_CONFLICT:   'Attribute conflict',
  CAPACITY_DISCREPANCY: 'Capacity discrepancy',
  POWER_PATH_MISMATCH:  'Power path mismatch',
}

function useDriftEvents(tenantId: string, status: string, severity: string) {
  const [events, setEvents] = useState<DriftEvent[]>([])
  const [total, setTotal]   = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError]   = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const params: any = { tenant_id: tenantId, limit: 100 }
      if (status !== 'ALL') params.status = status
      if (severity !== 'ALL') params.severity = severity
      const r = await axios.get(`${INSIGHTS_BASE}/drift/events`, { params })
      setEvents(r.data.items || [])
      setTotal(r.data.total || 0)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  React.useEffect(() => { load() }, [tenantId, status, severity])

  return { events, total, loading, error, reload: load }
}

function useSummary(tenantId: string) {
  const [summary, setSummary] = useState<any[]>([])
  React.useEffect(() => {
    axios.get(`${INSIGHTS_BASE}/drift/summary`, { params: { tenant_id: tenantId } })
      .then(r => setSummary(r.data))
      .catch(() => {})
  }, [tenantId])
  return summary
}

function SeverityBadge({ sev }: { sev: string }) {
  return (
    <Chip label={sev} size="small"
      sx={{ bgcolor: `${severityColor(sev)}22`, color: severityColor(sev),
            fontWeight: 700, fontSize: '0.65rem', height: 18 }} />
  )
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    OPEN: '#0891B2', ACCEPTED: '#059669', DISMISSED: '#64748B',
    RESOLVED: '#64748B', ESCALATED: '#F59E0B',
  }
  return (
    <Chip label={status} size="small"
      sx={{ bgcolor: `${colors[status] || '#64748B'}22`, color: colors[status] || '#64748B',
            fontSize: '0.65rem', height: 18 }} />
  )
}

export default function DriftDashboard({ tenantId }: { tenantId: string }) {
  const [statusFilter,   setStatusFilter]   = useState('OPEN')
  const [severityFilter, setSeverityFilter] = useState('ALL')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<DriftEvent | null>(null)
  const [updating, setUpdating] = useState(false)

  const { events, total, loading, error, reload } = useDriftEvents(tenantId, statusFilter, severityFilter)
  const summary = useSummary(tenantId)

  const filtered = search
    ? events.filter(e =>
        e.description.toLowerCase().includes(search.toLowerCase()) ||
        e.drift_type.toLowerCase().includes(search.toLowerCase()))
    : events

  const updateStatus = async (driftId: string, status: string) => {
    setUpdating(true)
    try {
      await axios.patch(`${INSIGHTS_BASE}/drift/events/${driftId}`,
        null, { params: { status, operator_decision: status } })
      reload()
      setSelected(null)
    } catch (e: any) {
      console.error(e)
    } finally {
      setUpdating(false)
    }
  }

  // Summary by type
  const byType: Record<string, number> = {}
  summary.forEach(r => {
    byType[r.drift_type] = (byType[r.drift_type] || 0) + Number(r.count)
  })
  const openBySev: Record<string, number> = {}
  summary.filter(r => r.status === 'OPEN').forEach(r => {
    openBySev[r.severity] = (openBySev[r.severity] || 0) + Number(r.count)
  })

  return (
    <Box sx={{ p: 2 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
        <DriftIcon sx={{ color: '#F59E0B' }} />
        <Typography variant="h2">Drift & Hygiene Dashboard</Typography>
      </Box>

      {/* Summary cards */}
      <Box sx={{ display: 'flex', gap: 1.5, mb: 2, flexWrap: 'wrap' }}>
        {['CRITICAL', 'MAJOR', 'MINOR'].map(sev => (
          <Card key={sev} sx={{ minWidth: 120, borderLeft: `3px solid ${severityColor(sev)}` }}>
            <CardContent sx={{ p: '12px!important', textAlign: 'center' }}>
              <Typography variant="h2" sx={{ color: severityColor(sev) }}>
                {openBySev[sev] || 0}
              </Typography>
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                Open {sev.toLowerCase()}
              </Typography>
            </CardContent>
          </Card>
        ))}
        {Object.entries(byType).slice(0, 3).map(([type, count]) => (
          <Card key={type} sx={{ minWidth: 140 }}>
            <CardContent sx={{ p: '12px!important', textAlign: 'center' }}>
              <Typography variant="h3">{count}</Typography>
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                {DRIFT_TYPE_LABELS[type] || type}
              </Typography>
            </CardContent>
          </Card>
        ))}
      </Box>

      {/* Filters */}
      <Box sx={{ display: 'flex', gap: 1.5, mb: 2, flexWrap: 'wrap', alignItems: 'center' }}>
        <FormControl size="small" sx={{ minWidth: 130 }}>
          <InputLabel>Status</InputLabel>
          <Select value={statusFilter} label="Status" onChange={e => setStatusFilter(e.target.value)}>
            <MenuItem value="ALL">All</MenuItem>
            <MenuItem value="OPEN">Open</MenuItem>
            <MenuItem value="ACCEPTED">Accepted</MenuItem>
            <MenuItem value="DISMISSED">Dismissed</MenuItem>
            <MenuItem value="RESOLVED">Resolved</MenuItem>
            <MenuItem value="ESCALATED">Escalated</MenuItem>
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 130 }}>
          <InputLabel>Severity</InputLabel>
          <Select value={severityFilter} label="Severity" onChange={e => setSeverityFilter(e.target.value)}>
            <MenuItem value="ALL">All</MenuItem>
            <MenuItem value="CRITICAL">Critical</MenuItem>
            <MenuItem value="MAJOR">Major</MenuItem>
            <MenuItem value="MINOR">Minor</MenuItem>
          </Select>
        </FormControl>
        <TextField placeholder="Search…" size="small" value={search}
          onChange={e => setSearch(e.target.value)} sx={{ minWidth: 200 }} />
        <Typography variant="caption" sx={{ color: 'text.secondary', ml: 'auto' }}>
          {loading ? 'Loading…' : `${filtered.length} of ${total}`}
        </Typography>
      </Box>

      {/* Error */}
      {error && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Could not load drift events from insights-api ({error}).
          Make sure the insights-api service is running.
        </Alert>
      )}

      {/* Table */}
      <Card>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Severity</TableCell>
              <TableCell>Type</TableCell>
              <TableCell>Description</TableCell>
              <TableCell>Entity</TableCell>
              <TableCell>Confidence</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Detected</TableCell>
              <TableCell>Ticket</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={9} align="center" sx={{ py: 4 }}>
                  <CircularProgress size={24} />
                </TableCell>
              </TableRow>
            ) : filtered.length === 0 ? (
              <TableRow>
                <TableCell colSpan={9} align="center" sx={{ py: 3 }}>
                  <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                    No drift events found
                  </Typography>
                </TableCell>
              </TableRow>
            ) : filtered.map(ev => (
              <TableRow key={ev.drift_id}
                sx={{ cursor: 'pointer', '&:hover': { bgcolor: 'rgba(255,255,255,0.02)' } }}
                onClick={() => setSelected(ev)}>
                <TableCell><SeverityBadge sev={ev.severity} /></TableCell>
                <TableCell>
                  <Typography variant="caption">
                    {DRIFT_TYPE_LABELS[ev.drift_type] || ev.drift_type}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Tooltip title={ev.description}>
                    <Typography variant="caption" noWrap sx={{ maxWidth: 200, display: 'block' }}>
                      {ev.description}
                    </Typography>
                  </Tooltip>
                </TableCell>
                <TableCell>
                  <Typography variant="caption" sx={{ fontFamily: 'monospace', fontSize: '0.68rem' }}>
                    {ev.affected_entity_id.slice(0, 8)}…
                  </Typography>
                </TableCell>
                <TableCell>
                  <Typography variant="caption"
                    sx={{ color: ev.detection_confidence >= 0.9 ? '#059669' : '#F59E0B' }}>
                    {(ev.detection_confidence * 100).toFixed(0)}%
                  </Typography>
                </TableCell>
                <TableCell><StatusBadge status={ev.status} /></TableCell>
                <TableCell>
                  <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                    {new Date(ev.detected_at).toLocaleString()}
                  </Typography>
                </TableCell>
                <TableCell>
                  {ev.itsm_ticket_ref && (
                    <Chip label={ev.itsm_ticket_ref} size="small"
                      sx={{ fontSize: '0.6rem', height: 16, bgcolor: 'rgba(255,255,255,0.06)' }} />
                  )}
                </TableCell>
                <TableCell align="right" onClick={e => e.stopPropagation()}>
                  {ev.status === 'OPEN' && (
                    <Box sx={{ display: 'flex', gap: 0.5, justifyContent: 'flex-end' }}>
                      <Tooltip title="Accept">
                        <Button size="small" sx={{ minWidth: 0, p: 0.5, color: '#059669' }}
                          disabled={updating}
                          onClick={() => updateStatus(ev.drift_id, 'ACCEPTED')}>
                          <CheckCircle fontSize="small" />
                        </Button>
                      </Tooltip>
                      <Tooltip title="Dismiss">
                        <Button size="small" sx={{ minWidth: 0, p: 0.5, color: '#64748B' }}
                          disabled={updating}
                          onClick={() => updateStatus(ev.drift_id, 'DISMISSED')}>
                          <Cancel fontSize="small" />
                        </Button>
                      </Tooltip>
                    </Box>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      {/* Detail dialog */}
      <Dialog open={!!selected} onClose={() => setSelected(null)} maxWidth="sm" fullWidth>
        {selected && (
          <>
            <DialogTitle>
              <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                <SeverityBadge sev={selected.severity} />
                {DRIFT_TYPE_LABELS[selected.drift_type] || selected.drift_type}
              </Box>
            </DialogTitle>
            <DialogContent>
              <Typography variant="body2" sx={{ mb: 1.5 }}>{selected.description}</Typography>
              {[
                ['Drift ID',        selected.drift_id],
                ['Entity ID',       selected.affected_entity_id],
                ['Entity class',    selected.affected_entity_class],
                ['Conflict field',  selected.conflict_field ?? '—'],
                ['Confidence',      `${(selected.detection_confidence * 100).toFixed(0)}%`],
                ['Agent',           selected.agent_version],
                ['Detected',        new Date(selected.detected_at).toLocaleString()],
                ['ITSM ticket',     selected.itsm_ticket_ref ?? '—'],
              ].map(([k, v]) => (
                <Box key={k} sx={{ display: 'flex', gap: 2, py: 0.5,
                                    borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                  <Typography variant="caption" sx={{ color: 'text.secondary', minWidth: 120 }}>
                    {k}
                  </Typography>
                  <Typography variant="caption" fontWeight={500}
                    sx={{ fontFamily: k.includes('ID') ? 'monospace' : 'inherit', fontSize: '0.72rem' }}>
                    {v}
                  </Typography>
                </Box>
              ))}
            </DialogContent>
            <DialogActions>
              {selected.status === 'OPEN' && (
                <>
                  <Button color="success" disabled={updating}
                    onClick={() => updateStatus(selected.drift_id, 'ACCEPTED')}>
                    Accept
                  </Button>
                  <Button color="warning" disabled={updating}
                    onClick={() => updateStatus(selected.drift_id, 'DISMISSED')}>
                    Dismiss
                  </Button>
                  <Button color="error" disabled={updating}
                    onClick={() => updateStatus(selected.drift_id, 'ESCALATED')}>
                    Escalate
                  </Button>
                </>
              )}
              <Button onClick={() => setSelected(null)}>Close</Button>
            </DialogActions>
          </>
        )}
      </Dialog>
    </Box>
  )
}
