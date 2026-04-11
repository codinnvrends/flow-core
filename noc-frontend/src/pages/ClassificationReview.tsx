import React, { useState, useEffect } from 'react'
import {
  Box, Typography, Card, Table, TableBody, TableCell, TableHead,
  TableRow, Chip, Alert, CircularProgress, Button, Dialog,
  DialogTitle, DialogContent, DialogActions, TextField, FormControl,
  InputLabel, Select, MenuItem, Tooltip, LinearProgress,
} from '@mui/material'
import { DeviceHub as ClassIcon, RateReview as ReviewIcon } from '@mui/icons-material'
import axios from 'axios'

const INSIGHTS_BASE = import.meta.env.VITE_INSIGHTS_API_URL || 'http://localhost:8888/api/insights'

const DEVICE_TYPES = [
  'Server', 'ToR-Switch', 'Core-Switch', 'Firewall', 'Load-Balancer',
  'Storage-Array', 'GPU-Server', 'PDU', 'UPS', 'CRAC', 'KVM-Switch',
  'Router', 'Out-of-Band-Manager', 'Unknown',
]

interface ClassResult {
  result_id: string
  entity_id: string
  tenant_id: string
  inferred_entity_type: string
  capability_flags: Record<string, any> | string
  confidence_score: number
  needs_review: boolean
  mlflow_run_id: string | null
  classified_at: string
  operator_feedback: string | null
  feedback_at: string | null
}

function useClassificationResults(tenantId: string, needsReview: boolean | null) {
  const [results, setResults] = useState<ClassResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const params: any = { tenant_id: tenantId, limit: 100 }
      if (needsReview !== null) params.needs_review = needsReview
      const r = await axios.get(`${INSIGHTS_BASE}/classification/results`, { params })
      setResults(r.data.items || [])
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [tenantId, needsReview])
  return { results, loading, error, reload: load }
}

function ConfidenceBar({ score }: { score: number }) {
  const color = score >= 0.9 ? '#059669' : score >= 0.7 ? '#F59E0B' : '#E05A5A'
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
      <LinearProgress variant="determinate" value={score * 100}
        sx={{ flex: 1, height: 6, borderRadius: 3, bgcolor: 'rgba(255,255,255,0.06)',
              '& .MuiLinearProgress-bar': { bgcolor: color, borderRadius: 3 } }} />
      <Typography variant="caption" sx={{ color, fontWeight: 700, minWidth: 32 }}>
        {(score * 100).toFixed(0)}%
      </Typography>
    </Box>
  )
}

function CapabilityChips({ caps }: { caps: Record<string, any> | string }) {
  let parsed: Record<string, any> = {}
  try {
    parsed = typeof caps === 'string' ? JSON.parse(caps) : (caps || {})
  } catch { return null }

  const trueKeys = Object.entries(parsed).filter(([, v]) => v === true).map(([k]) => k)
  if (!trueKeys.length) return null

  return (
    <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
      {trueKeys.slice(0, 3).map(k => (
        <Chip key={k} label={k.replace(/_/g, ' ')} size="small"
          sx={{ height: 16, fontSize: '0.6rem', bgcolor: 'rgba(8,145,178,0.1)', color: '#0891B2' }} />
      ))}
      {trueKeys.length > 3 && (
        <Typography variant="caption" sx={{ color: 'text.secondary' }}>
          +{trueKeys.length - 3}
        </Typography>
      )}
    </Box>
  )
}

export default function ClassificationReview({ tenantId }: { tenantId: string }) {
  const [reviewOnly, setReviewOnly] = useState(true)
  const [feedbackItem, setFeedbackItem] = useState<ClassResult | null>(null)
  const [correctedType, setCorrectedType] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [successMsg, setSuccessMsg] = useState('')

  const { results, loading, error, reload } = useClassificationResults(
    tenantId, reviewOnly ? true : null
  )

  const submitFeedback = async () => {
    if (!feedbackItem || !correctedType) return
    setSubmitting(true)
    try {
      await axios.patch(
        `${INSIGHTS_BASE}/classification/results/${feedbackItem.result_id}/feedback`,
        null,
        { params: { corrected_type: correctedType } }
      )
      setSuccessMsg(`Feedback recorded: ${correctedType}`)
      setFeedbackItem(null)
      setCorrectedType('')
      reload()
    } catch (e: any) {
      console.error(e)
    } finally {
      setSubmitting(false)
    }
  }

  // Stats
  const total = results.length
  const pendingReview = results.filter(r => r.needs_review && !r.operator_feedback).length
  const corrected = results.filter(r => r.operator_feedback).length
  const avgConfidence = total ? results.reduce((s, r) => s + r.confidence_score, 0) / total : 0

  return (
    <Box sx={{ p: 2 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
        <ClassIcon sx={{ color: '#059669' }} />
        <Typography variant="h2">Classification Review</Typography>
      </Box>

      {/* Summary */}
      <Box sx={{ display: 'flex', gap: 1.5, mb: 2, flexWrap: 'wrap' }}>
        {[
          { label: 'Total classified', value: total,         color: '#94A3B8' },
          { label: 'Pending review',   value: pendingReview, color: '#F59E0B' },
          { label: 'Operator corrected', value: corrected,  color: '#059669' },
          { label: 'Avg confidence',   value: `${(avgConfidence * 100).toFixed(0)}%`, color: '#0891B2' },
        ].map(s => (
          <Card key={s.label} sx={{ minWidth: 130, borderLeft: `3px solid ${s.color}` }}>
            <Box sx={{ p: '10px 12px', textAlign: 'center' }}>
              <Typography variant="h2" sx={{ color: s.color }}>{s.value}</Typography>
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>{s.label}</Typography>
            </Box>
          </Card>
        ))}
      </Box>

      {successMsg && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSuccessMsg('')}>
          {successMsg}
        </Alert>
      )}

      {/* Filter toggle */}
      <Box sx={{ display: 'flex', gap: 1, mb: 2, alignItems: 'center' }}>
        <Button
          variant={reviewOnly ? 'contained' : 'outlined'}
          size="small" startIcon={<ReviewIcon />}
          onClick={() => setReviewOnly(true)}>
          Needs review
        </Button>
        <Button
          variant={!reviewOnly ? 'contained' : 'outlined'}
          size="small" onClick={() => setReviewOnly(false)}>
          All classifications
        </Button>
        <Typography variant="caption" sx={{ color: 'text.secondary', ml: 'auto' }}>
          {loading ? 'Loading…' : `${results.length} results`}
        </Typography>
      </Box>

      {error && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Cannot load classification results ({error})
        </Alert>
      )}

      {/* Table */}
      <Card>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Entity ID</TableCell>
              <TableCell>Inferred type</TableCell>
              <TableCell>Capabilities</TableCell>
              <TableCell sx={{ minWidth: 140 }}>Confidence</TableCell>
              <TableCell>Review needed</TableCell>
              <TableCell>Operator correction</TableCell>
              <TableCell>Classified at</TableCell>
              <TableCell align="right">Action</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={8} align="center" sx={{ py: 4 }}>
                  <CircularProgress size={24} />
                </TableCell>
              </TableRow>
            ) : results.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} align="center" sx={{ py: 3 }}>
                  <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                    {reviewOnly
                      ? 'No items pending review — classification confidence is above threshold.'
                      : 'No classification results yet. Waiting for discovery data.'}
                  </Typography>
                </TableCell>
              </TableRow>
            ) : results.map(r => (
              <TableRow key={r.result_id}
                sx={{ '&:hover': { bgcolor: 'rgba(255,255,255,0.02)' },
                      bgcolor: r.needs_review && !r.operator_feedback
                        ? 'rgba(245,158,11,0.04)' : undefined }}>
                <TableCell>
                  <Typography variant="caption"
                    sx={{ fontFamily: 'monospace', fontSize: '0.68rem' }}>
                    {r.entity_id.slice(0, 8)}…
                  </Typography>
                </TableCell>
                <TableCell>
                  <Chip label={r.inferred_entity_type} size="small"
                    sx={{ bgcolor: 'rgba(5,150,105,0.1)', color: '#059669',
                          fontSize: '0.7rem', fontWeight: 600 }} />
                </TableCell>
                <TableCell>
                  <CapabilityChips caps={r.capability_flags} />
                </TableCell>
                <TableCell><ConfidenceBar score={r.confidence_score} /></TableCell>
                <TableCell>
                  {r.needs_review ? (
                    <Chip label="Review" size="small"
                      sx={{ bgcolor: '#F59E0B22', color: '#F59E0B',
                            fontSize: '0.65rem', fontWeight: 700, height: 18 }} />
                  ) : (
                    <Chip label="OK" size="small"
                      sx={{ bgcolor: '#05966922', color: '#059669',
                            fontSize: '0.65rem', height: 18 }} />
                  )}
                </TableCell>
                <TableCell>
                  {r.operator_feedback ? (
                    <Box>
                      <Chip label={r.operator_feedback} size="small"
                        sx={{ bgcolor: 'rgba(8,145,178,0.1)', color: '#0891B2',
                              fontSize: '0.65rem', height: 18, fontWeight: 600 }} />
                      {r.feedback_at && (
                        <Typography variant="caption"
                          sx={{ display: 'block', color: 'text.secondary', mt: 0.25 }}>
                          {new Date(r.feedback_at).toLocaleDateString()}
                        </Typography>
                      )}
                    </Box>
                  ) : (
                    <Typography variant="caption" sx={{ color: 'text.secondary' }}>—</Typography>
                  )}
                </TableCell>
                <TableCell>
                  <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                    {new Date(r.classified_at).toLocaleString()}
                  </Typography>
                </TableCell>
                <TableCell align="right">
                  {!r.operator_feedback && (
                    <Button size="small" variant="outlined" sx={{ fontSize: '0.7rem', py: 0.25 }}
                      onClick={() => { setFeedbackItem(r); setCorrectedType(r.inferred_entity_type) }}>
                      Correct
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      {/* Feedback dialog */}
      <Dialog open={!!feedbackItem} onClose={() => setFeedbackItem(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Correct classification</DialogTitle>
        <DialogContent sx={{ pt: 2 }}>
          {feedbackItem && (
            <>
              <Typography variant="body2" sx={{ mb: 0.5 }}>
                Entity: <code style={{ fontSize: '0.75rem' }}>{feedbackItem.entity_id}</code>
              </Typography>
              <Typography variant="body2" sx={{ mb: 2 }}>
                Current type: <strong>{feedbackItem.inferred_entity_type}</strong>
                {' '}({(feedbackItem.confidence_score * 100).toFixed(0)}% confidence)
              </Typography>
              <FormControl fullWidth size="small">
                <InputLabel>Correct device type</InputLabel>
                <Select value={correctedType} label="Correct device type"
                  onChange={e => setCorrectedType(e.target.value)}>
                  {DEVICE_TYPES.map(t => (
                    <MenuItem key={t} value={t}>{t}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <Typography variant="caption" sx={{ color: 'text.secondary', mt: 1, display: 'block' }}>
                Your correction will be queued for the next model retraining run (FR-CC-04).
              </Typography>
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFeedbackItem(null)}>Cancel</Button>
          <Button variant="contained" disabled={!correctedType || submitting}
            onClick={submitFeedback}>
            {submitting ? <CircularProgress size={16} /> : 'Submit correction'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
