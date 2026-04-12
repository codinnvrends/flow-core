/**
 * components/layout/TopBar.tsx
 * Persistent 64px top bar: facility name, POC status, health indicator, alert count, user avatar.
 */
import React from 'react'
import {
  AppBar, Toolbar, Typography, Chip, Box, IconButton, Avatar, Tooltip,
} from '@mui/material'
import {
  NotificationsNone as BellIcon,
  Circle as DotIcon,
  AccountCircle as UserIcon,
} from '@mui/icons-material'
import { SIDEBAR_WIDTH, TOPBAR_HEIGHT } from '../../lib/theme'

interface TopBarProps {
  facilityName?: string
  pocStatus?: string
  onTrack?: boolean
  alertCount?: number
  pue?: number
}

export default function TopBar({
  facilityName = 'FlowCore EU-West Alpha',
  pocStatus    = 'POC Active',
  onTrack      = true,
  alertCount   = 0,
  pue          = 0,
}: TopBarProps) {
  const healthColor = pue < 1.5 ? '#059669' : pue < 1.8 ? '#F59E0B' : '#E05A5A'

  return (
    <AppBar
      position="fixed"
      elevation={0}
      sx={{
        left: SIDEBAR_WIDTH,
        width: `calc(100% - ${SIDEBAR_WIDTH}px)`,
        height: TOPBAR_HEIGHT,
        bgcolor: '#0D1B2A',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
        zIndex: 1100,
      }}
    >
      <Toolbar sx={{ height: TOPBAR_HEIGHT, minHeight: `${TOPBAR_HEIGHT}px !important`, px: 3, gap: 2 }}>
        {/* Facility name */}
        <Typography sx={{ fontWeight: 600, fontSize: '0.95rem', color: '#E2E8F0' }}>
          {facilityName}
        </Typography>

        {/* POC period badge */}
        <Chip
          label={pocStatus}
          size="small"
          sx={{ bgcolor: 'rgba(8,145,178,0.15)', color: '#0891B2', fontWeight: 600, fontSize: '0.68rem' }}
        />

        {onTrack && (
          <Chip
            label="On Track"
            size="small"
            sx={{ bgcolor: 'rgba(5,150,105,0.15)', color: '#059669', fontWeight: 600, fontSize: '0.68rem' }}
          />
        )}

        <Box sx={{ flex: 1 }} />

        {/* Global health indicator */}
        {pue > 0 && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, mr: 1 }}>
            <DotIcon sx={{ fontSize: 10, color: healthColor }} />
            <Typography sx={{ fontSize: '0.75rem', color: '#94A3B8' }}>
              PUE {pue.toFixed(2)}
            </Typography>
          </Box>
        )}

        {/* Alert bell */}
        <Tooltip title={`${alertCount} active alerts`}>
          <IconButton size="small" sx={{ position: 'relative', color: alertCount > 0 ? '#E05A5A' : '#64748B' }}>
            <BellIcon fontSize="small" />
            {alertCount > 0 && (
              <Box sx={{
                position: 'absolute', top: 2, right: 2,
                width: 8, height: 8, borderRadius: '50%',
                bgcolor: '#E05A5A',
              }} />
            )}
          </IconButton>
        </Tooltip>

        {/* User avatar */}
        <Avatar sx={{ width: 30, height: 30, bgcolor: 'rgba(8,145,178,0.2)', cursor: 'pointer' }}>
          <UserIcon sx={{ fontSize: 18, color: '#0891B2' }} />
        </Avatar>
      </Toolbar>
    </AppBar>
  )
}
