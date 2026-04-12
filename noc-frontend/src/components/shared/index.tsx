/**
 * components/shared/index.tsx
 * Reusable atomic components used across all pages.
 */
import React from 'react'
import {
  Box, Typography, Card, CardContent, Chip, CircularProgress,
  Alert, Skeleton,
} from '@mui/material'
import { TrendingUp, TrendingDown, TrendingFlat } from '@mui/icons-material'
import { USE_MOCKS } from '../../mocks'
import { SIDEBAR_WIDTH, TOPBAR_HEIGHT } from '../../lib/theme'

// ── MockBanner ────────────────────────────────────────────────────────────────
export function MockBanner() {
  if (!USE_MOCKS) return null
  return (
    <Alert
      severity="info"
      sx={{
        mb: 2, py: 0.5, fontSize: '0.75rem',
        bgcolor: 'rgba(8,145,178,0.08)',
        border: '1px solid rgba(8,145,178,0.2)',
        '& .MuiAlert-icon': { fontSize: 16 },
      }}
    >
      Mock data active — set <code>VITE_USE_MOCKS=false</code> to use live API
    </Alert>
  )
}

// ── PageShell ─────────────────────────────────────────────────────────────────
/** Wraps page content with correct left offset and top padding for layout */
export function PageShell({ children, title, subtitle }: {
  children: React.ReactNode
  title?: string
  subtitle?: string
}) {
  return (
    <Box sx={{
      ml: `${SIDEBAR_WIDTH}px`,
      mt: `${TOPBAR_HEIGHT}px`,
      p: 3,
      minHeight: `calc(100vh - ${TOPBAR_HEIGHT}px)`,
      bgcolor: '#0D1B2A',
    }}>
      {(title || subtitle) && (
        <Box sx={{ mb: 2.5 }}>
          {title && (
            <Typography variant="h2" sx={{ color: '#E2E8F0', fontWeight: 600, fontSize: '1.2rem' }}>
              {title}
            </Typography>
          )}
          {subtitle && (
            <Typography sx={{ color: '#64748B', fontSize: '0.8rem', mt: 0.25 }}>
              {subtitle}
            </Typography>
          )}
        </Box>
      )}
      {children}
    </Box>
  )
}

// ── KpiTile ───────────────────────────────────────────────────────────────────
interface KpiTileProps {
  label: string
  value: string | number
  unit?: string
  delta?: number      // positive = up, negative = down
  deltaLabel?: string
  color?: string
  loading?: boolean
}

export function KpiTile({ label, value, unit, delta, deltaLabel, color = '#0891B2', loading = false }: KpiTileProps) {
  const trendIcon = delta === undefined ? null
    : delta > 0 ? <TrendingUp sx={{ fontSize: 14 }} />
    : delta < 0 ? <TrendingDown sx={{ fontSize: 14 }} />
    : <TrendingFlat sx={{ fontSize: 14 }} />

  const trendColor = delta === undefined ? '#64748B'
    : delta > 0 ? '#059669' : delta < 0 ? '#E05A5A' : '#64748B'

  return (
    <Card sx={{ bgcolor: '#111E2D', flex: 1, minWidth: 160 }}>
      <CardContent sx={{ p: '14px !important' }}>
        {loading ? (
          <>
            <Skeleton variant="text" width="60%" sx={{ bgcolor: 'rgba(255,255,255,0.06)' }} />
            <Skeleton variant="text" width="80%" height={40} sx={{ bgcolor: 'rgba(255,255,255,0.06)' }} />
          </>
        ) : (
          <>
            <Typography sx={{ fontSize: '0.72rem', color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.5px', mb: 0.5 }}>
              {label}
            </Typography>
            <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 0.5 }}>
              <Typography sx={{ fontSize: '1.6rem', fontWeight: 700, color, lineHeight: 1.1 }}>
                {value}
              </Typography>
              {unit && (
                <Typography sx={{ fontSize: '0.78rem', color: '#64748B', fontWeight: 500 }}>
                  {unit}
                </Typography>
              )}
            </Box>
            {delta !== undefined && (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.5, color: trendColor }}>
                {trendIcon}
                <Typography sx={{ fontSize: '0.7rem', color: trendColor }}>
                  {delta > 0 ? '+' : ''}{delta}{deltaLabel || '%'} vs last period
                </Typography>
              </Box>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

// ── SectionCard ───────────────────────────────────────────────────────────────
export function SectionCard({ title, children, action, sx }: {
  title?: string
  children: React.ReactNode
  action?: React.ReactNode
  sx?: object
}) {
  return (
    <Card sx={{ bgcolor: '#111E2D', ...sx }}>
      {(title || action) && (
        <Box sx={{ px: 2, pt: 1.5, pb: 1, display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
          {title && (
            <Typography sx={{ fontSize: '0.82rem', fontWeight: 600, color: '#E2E8F0' }}>
              {title}
            </Typography>
          )}
          {action}
        </Box>
      )}
      <CardContent sx={{ p: '14px !important' }}>
        {children}
      </CardContent>
    </Card>
  )
}

// ── StatusChip ────────────────────────────────────────────────────────────────
const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  NORMAL:      { bg: 'rgba(5,150,105,0.15)',   text: '#059669' },
  ONLINE:      { bg: 'rgba(5,150,105,0.15)',   text: '#059669' },
  ACTIVE:      { bg: 'rgba(5,150,105,0.15)',   text: '#059669' },
  READY:       { bg: 'rgba(5,150,105,0.15)',   text: '#059669' },
  WARNING:     { bg: 'rgba(245,158,11,0.15)',  text: '#F59E0B' },
  DEGRADED:    { bg: 'rgba(245,158,11,0.15)',  text: '#F59E0B' },
  ACKNOWLEDGED:{ bg: 'rgba(245,158,11,0.15)',  text: '#F59E0B' },
  GENERATING:  { bg: 'rgba(245,158,11,0.15)',  text: '#F59E0B' },
  CRITICAL:    { bg: 'rgba(224,90,90,0.15)',   text: '#E05A5A' },
  OFFLINE:     { bg: 'rgba(224,90,90,0.15)',   text: '#E05A5A' },
  FAILED:      { bg: 'rgba(224,90,90,0.15)',   text: '#E05A5A' },
  RESOLVED:    { bg: 'rgba(100,116,139,0.15)', text: '#94A3B8' },
  PENDING:     { bg: 'rgba(100,116,139,0.15)', text: '#94A3B8' },
  OPEN:        { bg: 'rgba(8,145,178,0.15)',   text: '#0891B2' },
  MINOR:       { bg: 'rgba(8,145,178,0.15)',   text: '#0891B2' },
  INFO:        { bg: 'rgba(8,145,178,0.15)',   text: '#0891B2' },
}

export function StatusChip({ status }: { status: string }) {
  const c = STATUS_COLORS[status] || { bg: 'rgba(100,116,139,0.15)', text: '#94A3B8' }
  return (
    <Chip
      label={status}
      size="small"
      sx={{ bgcolor: c.bg, color: c.text, fontWeight: 600, fontSize: '0.65rem', height: 20 }}
    />
  )
}

// ── LoadingOverlay ────────────────────────────────────────────────────────────
export function LoadingOverlay() {
  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 8 }}>
      <CircularProgress size={32} sx={{ color: '#0891B2' }} />
    </Box>
  )
}

// ── ErrorAlert ────────────────────────────────────────────────────────────────
export function ErrorAlert({ message }: { message: string }) {
  return (
    <Alert severity="error" sx={{ bgcolor: 'rgba(224,90,90,0.1)', border: '1px solid rgba(224,90,90,0.2)' }}>
      {message}
    </Alert>
  )
}

// ── KpiRow ────────────────────────────────────────────────────────────────────
/** Horizontal row of 4 KPI tiles */
export function KpiRow({ children }: { children: React.ReactNode }) {
  return (
    <Box sx={{ display: 'flex', gap: 2, mb: 2, flexWrap: 'wrap' }}>
      {children}
    </Box>
  )
}
