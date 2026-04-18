/**
 * pages/Dashboard.tsx
 * Screens 1, 1.1, 1.2 — Landing page with facility context card, 4 KPI tiles,
 * zone list, D3 thermal heatmap, AI recommendations stub, recent alerts,
 * and a system health timeline chart (Recharts).
 */
import React, { useRef, useEffect, useState } from 'react'
import {
  Box, Typography, Grid, Card, CardContent, Chip, Button,
  ToggleButton, ToggleButtonGroup, LinearProgress, Tooltip,
  Table, TableBody, TableCell, TableRow,
} from '@mui/material'
import {
  Warning, Lightbulb, Download, Settings, PlayArrow,
} from '@mui/icons-material'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RTooltip,
  ResponsiveContainer, Legend,
} from 'recharts'
import * as d3 from 'd3'
import { api } from '../lib/api'
import {
  mockFacilitySummary, mockThermalZones, mockHeatmap,
  mockAlerts, mockAnalyticsTrends,
} from '../mocks'
import { useApi, usePollingApi } from '../hooks/useApi'
import {
  PageShell, KpiTile, KpiRow, SectionCard, StatusChip,
  MockBanner, LoadingOverlay, ErrorAlert,
} from '../components/shared'
import { tempColor, severityColor, CHART_COLORS } from '../lib/theme'
import type { RackHeatmapEntry } from '../lib/api'

const TENANT_ID = import.meta.env.VITE_DEFAULT_TENANT_ID || ''

// ── D3 Heatmap ────────────────────────────────────────────────────────────────
function ThermalHeatmap({ racks, mode }: { racks: RackHeatmapEntry[], mode: 'temp' | 'power' | 'airflow' }) {
  const ref = useRef<SVGSVGElement>(null)

  useEffect(() => {
    if (!ref.current || !racks.length) return
    const svg   = d3.select(ref.current)
    const W     = ref.current.clientWidth || 800
    const cols  = Math.ceil(Math.sqrt(racks.length * 1.6))
    const rows  = Math.ceil(racks.length / cols)
    const cell  = Math.max(18, Math.min(36, (W - 40) / cols))
    const H     = rows * cell + 40

    svg.attr('viewBox', `0 0 ${W} ${H}`)
    svg.selectAll('*').remove()

    const vals = racks.map(r =>
      mode === 'temp'    ? r.temp_c :
      mode === 'power'   ? r.power_draw_w / 1000 :
                           r.airflow_cfm / 1000)

    const colorScale = d3.scaleSequential(d3.interpolateRdYlGn)
      .domain(mode === 'temp' ? [38, 18] : [d3.max(vals)!, d3.min(vals)!])

    const g = svg.append('g').attr('transform', 'translate(20,20)')

    racks.forEach((rack, i) => {
      const cx = (i % cols) * cell
      const cy = Math.floor(i / cols) * cell
      const v  = vals[i]

      const cell_g = g.append('g')
        .attr('transform', `translate(${cx},${cy})`)
        .style('cursor', 'pointer')

      cell_g.append('rect')
        .attr('width', cell - 2)
        .attr('height', cell - 2)
        .attr('rx', 3)
        .attr('fill', colorScale(v))
        .attr('opacity', 0.85)

      if (cell > 24) {
        cell_g.append('text')
          .attr('x', (cell - 2) / 2)
          .attr('y', (cell - 2) / 2 + 4)
          .attr('text-anchor', 'middle')
          .attr('font-size', 9)
          .attr('fill', '#fff')
          .attr('font-family', 'Inter, sans-serif')
          .text(mode === 'temp' ? `${v.toFixed(0)}°` : v.toFixed(1))
      }

      cell_g.append('title').text(
        `${rack.rack_name} | Zone: ${rack.zone_name}\n` +
        `Temp: ${rack.temp_c}°C | Power: ${(rack.power_draw_w/1000).toFixed(1)}kW | Airflow: ${rack.airflow_cfm.toFixed(0)} CFM`
      )
    })
  }, [racks, mode])

  return <svg ref={ref} style={{ width: '100%', minHeight: 220 }} />
}

// ── AI Recommendations stub ───────────────────────────────────────────────────
const RECOMMENDATIONS = [
  { id: 1, priority: 'HIGH',   title: 'Increase airflow in Zone D', saving: '€420/mo', action: 'Raise CRAC-04 fan speed to 85%' },
  { id: 2, priority: 'MEDIUM', title: 'Consolidate low-util racks in Zone B', saving: '€210/mo', action: 'Migrate workloads to reduce cooling overhead' },
  { id: 3, priority: 'LOW',    title: 'Enable eco-mode during off-peak', saving: '€85/mo',  action: 'Schedule eco mode 22:00–06:00 UTC' },
]

const PRIORITY_COLOR: Record<string, string> = {
  HIGH: '#E05A5A', MEDIUM: '#F59E0B', LOW: '#0891B2',
}

// ── Health timeline chart ─────────────────────────────────────────────────────
function HealthTimeline({ data, window: win }: { data: { timestamp: string; pue?: number; power_mw?: number; avg_temp_c?: number }[], window: string }) {
  const fmt = (ts: string) => {
    const d = new Date(ts)
    return win === '24h' ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                         : d.toLocaleDateString([], { month: 'short', day: 'numeric' })
  }
  const formatted = data.map(d => ({ ...d, label: fmt(d.timestamp) }))

  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={formatted} margin={{ top: 4, right: 16, left: -10, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
        <XAxis dataKey="label" tick={{ fontSize: 10, fill: CHART_COLORS.text }} interval="preserveStartEnd" />
        <YAxis yAxisId="pue" domain={[1.0, 2.5]} tick={{ fontSize: 10, fill: CHART_COLORS.text }} width={32} />
        <YAxis yAxisId="power" orientation="right" tick={{ fontSize: 10, fill: CHART_COLORS.text }} width={36} />
        <RTooltip
          contentStyle={{ background: '#111E2D', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, fontSize: 11 }}
          labelStyle={{ color: '#94A3B8' }}
        />
        <Legend wrapperStyle={{ fontSize: 11, color: '#94A3B8' }} />
        <Line yAxisId="pue"   type="monotone" dataKey="pue"      stroke={CHART_COLORS.pue}   dot={false} strokeWidth={2} name="PUE" />
        <Line yAxisId="power" type="monotone" dataKey="power_mw" stroke={CHART_COLORS.power} dot={false} strokeWidth={2} name="Power (MW)" />
      </LineChart>
    </ResponsiveContainer>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Dashboard Page
// ─────────────────────────────────────────────────────────────────────────────
export default function Dashboard() {
  const [heatmapMode, setHeatmapMode] = useState<'temp' | 'power' | 'airflow'>('temp')
  const [timeWindow, setTimeWindow]   = useState('24h')

  const { data: facility, loading: fl, error: fe } = usePollingApi(
    () => api.facility.summary(),
    mockFacilitySummary,
    60000,
  )
  const { data: zones, loading: zl } = useApi(
    () => api.thermal.zones(),
    mockThermalZones,
  )
  const { data: heatmap, loading: hl } = usePollingApi(
    () => api.thermal.heatmap(heatmapMode),
    mockHeatmap,
    30000,
    [heatmapMode],
  )
  const { data: alertsData } = useApi(
    () => api.alerts.list({ limit: 5 }),
    mockAlerts,
  )
  const { data: trends } = useApi(
    () => api.analytics.trends('all', timeWindow),
    mockAnalyticsTrends,
    [timeWindow],
  )


  return (
    <PageShell>
      <MockBanner />

      {fe && <ErrorAlert message={fe} />}

      {/* ── Facility Context Card ── */}
      <Card sx={{ bgcolor: '#111E2D', mb: 2 }}>
        <CardContent sx={{ p: '16px !important' }}>
          <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 2 }}>
            <Box>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                <Typography sx={{ fontWeight: 700, fontSize: '1.1rem', color: '#E2E8F0' }}>
                  {facility?.facility_name ?? '—'}
                </Typography>
                <Chip label="Data Centre" size="small" sx={{ bgcolor: 'rgba(8,145,178,0.12)', color: '#0891B2', fontSize: '0.65rem' }} />
              </Box>
              <Typography sx={{ fontSize: '0.78rem', color: '#64748B' }}>
                {facility ? `${facility.city}, ${facility.country_code}` : '—'} ·{' '}
                Capacity: <strong style={{ color: '#E2E8F0' }}>{facility ? `${(facility.capacity_kw / 1000).toFixed(0)} MW` : '—'}</strong> ·{' '}
                Current load: <strong style={{ color: '#E2E8F0' }}>{facility ? `${(facility.current_load_kw / 1000).toFixed(1)} MW` : '—'}</strong>{' '}
                <span style={{ color: '#94A3B8' }}>({facility?.utilisation_pct}%)</span>
              </Typography>
            </Box>

          </Box>
        </CardContent>
      </Card>

      {/* ── 4 KPI Tiles ── */}
      <KpiRow>
        <KpiTile label="PUE"           value={facility?.pue?.toFixed(2) ?? '—'}  color="#A78BFA" delta={facility ? parseFloat(((facility.pue - facility.pue_target) / facility.pue_target * 100).toFixed(1)) : undefined} deltaLabel="% vs target" loading={fl} />
        <KpiTile label="Total Power"   value={facility ? (facility.current_load_kw / 1000).toFixed(1) : '—'} unit="MW" color="#F59E0B" delta={5}  loading={fl} />
        <KpiTile label="Avg Temp"      value={facility?.avg_temp_c?.toFixed(1) ?? '—'} unit="°C" color="#0891B2" delta={3}  loading={fl} />
        <KpiTile label="Active Alerts" value={facility?.active_alerts ?? '—'}         color="#E05A5A" loading={fl} />
      </KpiRow>

      {/* ── Zone List + Heatmap ── */}
      <Grid container spacing={2} sx={{ mb: 2 }}>
        <Grid item xs={12} md={3}>
          <SectionCard title={`Zones (${facility?.zone_count ?? 0})`}>
            {zl ? <LoadingOverlay /> : (
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                {zones?.map(z => (
                  <Box key={z.zone_id} sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', py: 0.5, borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                    <Box>
                      <Typography sx={{ fontSize: '0.78rem', color: '#E2E8F0' }}>{z.zone_name}</Typography>
                      <Typography sx={{ fontSize: '0.68rem', color: '#64748B' }}>{z.rack_count} racks · {z.avg_temp_c.toFixed(1)}°C avg</Typography>
                    </Box>
                    <StatusChip status={z.status} />
                  </Box>
                ))}
              </Box>
            )}
          </SectionCard>
        </Grid>

        <Grid item xs={12} md={9}>
          <SectionCard
            title="Live Thermal / Power / Airflow Map"
            action={
              <ToggleButtonGroup
                value={heatmapMode}
                exclusive
                onChange={(_, v) => v && setHeatmapMode(v)}
                size="small"
                sx={{ '& .MuiToggleButton-root': { fontSize: '0.68rem', py: 0.25, px: 1, color: '#64748B', border: '1px solid rgba(255,255,255,0.08)' }, '& .Mui-selected': { bgcolor: 'rgba(8,145,178,0.2) !important', color: '#0891B2 !important' } }}
              >
                <ToggleButton value="temp">Temp</ToggleButton>
                <ToggleButton value="power">Power</ToggleButton>
                <ToggleButton value="airflow">Airflow</ToggleButton>
              </ToggleButtonGroup>
            }
          >
            {hl ? <LoadingOverlay /> : <ThermalHeatmap racks={heatmap ?? []} mode={heatmapMode} />}
          </SectionCard>
        </Grid>
      </Grid>

      {/* ── AI Recommendations + Recent Alerts ── */}
      <Grid container spacing={2} sx={{ mb: 2 }}>
        <Grid item xs={12} md={6}>
          <SectionCard
            title="AI Recommendations"
            action={
              <Chip label="3 suggestions" size="small" sx={{ bgcolor: 'rgba(167,139,250,0.12)', color: '#A78BFA', fontSize: '0.65rem' }} />
            }
          >
            {RECOMMENDATIONS.map(r => (
              <Box key={r.id} sx={{ py: 1, borderBottom: '1px solid rgba(255,255,255,0.04)', '&:last-child': { borderBottom: 0 } }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 0.25 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                    <Lightbulb sx={{ fontSize: 14, color: PRIORITY_COLOR[r.priority] }} />
                    <Typography sx={{ fontSize: '0.8rem', color: '#E2E8F0', fontWeight: 500 }}>{r.title}</Typography>
                  </Box>
                  <Chip label={`Save ${r.saving}`} size="small" sx={{ bgcolor: 'rgba(5,150,105,0.12)', color: '#059669', fontSize: '0.65rem' }} />
                </Box>
                <Typography sx={{ fontSize: '0.72rem', color: '#64748B', ml: 2.5, mb: 0.5 }}>{r.action}</Typography>
                <Button size="small" sx={{ ml: 2, fontSize: '0.68rem', py: 0, px: 1, color: '#0891B2' }}>Apply</Button>
              </Box>
            ))}
          </SectionCard>
        </Grid>

        <Grid item xs={12} md={6}>
          <SectionCard
            title="Recent Alerts"
            action={
              <Button size="small" href="/alerts" sx={{ fontSize: '0.7rem', color: '#0891B2', py: 0 }}>View all</Button>
            }
          >
            {alertsData?.items.slice(0, 5).map(a => (
              <Box key={a.alert_id} sx={{ py: 0.75, borderBottom: '1px solid rgba(255,255,255,0.04)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Box>
                  <Typography sx={{ fontSize: '0.78rem', color: '#E2E8F0' }}>{a.title}</Typography>
                  <Typography sx={{ fontSize: '0.68rem', color: '#64748B' }}>
                    {a.zone} · {a.device} · {new Date(a.event_ts).toLocaleTimeString()}
                  </Typography>
                </Box>
                <StatusChip status={a.severity} />
              </Box>
            ))}
          </SectionCard>
        </Grid>
      </Grid>

      {/* ── System Health Timeline ── */}
      <SectionCard
        title="System Health Timeline"
        action={
          <ToggleButtonGroup
            value={timeWindow} exclusive
            onChange={(_, v) => v && setTimeWindow(v)}
            size="small"
            sx={{ '& .MuiToggleButton-root': { fontSize: '0.68rem', py: 0.25, px: 1, color: '#64748B', border: '1px solid rgba(255,255,255,0.08)' }, '& .Mui-selected': { bgcolor: 'rgba(8,145,178,0.2) !important', color: '#0891B2 !important' } }}
          >
            {['1h', '24h', '7d', '30d'].map(w => <ToggleButton key={w} value={w}>{w.toUpperCase()}</ToggleButton>)}
          </ToggleButtonGroup>
        }
      >
        {trends ? <HealthTimeline data={trends} window={timeWindow} /> : <LoadingOverlay />}
      </SectionCard>

      {/* ── Quick Actions ── */}
      <Box sx={{ display: 'flex', gap: 1.5, mt: 2 }}>
        <Button variant="outlined" size="small" startIcon={<PlayArrow />}
          sx={{ borderColor: 'rgba(8,145,178,0.4)', color: '#0891B2', fontSize: '0.78rem' }}>
          Run Optimization
        </Button>
        <Button variant="outlined" size="small" startIcon={<Download />}
          sx={{ borderColor: 'rgba(255,255,255,0.1)', color: '#94A3B8', fontSize: '0.78rem' }}>
          Generate Report
        </Button>
        <Button variant="outlined" size="small" startIcon={<Settings />}
          sx={{ borderColor: 'rgba(255,255,255,0.1)', color: '#94A3B8', fontSize: '0.78rem' }}>
          Configure Alerts
        </Button>
      </Box>
    </PageShell>
  )
}
