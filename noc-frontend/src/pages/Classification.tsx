/**
 * pages/Classification.tsx
 * Classification Agent — replaces ClassificationReview.tsx in new dark sidebar design.
 * Shows: agent health banner, model accuracy trend, needs-review queue,
 * all recent results, confidence bars, inline correction workflow.
 */
import React, { useState, useMemo } from 'react'
import {
  Box, Typography, Chip, Card, CardContent, Button, LinearProgress,
  Select, MenuItem, FormControl, Snackbar, Tabs, Tab, Tooltip,
  CircularProgress,
} from '@mui/material'
import { DeviceHub, Circle as DotIcon, RateReview, Refresh } from '@mui/icons-material'
import { api } from '../lib/api'
import { mockClassStatus, mockClassResults } from '../mocks'
import { useApi, usePollingApi } from '../hooks/useApi'
import {
  PageShell, KpiTile, KpiRow, SectionCard, MockBanner, LoadingOverlay,
} from '../components/shared'
import { confidenceColor } from '../lib/theme'
import type { ClassResult } from '../lib/api'

const DEVICE_TYPES = [
  'Server', 'ToR-Switch', 'Core-Switch', 'Firewall', 'Load-Balancer',
  'Storage-Array', 'GPU-Server', 'PDU', 'UPS', 'CRAC', 'KVM-Switch',
  'Router', 'Out-of-Band-Manager', 'Unknown',
]

function ConfidenceBar({ score }: { score: number }) {
  const color = confidenceColor(score)
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 140 }}>
      <LinearProgress
        variant="determinate"
        value={score * 100}
        sx={{
          flex: 1, height: 6, borderRadius: 3,
          bgcolor: 'rgba(255,255,255,0.06)',
          '& .MuiLinearProgress-bar': { bgcolor: color, borderRadius: 3 },
        }}
      />
      <Typography sx={{ fontSize: '0.72rem', color, fontWeight: 600, minWidth: 36 }}>
        {(score * 100).toFixed(0)}%
      </Typography>
    </Box>
  )
}

function ResultCard({
  result,
  onFeedback,
}: {
  result: ClassResult
  onFeedback: (id: string, type: string) => void
}) {
  const [selectedType, setSelectedType] = useState(result.inferred_entity_type)
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(!!result.operator_feedback)

  const handleSubmit = async () => {
    setSubmitting(true)
    await onFeedback(result.result_id, selectedType)
    setSubmitted(true)
    setSubmitting(false)
  }

  return (
    <Card sx={{
      bgcolor: '#111E2D', mb: 1.5,
      borderLeft: `3px solid ${result.needs_review ? '#F59E0B' : 'rgba(255,255,255,0.06)'}`,
      transition: 'box-shadow 0.15s',
      '&:hover': { boxShadow: '0 0 0 1px rgba(8,145,178,0.15)' },
    }}>
      <CardContent sx={{ p: '12px 14px !important' }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 0.75 }}>
          <Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.25 }}>
              <Typography sx={{ fontSize: '0.82rem', fontWeight: 600, color: '#E2E8F0' }}>
                {result.entity_id}
              </Typography>
              {result.needs_review && (
                <Chip icon={<RateReview sx={{ fontSize: '11px !important' }} />} label="Needs Review"
                  size="small" sx={{ bgcolor: 'rgba(245,158,11,0.12)', color: '#F59E0B', fontSize: '0.62rem', height: 18 }} />
              )}
              {submitted && (
                <Chip label="Feedback Submitted" size="small"
                  sx={{ bgcolor: 'rgba(5,150,105,0.12)', color: '#059669', fontSize: '0.62rem', height: 18 }} />
              )}
            </Box>
            <Typography sx={{ fontSize: '0.7rem', color: '#64748B' }}>
              Inferred: <span style={{ color: '#E2E8F0', fontWeight: 600 }}>{result.inferred_entity_type}</span> ·{' '}
              Classified: {new Date(result.classified_at).toLocaleString()} ·{' '}
              Run: {result.mlflow_run_id?.slice(-8) ?? 'N/A'}
            </Typography>
          </Box>
          <ConfidenceBar score={result.confidence_score} />
        </Box>

        {/* Correction input */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mt: 0.5 }}>
          <FormControl size="small" sx={{ minWidth: 180 }}>
            <Select
              value={selectedType}
              onChange={e => setSelectedType(e.target.value)}
              disabled={submitted}
              sx={{ bgcolor: '#0D1B2A', fontSize: '0.78rem', '& fieldset': { borderColor: 'rgba(255,255,255,0.1)' } }}
            >
              {DEVICE_TYPES.map(t => (
                <MenuItem key={t} value={t} sx={{ fontSize: '0.78rem' }}>{t}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <Button
            size="small"
            variant="outlined"
            disabled={submitted || submitting || selectedType === result.inferred_entity_type}
            onClick={handleSubmit}
            sx={{ fontSize: '0.72rem', py: 0.3, px: 1.25, color: '#0891B2', borderColor: 'rgba(8,145,178,0.4)', '&:hover': { bgcolor: 'rgba(8,145,178,0.08)' } }}
          >
            {submitting ? <CircularProgress size={12} /> : 'Submit Correction'}
          </Button>
          {result.operator_feedback && (
            <Typography sx={{ fontSize: '0.68rem', color: '#64748B' }}>
              Previous: <span style={{ color: '#94A3B8' }}>{result.operator_feedback}</span>
            </Typography>
          )}
        </Box>
      </CardContent>
    </Card>
  )
}

export default function Classification() {
  const [tab, setTab] = useState(0)
  const [snack, setSnack] = useState('')
  const [results, setResults] = useState<ClassResult[]>([])
  const [retraining, setRetraining] = useState(false)

  const { data: status } = usePollingApi(() => api.classification.status(), mockClassStatus, 60000)
  const { data: resultsData, loading } = useApi(
    () => api.classification.results({ limit: 50 }),
    () => ({ items: mockClassResults(), total: 20 }),
  )

  React.useEffect(() => {
    if (resultsData) setResults(resultsData.items)
  }, [resultsData])

  const handleFeedback = async (id: string, type: string) => {
    try {
      await api.classification.feedback(id, { operator_feedback: type })
    } catch { /* mock */ }
    setSnack(`Correction submitted: ${type}`)
  }

  const handleRetrain = async () => {
    setRetraining(true)
    try { await api.classification.retrain() } catch { /* mock */ }
    setTimeout(() => setRetraining(false), 2000)
    setSnack('Retraining triggered — model will update shortly')
  }

  const displayResults = tab === 0
    ? results.filter(r => r.needs_review)
    : results

  const accuracy = status?.val_accuracy ?? 0

  return (
    <PageShell title="Classification Agent" subtitle="Device classification model status, results, and operator feedback">
      <MockBanner />

      {/* Agent health banner */}
      <Box sx={{ display: 'flex', gap: 3, mb: 2, p: 1.5, bgcolor: '#111E2D', borderRadius: 2, border: '1px solid rgba(255,255,255,0.06)', flexWrap: 'wrap', alignItems: 'center' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
          <DotIcon sx={{ fontSize: 10, color: status?.model_loaded ? '#059669' : '#E05A5A' }} />
          <Typography sx={{ fontSize: '0.75rem', color: '#94A3B8' }}>
            Model: <span style={{ color: '#E2E8F0', fontWeight: 600 }}>{status?.model_loaded ? 'Loaded' : 'Not loaded'}</span>
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Typography sx={{ fontSize: '0.75rem', color: '#94A3B8' }}>Accuracy:</Typography>
          <LinearProgress
            variant="determinate" value={accuracy * 100}
            sx={{ width: 80, height: 6, borderRadius: 3, bgcolor: 'rgba(255,255,255,0.06)', '& .MuiLinearProgress-bar': { bgcolor: confidenceColor(accuracy), borderRadius: 3 } }}
          />
          <Typography sx={{ fontSize: '0.75rem', color: confidenceColor(accuracy), fontWeight: 700 }}>
            {(accuracy * 100).toFixed(1)}%
          </Typography>
        </Box>
        <Typography sx={{ fontSize: '0.75rem', color: '#94A3B8' }}>
          Classified: <span style={{ color: '#E2E8F0', fontWeight: 600 }}>{status?.classified?.toLocaleString()}</span>
        </Typography>
        <Typography sx={{ fontSize: '0.75rem', color: '#94A3B8' }}>
          Needs Review: <span style={{ color: '#F59E0B', fontWeight: 600 }}>{status?.needs_review}</span>
        </Typography>
        <Typography sx={{ fontSize: '0.72rem', color: '#64748B' }}>
          Run ID: {status?.model_run_id?.slice(-12) ?? 'N/A'}
        </Typography>
        <Box sx={{ ml: 'auto' }}>
          <Button
            size="small"
            startIcon={retraining ? <CircularProgress size={12} /> : <Refresh sx={{ fontSize: 14 }} />}
            onClick={handleRetrain}
            disabled={retraining}
            sx={{ fontSize: '0.72rem', py: 0.25, px: 1, color: '#A78BFA', border: '1px solid rgba(167,139,250,0.3)', '&:hover': { bgcolor: 'rgba(167,139,250,0.08)' } }}
          >
            Trigger Retrain
          </Button>
        </Box>
      </Box>

      {/* KPIs */}
      <KpiRow>
        <KpiTile label="Model Accuracy" value={`${(accuracy * 100).toFixed(1)}`} unit="%" color={confidenceColor(accuracy)} />
        <KpiTile label="Total Classified" value={status?.classified?.toLocaleString() ?? '—'} color="#0891B2" />
        <KpiTile label="Needs Review" value={status?.needs_review ?? 0} color="#F59E0B" />
        <KpiTile label="Avg Confidence" value={
          results.length ? `${(results.reduce((s, r) => s + r.confidence_score, 0) / results.length * 100).toFixed(0)}` : '—'
        } unit="%" color="#059669" />
      </KpiRow>

      {/* Tab bar */}
      <Tabs value={tab} onChange={(_, v) => setTab(v)}
        sx={{ mb: 2, borderBottom: '1px solid rgba(255,255,255,0.06)', '& .MuiTab-root': { fontSize: '0.78rem', minHeight: 36, py: 0, textTransform: 'none', color: '#64748B' }, '& .Mui-selected': { color: '#0891B2' }, '& .MuiTabs-indicator': { bgcolor: '#0891B2', height: 2 } }}>
        <Tab label={`Needs Review (${results.filter(r => r.needs_review).length})`} />
        <Tab label={`All Results (${results.length})`} />
      </Tabs>

      {/* Result cards */}
      {loading ? <LoadingOverlay /> : (
        displayResults.length === 0 ? (
          <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', py: 8, gap: 1.5 }}>
            <DeviceHub sx={{ fontSize: 40, color: '#64748B' }} />
            <Typography sx={{ fontSize: '0.85rem', color: '#64748B' }}>
              {tab === 0 ? 'No items need review' : 'No classification results yet'}
            </Typography>
          </Box>
        ) : (
          displayResults.map(r => (
            <ResultCard key={r.result_id} result={r} onFeedback={handleFeedback} />
          ))
        )
      )}

      <Snackbar open={!!snack} autoHideDuration={3000} onClose={() => setSnack('')}
        message={snack} anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }} />
    </PageShell>
  )
}
