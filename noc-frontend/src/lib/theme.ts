import { createTheme } from '@mui/material/styles'

export const nocTheme = createTheme({
  palette: {
    mode: 'dark',
    primary:   { main: '#0891B2' },
    secondary: { main: '#059669' },
    error:     { main: '#E05A5A' },
    warning:   { main: '#F59E0B' },
    success:   { main: '#059669' },
    background: { default: '#0D1B2A', paper: '#111E2D' },
    text: { primary: '#E2E8F0', secondary: '#94A3B8' },
  },
  typography: {
    fontFamily: '"Inter", "Roboto", "Arial", sans-serif',
    fontSize: 13,
    h1: { fontSize: '1.5rem', fontWeight: 600 },
    h2: { fontSize: '1.25rem', fontWeight: 600 },
    h3: { fontSize: '1.1rem',  fontWeight: 600 },
    h4: { fontSize: '1rem',    fontWeight: 500 },
    body2: { fontSize: '0.8rem' },
    caption: { fontSize: '0.75rem', color: '#94A3B8' },
  },
  components: {
    MuiCard: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          border: '1px solid rgba(255,255,255,0.06)',
          borderRadius: 8,
        },
      },
    },
    MuiChip: {
      styleOverrides: { root: { borderRadius: 4, fontWeight: 600, fontSize: '0.7rem' } },
    },
    MuiTableCell: {
      styleOverrides: { root: { borderColor: 'rgba(255,255,255,0.05)' } },
    },
  },
})

export const healthColor = (status: string, score: number): string => {
  if (status === 'OFFLINE') return '#E05A5A'
  if (status === 'DEGRADED') return '#F59E0B'
  if (score >= 0.85) return '#059669'
  if (score >= 0.60) return '#F59E0B'
  return '#E05A5A'
}

export const severityColor = (sev: string): string => ({
  CRITICAL: '#E05A5A',
  MAJOR:    '#F59E0B',
  MINOR:    '#0891B2',
  WARNING:  '#F59E0B',
  INFO:     '#64748B',
}[sev] || '#64748B')
