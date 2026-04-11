import React, { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { gql, useSubscription, useQuery } from '@apollo/client'
import {
  Box, Grid, Card, CardContent, Typography, Chip, TextField,
  Select, MenuItem, FormControl, InputLabel, CircularProgress,
  Alert, Tooltip, LinearProgress, Skeleton,
} from '@mui/material'
import {
  Memory as RackIcon,
  Warning as WarnIcon,
  CheckCircle as OkIcon,
  Error as ErrIcon,
  HelpOutline as UnknownIcon,
} from '@mui/icons-material'
import { healthColor, severityColor } from '../lib/theme'

// ── GraphQL ───────────────────────────────────────────────────────────────────

const RACK_HEALTH_QUERY = gql`
  query RackHealthCards($tenantId: String!, $limit: Int) {
    rackHealthCards(tenantId: $tenantId, limit: $limit) {
      entityId canonicalName tenantId operationalStatus
      healthScore activeAlertCount criticalityLevel redundancyPosture
      powerDrawW inletTempC deviceCount
    }
  }
`

const RACK_HEALTH_SUB = gql`
  subscription RackHealthUpdates($tenantId: String!) {
    rackHealthUpdates(tenantId: $tenantId) {
      entityId canonicalName tenantId operationalStatus
      healthScore activeAlertCount criticalityLevel redundancyPosture
      powerDrawW inletTempC deviceCount
    }
  }
`

// ── Types ─────────────────────────────────────────────────────────────────────

interface RackCard {
  entityId: string
  canonicalName: string
  operationalStatus: string
  healthScore: number
  activeAlertCount: number
  criticalityLevel?: string
  redundancyPosture?: string
  powerDrawW?: number
  inletTempC?: number
  deviceCount: number
}

// ── Status icon ───────────────────────────────────────────────────────────────

function StatusIcon({ status, score }: { status: string; score: number }) {
  const color = healthColor(status, score)
  const sz = { fontSize: 14 }
  if (status === 'OFFLINE')  return <ErrIcon sx={{ ...sz, color }} />
  if (status === 'DEGRADED') return <WarnIcon sx={{ ...sz, color }} />
  if (status === 'ONLINE' && score >= 0.8) return <OkIcon sx={{ ...sz, color }} />
  if (status === 'ONLINE')   return <WarnIcon sx={{ ...sz, color }} />
  return <UnknownIcon sx={{ ...sz, color: '#64748B' }} />
}

// ── Single rack card ──────────────────────────────────────────────────────────

function RackCard({ rack, onClick }: { rack: RackCard; onClick: () => void }) {
  const border = healthColor(rack.operationalStatus, rack.healthScore)
  const score = rack.healthScore ?? 0

  return (
    <Card
      onClick={onClick}
      sx={{
        cursor: 'pointer',
        borderLeft: `3px solid ${border}`,
        transition: 'all 0.15s',
        '&:hover': { transform: 'translateY(-2px)', boxShadow: `0 4px 20px ${border}30` },
        height: '100%',
      }}
    >
      <CardContent sx={{ p: 1.5, '&:last-child': { pb: 1.5 } }}>
        {/* Header row */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.75 }}>
          <StatusIcon status={rack.operationalStatus} score={score} />
          <Typography variant="body2" fontWeight={600} noWrap sx={{ flex: 1, fontSize: '0.78rem' }}>
            {rack.canonicalName}
          </Typography>
          {rack.activeAlertCount > 0 && (
            <Chip
              label={rack.activeAlertCount}
              size="small"
              sx={{ bgcolor: '#E05A5A22', color: '#E05A5A', fontSize: '0.65rem',
                    height: 18, minWidth: 22, fontWeight: 700 }}
            />
          )}
        </Box>

        {/* Health bar */}
        <Box sx={{ mb: 1 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.25 }}>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>Health</Typography>
            <Typography variant="caption" sx={{ color: border, fontWeight: 600 }}>
              {Math.round(score * 100)}%
            </Typography>
          </Box>
          <LinearProgress
            variant="determinate"
            value={score * 100}
            sx={{
              height: 4, borderRadius: 2, bgcolor: 'rgba(255,255,255,0.06)',
              '& .MuiLinearProgress-bar': { bgcolor: border, borderRadius: 2 },
            }}
          />
        </Box>

        {/* Metric row */}
        <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0.5 }}>
          <MetricPill label="Power"
            value={rack.powerDrawW != null ? `${Math.round(rack.powerDrawW)}W` : '—'} />
          <MetricPill label="Temp"
            value={rack.inletTempC != null ? `${rack.inletTempC.toFixed(1)}°C` : '—'}
            warn={rack.inletTempC != null && rack.inletTempC > 30} />
          <MetricPill label="Devices" value={String(rack.deviceCount)} />
          <MetricPill label="Redundancy" value={rack.redundancyPosture || '—'} />
        </Box>

        {/* Tags */}
        <Box sx={{ display: 'flex', gap: 0.5, mt: 0.75, flexWrap: 'wrap' }}>
          {rack.criticalityLevel && (
            <Chip label={rack.criticalityLevel} size="small"
              sx={{ height: 16, fontSize: '0.6rem', bgcolor: 'rgba(255,255,255,0.06)',
                    color: rack.criticalityLevel === 'P1' ? '#E05A5A' : 'text.secondary' }} />
          )}
          <Chip label={rack.operationalStatus} size="small"
            sx={{ height: 16, fontSize: '0.6rem',
                  bgcolor: `${border}22`, color: border }} />
        </Box>
      </CardContent>
    </Card>
  )
}

function MetricPill({ label, value, warn = false }: { label: string; value: string; warn?: boolean }) {
  return (
    <Box sx={{ bgcolor: 'rgba(255,255,255,0.03)', borderRadius: 1, px: 0.75, py: 0.25 }}>
      <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', fontSize: '0.6rem' }}>
        {label}
      </Typography>
      <Typography variant="caption"
        sx={{ fontWeight: 600, fontSize: '0.72rem', color: warn ? '#F59E0B' : 'text.primary' }}>
        {value}
      </Typography>
    </Box>
  )
}

// ── Skeleton grid ─────────────────────────────────────────────────────────────

function SkeletonGrid() {
  return (
    <Grid container spacing={1.5}>
      {Array.from({ length: 12 }).map((_, i) => (
        <Grid item xs={12} sm={6} md={4} lg={3} xl={2} key={i}>
          <Skeleton variant="rectangular" height={160} sx={{ borderRadius: 1 }} />
        </Grid>
      ))}
    </Grid>
  )
}

// ── Summary bar ───────────────────────────────────────────────────────────────

function SummaryBar({ racks }: { racks: RackCard[] }) {
  const total   = racks.length
  const online  = racks.filter(r => r.operationalStatus === 'ONLINE').length
  const degraded = racks.filter(r => r.operationalStatus === 'DEGRADED').length
  const offline  = racks.filter(r => r.operationalStatus === 'OFFLINE').length
  const alerts   = racks.reduce((s, r) => s + (r.activeAlertCount || 0), 0)

  const pills = [
    { label: 'Total racks', value: total,    color: '#94A3B8' },
    { label: 'Online',      value: online,   color: '#059669' },
    { label: 'Degraded',    value: degraded, color: '#F59E0B' },
    { label: 'Offline',     value: offline,  color: '#E05A5A' },
    { label: 'Active alerts', value: alerts, color: alerts > 0 ? '#E05A5A' : '#059669' },
  ]

  return (
    <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap', mb: 2 }}>
      {pills.map(p => (
        <Box key={p.label} sx={{ textAlign: 'center' }}>
          <Typography variant="h3" sx={{ color: p.color, lineHeight: 1 }}>
            {p.value}
          </Typography>
          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
            {p.label}
          </Typography>
        </Box>
      ))}
    </Box>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function RackHealthGrid({ tenantId }: { tenantId: string }) {
  const navigate = useNavigate()
  const [search, setSearch]   = useState('')
  const [filterStatus, setFilterStatus] = useState('ALL')
  const [sortBy, setSortBy]   = useState<'health' | 'alerts' | 'name'>('alerts')

  // Initial query
  const { data: qData, loading, error } = useQuery(RACK_HEALTH_QUERY, {
    variables: { tenantId, limit: 500 },
    pollInterval: 30000,  // fallback poll every 30s
  })

  // Live subscription overlay
  const { data: subData } = useSubscription(RACK_HEALTH_SUB, {
    variables: { tenantId },
    onError: () => {},  // subscription optional — fall back to poll
  })

  // Merge query + subscription data
  const racks: RackCard[] = useMemo(() => {
    const base: RackCard[] = qData?.rackHealthCards ?? []
    if (!subData?.rackHealthUpdates?.length) return base
    // Subscription replaces entire list
    return subData.rackHealthUpdates
  }, [qData, subData])

  // Filter + sort
  const displayed = useMemo(() => {
    let items = [...racks]
    if (search) {
      const q = search.toLowerCase()
      items = items.filter(r => r.canonicalName.toLowerCase().includes(q))
    }
    if (filterStatus !== 'ALL') {
      items = items.filter(r => r.operationalStatus === filterStatus)
    }
    items.sort((a, b) => {
      if (sortBy === 'alerts') return (b.activeAlertCount ?? 0) - (a.activeAlertCount ?? 0)
      if (sortBy === 'health') return (a.healthScore ?? 0) - (b.healthScore ?? 0)
      return a.canonicalName.localeCompare(b.canonicalName)
    })
    return items
  }, [racks, search, filterStatus, sortBy])

  if (error) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error">
          Cannot reach graph-api-service. Make sure the stack is running.<br />
          <small>{error.message}</small>
        </Alert>
      </Box>
    )
  }

  return (
    <Box sx={{ p: 2 }}>
      {/* Page header */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
        <RackIcon sx={{ color: '#0891B2' }} />
        <Typography variant="h2">Rack Health</Typography>
        <Chip label="LIVE" size="small"
          sx={{ bgcolor: 'rgba(5,150,105,0.2)', color: '#059669', fontWeight: 700,
                fontSize: '0.65rem', ml: 'auto' }} />
      </Box>

      {/* Summary */}
      {!loading && <SummaryBar racks={racks} />}

      {/* Filters */}
      <Box sx={{ display: 'flex', gap: 1.5, mb: 2, flexWrap: 'wrap', alignItems: 'center' }}>
        <TextField
          placeholder="Search racks…"
          size="small"
          value={search}
          onChange={e => setSearch(e.target.value)}
          sx={{ minWidth: 200 }}
        />
        <FormControl size="small" sx={{ minWidth: 140 }}>
          <InputLabel>Status</InputLabel>
          <Select value={filterStatus} label="Status" onChange={e => setFilterStatus(e.target.value)}>
            <MenuItem value="ALL">All statuses</MenuItem>
            <MenuItem value="ONLINE">Online</MenuItem>
            <MenuItem value="DEGRADED">Degraded</MenuItem>
            <MenuItem value="OFFLINE">Offline</MenuItem>
            <MenuItem value="UNKNOWN">Unknown</MenuItem>
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 140 }}>
          <InputLabel>Sort by</InputLabel>
          <Select value={sortBy} label="Sort by" onChange={e => setSortBy(e.target.value as any)}>
            <MenuItem value="alerts">Alerts (high first)</MenuItem>
            <MenuItem value="health">Health (low first)</MenuItem>
            <MenuItem value="name">Name (A-Z)</MenuItem>
          </Select>
        </FormControl>
        <Typography variant="caption" sx={{ color: 'text.secondary', ml: 'auto' }}>
          {loading ? 'Loading…' : `${displayed.length} / ${racks.length} racks`}
        </Typography>
      </Box>

      {/* Grid */}
      {loading ? (
        <SkeletonGrid />
      ) : displayed.length === 0 ? (
        <Alert severity="info">
          No racks found. Make sure the Digital Twin is populated (check graph-updater logs).
        </Alert>
      ) : (
        <Grid container spacing={1.5}>
          {displayed.map(rack => (
            <Grid item xs={12} sm={6} md={4} lg={3} xl={2} key={rack.entityId}>
              <RackCard rack={rack} onClick={() => navigate(`/rack/${rack.entityId}`)} />
            </Grid>
          ))}
        </Grid>
      )}
    </Box>
  )
}
