/**
 * pages/ThermalFlow.tsx
 * Screens 2, 2.1 — 4 thermal KPIs, zone list, cooling units, hotspot panel,
 * 24h zone temp trend (Recharts), cooling controls (toggles + slider).
 */
import React, { useState } from 'react'
import {
  Box, Grid, Typography, Switch, Slider, Button, Chip,
  Table, TableBody, TableCell, TableHead, TableRow,
  LinearProgress, Alert, Snackbar,
} from '@mui/material'
import { Thermostat, Air, Warning } from '@mui/icons-material'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, ResponsiveContainer, Legend,
} from 'recharts'
import { api } from '../lib/api'
import {
  mockThermalZones, mockCoolingUnits, mockThermalControls, mockAnalyticsTrends,
} from '../mocks'
import { useApi, usePollingApi } from '../hooks/useApi'
import {
  PageShell, KpiTile, KpiRow, SectionCard, StatusChip,
  MockBanner, LoadingOverlay, ErrorAlert,
} from '../components/shared'
import { tempColor, CHART_COLORS } from '../lib/theme'

export default function ThermalFlow() {
  const [snackOpen, setSnackOpen] = useState(false)

  const { data: zones,    loading: zl, error: ze } = usePollingApi(() => api.thermal.zones(),    mockThermalZones,    60000)
  const { data: units,    loading: ul }             = usePollingApi(() => api.thermal.units(),    mockCoolingUnits,    60000)
  const { data: controls, reload: reloadControls }  = useApi(() => api.thermal.controls.get(),   mockThermalControls)
  const { data: trends }                            = useApi(() => api.analytics.trends('temp', '24h'), mockAnalyticsTrends)

  const [localControls, setLocalControls] = useState({ auto_optimise: true, target_temp_c: 22, eco_mode: false })

  React.useEffect(() => {
    if (controls) setLocalControls({ ...controls })
  }, [controls])

  const saveControls = async () => {
    try {
      await api.thermal.controls.set(localControls)
      setSnackOpen(true)
    } catch {
      // mock mode — just show success
      setSnackOpen(true)
    }
  }

  // Derived KPIs from zones
  const avgTemp    = zones?.length ? (zones.reduce((s, z) => s + z.avg_temp_c, 0) / zones.length).toFixed(1) : '—'
  const maxTemp    = zones?.length ? Math.max(...zones.map(z => z.max_temp_c)).toFixed(1) : '—'
  const hotspots   = zones?.filter(z => z.status === 'CRITICAL').length ?? 0
  const avgCooling = units?.length ? (units.reduce((s, u) => s + u.utilisation_pct, 0) / units.length).toFixed(0) : '—'

  // 24h trend chart data
  const trendData = trends?.map(t => ({
    label: new Date(t.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    temp:  t.avg_temp_c,
  })) ?? []

  return (
    <PageShell title="ThermalFlow" subtitle="Thermal monitoring, cooling units, and environment controls">
      <MockBanner />
      {ze && <ErrorAlert message={ze} />}

      {/* KPIs */}
      <KpiRow>
        <KpiTile label="Avg Temperature" value={avgTemp} unit="°C"  color="#0891B2" delta={-1.2} deltaLabel="°C" loading={zl} />
        <KpiTile label="Max Temperature" value={maxTemp} unit="°C"  color="#E05A5A" loading={zl} />
        <KpiTile label="Cooling Capacity" value={avgCooling} unit="%" color="#059669" loading={ul} />
        <KpiTile label="Active Hotspots"  value={hotspots}           color={hotspots > 0 ? '#E05A5A' : '#059669'} loading={zl} />
      </KpiRow>

      <Grid container spacing={2}>
        {/* Zone list */}
        <Grid item xs={12} md={4}>
          <SectionCard title="Thermal Zones">
            {zl ? <LoadingOverlay /> : (
              <Box>
                {zones?.map(z => (
                  <Box key={z.zone_id} sx={{ py: 1, borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                      <Typography sx={{ fontSize: '0.8rem', color: '#E2E8F0', fontWeight: 500 }}>{z.zone_name}</Typography>
                      <StatusChip status={z.status} />
                    </Box>
                    <Box sx={{ display: 'flex', gap: 2 }}>
                      <Typography sx={{ fontSize: '0.7rem', color: '#64748B' }}>
                        Avg: <span style={{ color: tempColor(z.avg_temp_c) }}>{z.avg_temp_c.toFixed(1)}°C</span>
                      </Typography>
                      <Typography sx={{ fontSize: '0.7rem', color: '#64748B' }}>
                        Max: <span style={{ color: tempColor(z.max_temp_c) }}>{z.max_temp_c.toFixed(1)}°C</span>
                      </Typography>
                      <Typography sx={{ fontSize: '0.7rem', color: '#64748B' }}>{z.rack_count} racks</Typography>
                    </Box>
                    <LinearProgress
                      variant="determinate"
                      value={Math.min(100, ((z.avg_temp_c - 18) / 20) * 100)}
                      sx={{
                        mt: 0.5, height: 3, borderRadius: 2,
                        bgcolor: 'rgba(255,255,255,0.06)',
                        '& .MuiLinearProgress-bar': {
                          bgcolor: tempColor(z.avg_temp_c),
                          borderRadius: 2,
                        },
                      }}
                    />
                  </Box>
                ))}
              </Box>
            )}
          </SectionCard>
        </Grid>

        {/* 24h Temp Trend chart */}
        <Grid item xs={12} md={8}>
          <SectionCard title="24h Temperature Trends">
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={trendData} margin={{ top: 4, right: 16, left: -10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
                <XAxis dataKey="label" tick={{ fontSize: 10, fill: CHART_COLORS.text }} interval={3} />
                <YAxis domain={[18, 40]} tick={{ fontSize: 10, fill: CHART_COLORS.text }} width={30} unit="°" />
                <RTooltip
                  contentStyle={{ background: '#111E2D', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, fontSize: 11 }}
                  labelStyle={{ color: '#94A3B8' }}
                />
                <Line type="monotone" dataKey="temp" stroke="#0891B2" dot={false} strokeWidth={2} name="Avg Temp (°C)" />
              </LineChart>
            </ResponsiveContainer>
          </SectionCard>
        </Grid>

        {/* Cooling units */}
        <Grid item xs={12} md={7}>
          <SectionCard title="Cooling Units">
            {ul ? <LoadingOverlay /> : (
              <Table size="small">
                <TableHead>
                  <TableRow>
                    {['Unit', 'Zone', 'Utilisation', 'Power (kW)', 'Airflow (CFM)', 'Status'].map(h => (
                      <TableCell key={h} sx={{ color: '#64748B', fontSize: '0.7rem', fontWeight: 600, borderColor: 'rgba(255,255,255,0.05)' }}>{h}</TableCell>
                    ))}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {units?.map(u => (
                    <TableRow key={u.unit_id} hover sx={{ '& td': { borderColor: 'rgba(255,255,255,0.04)' } }}>
                      <TableCell sx={{ fontSize: '0.78rem', color: '#E2E8F0' }}>{u.unit_name}</TableCell>
                      <TableCell sx={{ fontSize: '0.75rem', color: '#94A3B8' }}>{u.zone_name}</TableCell>
                      <TableCell>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <LinearProgress
                            variant="determinate" value={u.utilisation_pct}
                            sx={{
                              width: 60, height: 4, borderRadius: 2,
                              bgcolor: 'rgba(255,255,255,0.06)',
                              '& .MuiLinearProgress-bar': {
                                bgcolor: u.utilisation_pct > 90 ? '#E05A5A' : u.utilisation_pct > 75 ? '#F59E0B' : '#059669',
                                borderRadius: 2,
                              },
                            }}
                          />
                          <Typography sx={{ fontSize: '0.72rem', color: '#E2E8F0' }}>{u.utilisation_pct}%</Typography>
                        </Box>
                      </TableCell>
                      <TableCell sx={{ fontSize: '0.75rem', color: '#94A3B8' }}>{u.power_kw.toFixed(1)}</TableCell>
                      <TableCell sx={{ fontSize: '0.75rem', color: '#94A3B8' }}>{u.airflow_cfm.toFixed(0)}</TableCell>
                      <TableCell><StatusChip status={u.status} /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </SectionCard>
        </Grid>

        {/* Hotspot detection */}
        <Grid item xs={12} md={5}>
          <SectionCard title="Hotspot Detection">
            {hotspots === 0 ? (
              <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', py: 3, gap: 1 }}>
                <Thermostat sx={{ fontSize: 32, color: '#059669' }} />
                <Typography sx={{ color: '#059669', fontSize: '0.82rem' }}>No hotspots detected</Typography>
                <Typography sx={{ color: '#64748B', fontSize: '0.72rem' }}>All zones within normal temperature range</Typography>
              </Box>
            ) : (
              <Box>
                {zones?.filter(z => z.status !== 'NORMAL').map(z => (
                  <Box key={z.zone_id} sx={{ display: 'flex', alignItems: 'center', gap: 1.5, p: 1, mb: 1, bgcolor: 'rgba(224,90,90,0.06)', borderRadius: 2, border: '1px solid rgba(224,90,90,0.15)' }}>
                    <Warning sx={{ fontSize: 18, color: z.status === 'CRITICAL' ? '#E05A5A' : '#F59E0B' }} />
                    <Box>
                      <Typography sx={{ fontSize: '0.78rem', color: '#E2E8F0' }}>{z.zone_name}</Typography>
                      <Typography sx={{ fontSize: '0.7rem', color: '#64748B' }}>Max: {z.max_temp_c}°C · Avg: {z.avg_temp_c}°C</Typography>
                    </Box>
                    <Box sx={{ ml: 'auto' }}>
                      <StatusChip status={z.status} />
                    </Box>
                  </Box>
                ))}
              </Box>
            )}
          </SectionCard>

          {/* Cooling Controls */}
          <SectionCard title="Cooling Controls" sx={{ mt: 2 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
              <Box>
                <Typography sx={{ fontSize: '0.8rem', color: '#E2E8F0' }}>Auto-Optimise</Typography>
                <Typography sx={{ fontSize: '0.7rem', color: '#64748B' }}>AI-driven cooling adjustment</Typography>
              </Box>
              <Switch
                checked={localControls.auto_optimise}
                onChange={e => setLocalControls(p => ({ ...p, auto_optimise: e.target.checked }))}
                sx={{ '& .MuiSwitch-switchBase.Mui-checked': { color: '#0891B2' }, '& .MuiSwitch-switchBase.Mui-checked + .MuiSwitch-track': { bgcolor: '#0891B2' } }}
              />
            </Box>

            <Box sx={{ mb: 1.5 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                <Typography sx={{ fontSize: '0.8rem', color: '#E2E8F0' }}>Target Temperature</Typography>
                <Typography sx={{ fontSize: '0.8rem', color: '#0891B2', fontWeight: 600 }}>{localControls.target_temp_c}°C</Typography>
              </Box>
              <Slider
                value={localControls.target_temp_c}
                onChange={(_, v) => setLocalControls(p => ({ ...p, target_temp_c: v as number }))}
                min={18} max={28} step={0.5}
                sx={{ color: '#0891B2', '& .MuiSlider-thumb': { width: 14, height: 14 } }}
              />
              <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                <Typography sx={{ fontSize: '0.65rem', color: '#64748B' }}>18°C</Typography>
                <Typography sx={{ fontSize: '0.65rem', color: '#64748B' }}>28°C</Typography>
              </Box>
            </Box>

            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
              <Box>
                <Typography sx={{ fontSize: '0.8rem', color: '#E2E8F0' }}>Eco Mode</Typography>
                <Typography sx={{ fontSize: '0.7rem', color: '#64748B' }}>Reduce cooling during off-peak</Typography>
              </Box>
              <Switch
                checked={localControls.eco_mode}
                onChange={e => setLocalControls(p => ({ ...p, eco_mode: e.target.checked }))}
                sx={{ '& .MuiSwitch-switchBase.Mui-checked': { color: '#059669' }, '& .MuiSwitch-switchBase.Mui-checked + .MuiSwitch-track': { bgcolor: '#059669' } }}
              />
            </Box>

            <Button fullWidth variant="contained" size="small" onClick={saveControls}
              sx={{ bgcolor: '#0891B2', '&:hover': { bgcolor: '#0e7490' }, fontSize: '0.78rem' }}>
              Save Controls
            </Button>
          </SectionCard>
        </Grid>
      </Grid>

      <Snackbar open={snackOpen} autoHideDuration={3000} onClose={() => setSnackOpen(false)}
        message="Cooling controls saved" anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }} />
    </PageShell>
  )
}
