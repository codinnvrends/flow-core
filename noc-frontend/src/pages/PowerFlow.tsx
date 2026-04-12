/**
 * pages/PowerFlow.tsx
 * Screens 3, 3.1 — 4 power KPIs, power distribution bars + pie,
 * PUE analysis panel, 24h stacked area chart (Recharts), energy forecast,
 * power alerts list.
 */
import React, { useState } from 'react'
import {
  Box, Grid, Typography, Chip, Table, TableBody,
  TableCell, TableHead, TableRow, LinearProgress,
} from '@mui/material'
import {
  AreaChart, Area, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip as RTooltip,
  ResponsiveContainer, Legend,
} from 'recharts'
import { api } from '../lib/api'
import {
  mockPowerSummary, mockPowerTimeseries, mockPowerForecast, mockAlerts,
} from '../mocks'
import { useApi, usePollingApi } from '../hooks/useApi'
import {
  PageShell, KpiTile, KpiRow, SectionCard, StatusChip,
  MockBanner, LoadingOverlay, ErrorAlert,
} from '../components/shared'
import { CHART_COLORS } from '../lib/theme'

const PIE_COLORS = [CHART_COLORS.it, CHART_COLORS.cooling, CHART_COLORS.other]

const CUSTOM_TOOLTIP = ({ active, payload }: any) => {
  if (!active || !payload?.length) return null
  return (
    <Box sx={{ bgcolor: '#111E2D', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 1.5, p: 1, fontSize: 11 }}>
      {payload.map((p: any) => (
        <Typography key={p.name} sx={{ fontSize: '0.72rem', color: p.color }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toFixed(1) : p.value} kW
        </Typography>
      ))}
    </Box>
  )
}

export default function PowerFlow() {
  const { data: summary, loading: sl, error: se } = usePollingApi(() => api.power.summary(),    mockPowerSummary,    30000)
  const { data: timeseries, loading: tl }         = usePollingApi(() => api.power.timeseries(), mockPowerTimeseries, 30000)
  const { data: forecast }                        = useApi(() => api.power.forecast(),           mockPowerForecast)
  const { data: alertsData }                      = usePollingApi(() => api.alerts.list({ severity: 'CRITICAL,WARNING' }), mockAlerts, 30000)

  const dist = summary?.power_distribution
  const distTotal = dist ? dist.it_kw + dist.cooling_kw + dist.other_kw : 1
  const pieData = dist ? [
    { name: 'IT Load',  value: dist.it_kw },
    { name: 'Cooling',  value: dist.cooling_kw },
    { name: 'Other',    value: dist.other_kw },
  ] : []

  const chartData = timeseries?.map(t => ({
    label: new Date(t.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    it:      parseFloat((t.it_load_kw).toFixed(1)),
    cooling: parseFloat((t.cooling_kw).toFixed(1)),
  })) ?? []

  return (
    <PageShell title="PowerFlow" subtitle="Power consumption, PUE analysis, and energy forecast">
      <MockBanner />
      {se && <ErrorAlert message={se} />}

      {/* KPIs */}
      <KpiRow>
        <KpiTile label="Total Power Draw"   value={summary ? summary.total_power_draw_mw.toFixed(2) : '—'} unit="MW"  color="#F59E0B" delta={5}   loading={sl} />
        <KpiTile label="PUE"                value={summary?.pue.toFixed(2) ?? '—'}                          color="#A78BFA" delta={-0.08} deltaLabel="" loading={sl} />
        <KpiTile label="UPS Load"           value={summary?.ups_load_pct ?? '—'}                            unit="%" color="#0891B2" loading={sl} />
        <KpiTile label="Energy Cost Today"  value={summary ? `€${summary.energy_cost_eur_today.toLocaleString()}` : '—'} color="#059669" loading={sl} />
      </KpiRow>

      <Grid container spacing={2}>
        {/* Power Distribution */}
        <Grid item xs={12} md={4}>
          <SectionCard title="Power Distribution">
            {sl ? <LoadingOverlay /> : (
              <>
                <Box sx={{ display: 'flex', justifyContent: 'center', mb: 1 }}>
                  <PieChart width={200} height={160}>
                    <Pie data={pieData} cx={100} cy={80} innerRadius={50} outerRadius={75} paddingAngle={3} dataKey="value">
                      {pieData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i]} />)}
                    </Pie>
                    <RTooltip
                      contentStyle={{ background: '#111E2D', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, fontSize: 11 }}
                      formatter={(v: number) => [`${v.toFixed(0)} kW`, '']}
                    />
                  </PieChart>
                </Box>
                {pieData.map((d, i) => (
                  <Box key={d.name} sx={{ mb: 1 }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.25 }}>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: PIE_COLORS[i] }} />
                        <Typography sx={{ fontSize: '0.75rem', color: '#94A3B8' }}>{d.name}</Typography>
                      </Box>
                      <Typography sx={{ fontSize: '0.75rem', color: '#E2E8F0', fontWeight: 600 }}>
                        {((d.value / distTotal) * 100).toFixed(0)}%
                      </Typography>
                    </Box>
                    <LinearProgress
                      variant="determinate" value={(d.value / distTotal) * 100}
                      sx={{ height: 4, borderRadius: 2, bgcolor: 'rgba(255,255,255,0.06)', '& .MuiLinearProgress-bar': { bgcolor: PIE_COLORS[i], borderRadius: 2 } }}
                    />
                  </Box>
                ))}
              </>
            )}
          </SectionCard>

          {/* PUE Analysis */}
          <SectionCard title="PUE Analysis" sx={{ mt: 2 }}>
            {[
              ['Current',    summary?.pue_history.current],
              ['Last Hour',  summary?.pue_history.last_hour],
              ['Last Week',  summary?.pue_history.last_week],
              ['Last Month', summary?.pue_history.last_month],
            ].map(([label, val]) => (
              <Box key={label as string} sx={{ display: 'flex', justifyContent: 'space-between', py: 0.75, borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                <Typography sx={{ fontSize: '0.78rem', color: '#94A3B8' }}>{label}</Typography>
                <Typography sx={{ fontSize: '0.78rem', color: '#A78BFA', fontWeight: 600 }}>
                  {val != null ? (val as number).toFixed(2) : '—'}
                </Typography>
              </Box>
            ))}
          </SectionCard>
        </Grid>

        {/* 24h Stacked Area Chart */}
        <Grid item xs={12} md={8}>
          <SectionCard title="24h Power Consumption">
            {tl ? <LoadingOverlay /> : (
              <ResponsiveContainer width="100%" height={280}>
                <AreaChart data={chartData} margin={{ top: 4, right: 16, left: -10, bottom: 0 }}>
                  <defs>
                    <linearGradient id="it-grad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor={CHART_COLORS.it}      stopOpacity={0.4} />
                      <stop offset="95%" stopColor={CHART_COLORS.it}      stopOpacity={0.02} />
                    </linearGradient>
                    <linearGradient id="cooling-grad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor={CHART_COLORS.cooling} stopOpacity={0.4} />
                      <stop offset="95%" stopColor={CHART_COLORS.cooling} stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
                  <XAxis dataKey="label" tick={{ fontSize: 10, fill: CHART_COLORS.text }} interval={3} />
                  <YAxis tick={{ fontSize: 10, fill: CHART_COLORS.text }} width={40} unit=" kW" />
                  <RTooltip content={<CUSTOM_TOOLTIP />} />
                  <Legend wrapperStyle={{ fontSize: 11, color: '#94A3B8' }} />
                  <Area type="monotone" dataKey="it"      name="IT Load"  stroke={CHART_COLORS.it}      fill="url(#it-grad)"      strokeWidth={2} stackId="1" />
                  <Area type="monotone" dataKey="cooling" name="Cooling"  stroke={CHART_COLORS.cooling} fill="url(#cooling-grad)" strokeWidth={2} stackId="1" />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </SectionCard>

          {/* Energy Forecast */}
          <SectionCard title="Energy Forecast" sx={{ mt: 2 }}>
            <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
              {forecast?.map(f => (
                <Box key={f.horizon_label} sx={{ flex: 1, minWidth: 120, p: 1.5, bgcolor: 'rgba(8,145,178,0.06)', borderRadius: 2, border: '1px solid rgba(8,145,178,0.12)', textAlign: 'center' }}>
                  <Typography sx={{ fontSize: '0.68rem', color: '#64748B', mb: 0.5 }}>{f.horizon_label}</Typography>
                  <Typography sx={{ fontSize: '1.1rem', fontWeight: 700, color: '#F59E0B' }}>{f.predicted_mw.toFixed(2)} MW</Typography>
                  <Typography sx={{ fontSize: '0.72rem', color: '#64748B', mt: 0.25 }}>~€{f.predicted_cost_eur.toLocaleString()}</Typography>
                </Box>
              ))}
            </Box>
          </SectionCard>
        </Grid>

        {/* Power Alerts */}
        <Grid item xs={12}>
          <SectionCard title="Power Alerts">
            {alertsData?.items.filter(a => a.status !== 'RESOLVED').slice(0, 5).map(a => (
              <Box key={a.alert_id} sx={{ display: 'flex', alignItems: 'center', gap: 2, py: 0.75, borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                <StatusChip status={a.severity} />
                <Box sx={{ flex: 1 }}>
                  <Typography sx={{ fontSize: '0.78rem', color: '#E2E8F0' }}>{a.title}</Typography>
                  <Typography sx={{ fontSize: '0.7rem', color: '#64748B' }}>{a.zone} · {a.device} · {a.description}</Typography>
                </Box>
                <Typography sx={{ fontSize: '0.7rem', color: '#64748B', whiteSpace: 'nowrap' }}>
                  {new Date(a.event_ts).toLocaleTimeString()}
                </Typography>
              </Box>
            ))}
          </SectionCard>
        </Grid>
      </Grid>
    </PageShell>
  )
}
