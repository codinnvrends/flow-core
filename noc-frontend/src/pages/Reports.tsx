/**
 * pages/Reports.tsx
 * Screen 6 — Report counts, Recent/Templates/Scheduled tabs,
 * report cards with Download/View/Share, Create Custom Report modal.
 */
import React, { useState } from 'react'
import {
  Box, Typography, Chip, Tabs, Tab, Button, Card, CardContent,
  Dialog, DialogTitle, DialogContent, DialogActions,
  TextField, Select, MenuItem, FormControl, InputLabel, Snackbar,
} from '@mui/material'
import {
  Download, Visibility, Share, Add, Description,
  BoltOutlined, Schedule, CheckCircle,
} from '@mui/icons-material'
import { api } from '../lib/api'
import { mockReports } from '../mocks'
import { useApi } from '../hooks/useApi'
import {
  PageShell, KpiTile, KpiRow, SectionCard, StatusChip,
  MockBanner, LoadingOverlay,
} from '../components/shared'
import type { Report } from '../lib/api'

const TYPE_ICON: Record<string, React.ReactNode> = {
  ENERGY:   <BoltOutlined sx={{ fontSize: 16 }} />,
  THERMAL:  <Description sx={{ fontSize: 16 }} />,
  CAPACITY: <Description sx={{ fontSize: 16 }} />,
  ALERTS:   <Description sx={{ fontSize: 16 }} />,
  CUSTOM:   <Description sx={{ fontSize: 16 }} />,
}
const TYPE_COLOR: Record<string, string> = {
  ENERGY: '#F59E0B', THERMAL: '#0891B2', CAPACITY: '#A78BFA', ALERTS: '#E05A5A', CUSTOM: '#059669',
}

function ReportCard({ report }: { report: Report }) {
  const isReady = report.status === 'READY'
  const typeColor = TYPE_COLOR[report.report_type] || '#64748B'

  return (
    <Card sx={{ bgcolor: '#111E2D', mb: 1.5, '&:hover': { boxShadow: '0 0 0 1px rgba(8,145,178,0.2)' }, transition: 'box-shadow 0.15s' }}>
      <CardContent sx={{ p: '12px 14px !important' }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 0.5 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Box sx={{ color: typeColor }}>{TYPE_ICON[report.report_type]}</Box>
            <Box>
              <Typography sx={{ fontSize: '0.85rem', fontWeight: 600, color: '#E2E8F0' }}>{report.report_name}</Typography>
              <Typography sx={{ fontSize: '0.7rem', color: '#64748B' }}>{report.description}</Typography>
            </Box>
          </Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            {report.scheduled_cron && (
              <Chip icon={<Schedule sx={{ fontSize: '12px !important' }} />} label="Scheduled" size="small"
                sx={{ bgcolor: 'rgba(8,145,178,0.12)', color: '#0891B2', fontSize: '0.62rem' }} />
            )}
            <StatusChip status={report.status} />
          </Box>
        </Box>

        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Box sx={{ display: 'flex', gap: 0.75 }}>
            <Chip label={report.report_type} size="small" sx={{ bgcolor: `${typeColor}18`, color: typeColor, fontSize: '0.62rem', height: 18 }} />
            <Chip label={report.period_label} size="small" sx={{ bgcolor: 'rgba(255,255,255,0.04)', color: '#94A3B8', fontSize: '0.62rem', height: 18 }} />
          </Box>

          <Box sx={{ display: 'flex', gap: 0.5 }}>
            {isReady && (
              <>
                <Button size="small" startIcon={<Download sx={{ fontSize: 12 }} />}
                  href={report.s3_download_url ?? '#'}
                  sx={{ fontSize: '0.68rem', py: 0.25, px: 0.75, color: '#059669', border: '1px solid rgba(5,150,105,0.3)', '&:hover': { bgcolor: 'rgba(5,150,105,0.06)' } }}>
                  Download PDF
                </Button>
                <Button size="small" startIcon={<Visibility sx={{ fontSize: 12 }} />}
                  sx={{ fontSize: '0.68rem', py: 0.25, px: 0.75, color: '#0891B2', border: '1px solid rgba(8,145,178,0.3)', '&:hover': { bgcolor: 'rgba(8,145,178,0.06)' } }}>
                  View Online
                </Button>
                <Button size="small" startIcon={<Share sx={{ fontSize: 12 }} />}
                  sx={{ fontSize: '0.68rem', py: 0.25, px: 0.75, color: '#64748B', border: '1px solid rgba(255,255,255,0.08)', '&:hover': { bgcolor: 'rgba(255,255,255,0.04)' } }}>
                  Share
                </Button>
              </>
            )}
          </Box>
        </Box>
      </CardContent>
    </Card>
  )
}

export default function Reports() {
  const [tabIdx,     setTabIdx]     = useState(0)
  const [createOpen, setCreateOpen] = useState(false)
  const [snack,      setSnack]      = useState('')
  const [newName,    setNewName]    = useState('')
  const [newType,    setNewType]    = useState('ENERGY')

  const { data } = useApi(() => api.reports.list(), mockReports)

  const counts = data?.counts
  const allReports = data?.items ?? []

  const tabReports = (() => {
    if (tabIdx === 0) return allReports.filter(r => !r.is_template)
    if (tabIdx === 1) return allReports.filter(r => r.is_template)
    if (tabIdx === 2) return allReports.filter(r => r.scheduled_cron !== null)
    return allReports
  })()

  const handleCreate = async () => {
    try {
      await api.reports.create({ report_name: newName, report_type: newType as any })
    } catch { /* mock */ }
    setSnack(`Report "${newName}" queued for generation`)
    setCreateOpen(false)
    setNewName('')
  }

  return (
    <PageShell title="Reports & Analytics" subtitle="Generated reports, templates, and scheduled delivery">
      <MockBanner />

      {/* KPIs */}
      <KpiRow>
        <KpiTile label="Total Reports"   value={counts?.total ?? 0}       color="#0891B2" />
        <KpiTile label="This Month"      value={counts?.this_month ?? 0}  color="#059669" />
        <KpiTile label="Scheduled"       value={counts?.scheduled ?? 0}   color="#A78BFA" />
        <KpiTile label="Generating"      value={counts?.generating ?? 0}  color="#F59E0B" />
      </KpiRow>

      {/* Header + Create button */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Tabs
          value={tabIdx}
          onChange={(_, v) => setTabIdx(v)}
          sx={{
            '& .MuiTab-root': { fontSize: '0.78rem', minHeight: 36, py: 0, textTransform: 'none', color: '#64748B' },
            '& .Mui-selected': { color: '#0891B2' },
            '& .MuiTabs-indicator': { bgcolor: '#0891B2', height: 2 },
          }}
        >
          <Tab label="Recent" />
          <Tab label="Templates" />
          <Tab label="Scheduled" />
        </Tabs>
        <Button
          variant="contained" size="small" startIcon={<Add />}
          onClick={() => setCreateOpen(true)}
          sx={{ bgcolor: '#0891B2', '&:hover': { bgcolor: '#0e7490' }, fontSize: '0.78rem' }}
        >
          Create Custom Report
        </Button>
      </Box>

      {/* Report list */}
      {tabReports.length === 0 ? (
        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', py: 8, gap: 1.5 }}>
          <Description sx={{ fontSize: 40, color: '#64748B' }} />
          <Typography sx={{ fontSize: '0.85rem', color: '#64748B' }}>No reports in this category yet</Typography>
        </Box>
      ) : (
        tabReports.map(r => <ReportCard key={r.report_id} report={r} />)
      )}

      {/* Create Custom Report Modal */}
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth
        PaperProps={{ sx: { bgcolor: '#111E2D', border: '1px solid rgba(255,255,255,0.08)' } }}>
        <DialogTitle sx={{ color: '#E2E8F0', fontSize: '0.95rem' }}>Create Custom Report</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          <TextField
            label="Report Name" size="small" fullWidth
            value={newName} onChange={e => setNewName(e.target.value)}
            InputProps={{ sx: { bgcolor: '#0D1B2A', fontSize: '0.82rem' } }}
            InputLabelProps={{ sx: { fontSize: '0.82rem', color: '#64748B' } }}
            sx={{ '& fieldset': { borderColor: 'rgba(255,255,255,0.1)' } }}
          />
          <FormControl size="small" fullWidth>
            <InputLabel sx={{ fontSize: '0.82rem', color: '#64748B' }}>Report Type</InputLabel>
            <Select
              value={newType} onChange={e => setNewType(e.target.value)} label="Report Type"
              sx={{ bgcolor: '#0D1B2A', fontSize: '0.82rem', '& fieldset': { borderColor: 'rgba(255,255,255,0.1)' } }}
            >
              {['ENERGY', 'THERMAL', 'CAPACITY', 'ALERTS', 'CUSTOM'].map(t => (
                <MenuItem key={t} value={t} sx={{ fontSize: '0.82rem' }}>{t}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <Typography sx={{ fontSize: '0.75rem', color: '#64748B' }}>
            The report will be queued for generation. You will see it in the Recent tab with status GENERATING.
            Download becomes available once generation is complete (Phase 2 feature).
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)} sx={{ color: '#94A3B8', fontSize: '0.78rem' }}>Cancel</Button>
          <Button onClick={handleCreate} disabled={!newName}
            variant="contained" sx={{ bgcolor: '#0891B2', '&:hover': { bgcolor: '#0e7490' }, fontSize: '0.78rem' }}>
            Create
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar open={!!snack} autoHideDuration={4000} onClose={() => setSnack('')}
        message={snack} anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }} />
    </PageShell>
  )
}
