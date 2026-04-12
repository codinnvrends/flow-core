/**
 * pages/Analytics.tsx
 * Screen 4 — Filter/export bar, 4 KPI tiles, power distribution pie,
 * component breakdown, thermal zone table, 7-day PUE vs benchmark line chart,
 * cooling efficiency trends, peak/off-peak bar chart. 8-tab sub-view router.
 */
import React, { useState } from 'react'
import {
  Box, Grid, Typography, Button, Chip, Tabs, Tab,
  Table, TableBody, TableCell, TableHead, TableRow, LinearProgress,
} from '@mui/material'
import { Download, Schedule } from '@mui/icons-material'
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, ResponsiveContainer, Legend, ReferenceLine,
} from 'recharts'
import { api } from '../lib/api'
import { mockAnalyticsTrends, mockPowerSummary, mockThermalZones } from '../mocks'
import { useApi } from '../hooks/useApi'
import {
  PageShell, KpiTile, KpiRow, SectionCard, StatusChip,
  MockBanner, LoadingOverlay,
} from '../components/shared'
import { CHART_COLORS, tempColor } from '../lib/theme'

const TABS = ['Overview', 'Energy', 'Thermal', 'Alerts', 'Capacity', 'Performance', 'Benchmarks', 'Custom']

// Mock 7-day PUE data
const PUE_7DAY = Array.from({ length: 7 }, (_, i) => ({
  day: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][i],
  pue: parseFloat((1.38 + Math.sin(i) * 0.08 + Math.random() * 0.05).toFixed(3)),
  benchmark: 1.58,
}))

// Mock peak vs off-peak
const PEAK_DATA = Array.from({ length: 24 }, (_, i) => ({
  hour: `${String(i).padStart(2, '0')}:00`,
  power: parseFloat((1200 + (i >= 9 && i <= 21 ? 600 : 0) + Math.random() * 200).toFixed(0)),
  peak: i >= 9 && i <= 21,
}))

// Mock cooling efficiency 7-day
const COOLING_EFF = Array.from({ length: 7 }, (_, i) => ({
  day: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][i],
  efficiency: parseFloat((88 + Math.sin(i) * 5 + Math.random() * 3).toFixed(1)),
}))

const PIE_COLORS = [CHART_COLORS.it, CHART_COLORS.cooling, CHART_COLORS.other]

export default function Analytics() {
  const [tab, setTab] = useState(0)

  const { data: trends } = useApi(() => api.analytics.trends('all', '24h'), mockAnalyticsTrends)
  const { data: power }  = useApi(() => api.power.summary(),                mockPowerSummary)
  const { data: zones }  = useApi(() => api.thermal.zones(),                mockThermalZones)

  const avgPue = trends?.length
    ? (trends.reduce((s, t) => s + (t.pue ?? 0), 0) / trends.length).toFixed(3)
    : '—'

  const dist = power?.power_distribution
  const pieData = dist ? [
    { name: 'IT Servers',       value: dist.it_kw },
    { name: 'Cooling (CRAC)',   value: dist.cooling_kw },
    { name: 'Infra / Other',    value: dist.other_kw },
  ] : []

  return (
    <PageShell title="Analytics & Insights" subtitle="Performance trends, benchmarks, and usage patterns">
      <MockBanner />

      {/* Filter / export bar */}
      <Box sx={{ display: 'flex', gap: 1.5, mb: 2.5, alignItems: 'center', flexWrap: 'wrap' }}>
        {['Last 7 Days', 'Last 30 Days', 'Last 6 Months', 'Custom Range'].map((f, i) => (
          <Chip
            key={f} label={f} size="small" clickable
            sx={i === 0
              ? { bgcolor: 'rgba(8,145,178,0.2)', color: '#0891B2', fontWeight: 600 }
              : { bgcolor: 'rgba(255,255,255,0.04)', color: '#94A3B8' }}
          />
        ))}
        <Box sx={{ flex: 1 }} />
        <Button size="small" startIcon={<Download />}
          sx={{ borderColor: 'rgba(255,255,255,0.1)', color: '#94A3B8', border: '1px solid', fontSize: '0.75rem' }}>
          Export CSV
        </Button>
        <Button size="small" startIcon={<Schedule />}
          sx={{ borderColor: 'rgba(255,255,255,0.1)', color: '#94A3B8', border: '1px solid', fontSize: '0.75rem' }}>
          Schedule Report
        </Button>
      </Box>

      {/* KPIs */}
      <KpiRow>
        <KpiTile label="Avg PUE (6-Month)" value={avgPue}        color="#A78BFA" delta={-0.15} />
        <KpiTile label="Total Energy"      value="182.4"  unit="MWh" color="#F59E0B" />
        <KpiTile label="Energy Cost"       value="€29,180" color="#059669" />
        <KpiTile label="Cooling Efficiency" value="91" unit="%" color="#0891B2" delta={3} />
      </KpiRow>

      {/* Tab bar */}
      <Tabs
        value={tab}
        onChange={(_, v) => setTab(v)}
        variant="scrollable"
        scrollButtons="auto"
        sx={{
          mb: 2, borderBottom: '1px solid rgba(255,255,255,0.06)',
          '& .MuiTab-root': { fontSize: '0.78rem', minHeight: 40, py: 0, color: '#64748B', textTransform: 'none' },
          '& .Mui-selected': { color: '#0891B2' },
          '& .MuiTabs-indicator': { bgcolor: '#0891B2', height: 2 },
        }}
      >
        {TABS.map(t => <Tab key={t} label={t} />)}
      </Tabs>

      {/* Tab 0: Overview (all charts) */}
      {tab === 0 && (
        <Grid container spacing={2}>
          {/* Power Distribution Pie */}
          <Grid item xs={12} md={5}>
            <SectionCard title="Power Distribution by Component">
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <PieChart width={180} height={180}>
                  <Pie data={pieData} cx={90} cy={90} innerRadius={55} outerRadius={80} paddingAngle={3} dataKey="value">
                    {pieData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i]} />)}
                  </Pie>
                  <RTooltip
                    contentStyle={{ background: '#111E2D', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, fontSize: 11 }}
                    formatter={(v: number) => [`${v.toFixed(0)} kW`]}
                  />
                </PieChart>
                <Box sx={{ flex: 1 }}>
                  {pieData.map((d, i) => (
                    <Box key={d.name} sx={{ mb: 1 }}>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.25 }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                          <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: PIE_COLORS[i] }} />
                          <Typography sx={{ fontSize: '0.72rem', color: '#94A3B8' }}>{d.name}</Typography>
                        </Box>
                        <Typography sx={{ fontSize: '0.72rem', color: '#E2E8F0', fontWeight: 600 }}>
                          {d.value.toFixed(0)} kW
                        </Typography>
                      </Box>
                    </Box>
                  ))}
                </Box>
              </Box>
            </SectionCard>
          </Grid>

          {/* 7-Day PUE vs Industry Benchmark */}
          <Grid item xs={12} md={7}>
            <SectionCard title="7-Day PUE vs Industry Benchmark">
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={PUE_7DAY} margin={{ top: 4, right: 16, left: -10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
                  <XAxis dataKey="day" tick={{ fontSize: 10, fill: CHART_COLORS.text }} />
                  <YAxis domain={[1.0, 2.0]} tick={{ fontSize: 10, fill: CHART_COLORS.text }} width={30} />
                  <RTooltip contentStyle={{ background: '#111E2D', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, fontSize: 11 }} labelStyle={{ color: '#94A3B8' }} />
                  <Legend wrapperStyle={{ fontSize: 11, color: '#94A3B8' }} />
                  <ReferenceLine y={1.58} stroke="#F59E0B" strokeDasharray="4 2" label={{ value: 'Industry avg 1.58', fill: '#F59E0B', fontSize: 10, position: 'right' }} />
                  <Line type="monotone" dataKey="pue" stroke={CHART_COLORS.pue} dot={{ r: 3, fill: CHART_COLORS.pue }} strokeWidth={2} name="FlowCore PUE" />
                </LineChart>
              </ResponsiveContainer>
            </SectionCard>
          </Grid>

          {/* Thermal Zone Status Table */}
          <Grid item xs={12} md={6}>
            <SectionCard title="Thermal Zone Status">
              <Table size="small">
                <TableHead>
                  <TableRow>
                    {['Zone', 'Avg Temp', 'Max Temp', 'Sensors', 'Status'].map(h => (
                      <TableCell key={h} sx={{ color: '#64748B', fontSize: '0.7rem', fontWeight: 600, borderColor: 'rgba(255,255,255,0.05)' }}>{h}</TableCell>
                    ))}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {zones?.map(z => (
                    <TableRow key={z.zone_id} hover sx={{ '& td': { borderColor: 'rgba(255,255,255,0.04)' } }}>
                      <TableCell sx={{ fontSize: '0.75rem', color: '#E2E8F0' }}>{z.zone_name}</TableCell>
                      <TableCell sx={{ fontSize: '0.75rem', color: tempColor(z.avg_temp_c), fontWeight: 600 }}>{z.avg_temp_c.toFixed(1)}°C</TableCell>
                      <TableCell sx={{ fontSize: '0.75rem', color: tempColor(z.max_temp_c), fontWeight: 600 }}>{z.max_temp_c.toFixed(1)}°C</TableCell>
                      <TableCell sx={{ fontSize: '0.75rem', color: '#94A3B8' }}>{z.sensor_count}</TableCell>
                      <TableCell><StatusChip status={z.status} /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </SectionCard>
          </Grid>

          {/* Cooling Efficiency 7-day */}
          <Grid item xs={12} md={6}>
            <SectionCard title="Cooling Efficiency Trends (7-Day)">
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={COOLING_EFF} margin={{ top: 4, right: 16, left: -10, bottom: 0 }}>
                  <defs>
                    <linearGradient id="eff-grad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor={CHART_COLORS.cooling} stopOpacity={0.4} />
                      <stop offset="95%" stopColor={CHART_COLORS.cooling} stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
                  <XAxis dataKey="day" tick={{ fontSize: 10, fill: CHART_COLORS.text }} />
                  <YAxis domain={[70, 100]} tick={{ fontSize: 10, fill: CHART_COLORS.text }} width={30} unit="%" />
                  <RTooltip contentStyle={{ background: '#111E2D', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, fontSize: 11 }} labelStyle={{ color: '#94A3B8' }} />
                  <Area type="monotone" dataKey="efficiency" stroke={CHART_COLORS.cooling} fill="url(#eff-grad)" strokeWidth={2} name="Cooling Eff (%)" />
                </AreaChart>
              </ResponsiveContainer>
            </SectionCard>
          </Grid>

          {/* Peak vs Off-Peak */}
          <Grid item xs={12}>
            <SectionCard title="Power Usage Patterns — Peak vs Off-Peak (24h)">
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={PEAK_DATA} margin={{ top: 4, right: 16, left: -10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} vertical={false} />
                  <XAxis dataKey="hour" tick={{ fontSize: 9, fill: CHART_COLORS.text }} interval={2} />
                  <YAxis tick={{ fontSize: 10, fill: CHART_COLORS.text }} width={40} unit=" kW" />
                  <RTooltip contentStyle={{ background: '#111E2D', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, fontSize: 11 }} labelStyle={{ color: '#94A3B8' }} />
                  <Bar dataKey="power" name="Power (kW)" radius={[2, 2, 0, 0]}>
                    {PEAK_DATA.map((d, i) => (
                      <Cell key={i} fill={d.peak ? CHART_COLORS.power : CHART_COLORS.it} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
              <Box sx={{ display: 'flex', gap: 2, mt: 1 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                  <Box sx={{ width: 10, height: 10, borderRadius: 1, bgcolor: CHART_COLORS.power }} />
                  <Typography sx={{ fontSize: '0.7rem', color: '#94A3B8' }}>Peak (09:00–21:00)</Typography>
                </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                  <Box sx={{ width: 10, height: 10, borderRadius: 1, bgcolor: CHART_COLORS.it }} />
                  <Typography sx={{ fontSize: '0.7rem', color: '#94A3B8' }}>Off-Peak</Typography>
                </Box>
              </Box>
            </SectionCard>
          </Grid>
        </Grid>
      )}

      {/* Other tabs — placeholder */}
      {tab > 0 && (
        <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 8, color: '#64748B' }}>
          <Typography sx={{ fontSize: '0.85rem' }}>
            {TABS[tab]} view — coming in Sprint 2
          </Typography>
        </Box>
      )}
    </PageShell>
  )
}
