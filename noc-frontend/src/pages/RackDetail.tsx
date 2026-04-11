import React, { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { gql, useQuery } from '@apollo/client'
import {
  Box, Typography, Chip, Button, Grid, Card, CardContent,
  Table, TableBody, TableCell, TableHead, TableRow,
  CircularProgress, Alert, Divider, Tooltip,
} from '@mui/material'
import { ArrowBack as BackIcon } from '@mui/icons-material'
import cytoscape from 'cytoscape'
import * as d3 from 'd3'
import { healthColor } from '../lib/theme'

// ── GraphQL ───────────────────────────────────────────────────────────────────

const RACK_DETAIL_QUERY = gql`
  query RackDetail($entityId: String!) {
    entity(entityId: $entityId) {
      entityId canonicalName entityClass operationalStatus
      healthScore activeAlertCount criticalityLevel redundancyPosture
      canonicalType lastSeenAt
    }
    topologySubgraph(entityId: $entityId, depth: 2) {
      entities {
        entityId canonicalName entityClass operationalStatus
        healthScore activeAlertCount
      }
      relationships {
        fromEntityId toEntityId relationshipType
      }
    }
  }
`

const METRIC_QUERY = gql`
  query MetricHistory($entityId: String!, $metricId: String!, $hours: Int) {
    metricHistory(entityId: $entityId, metricId: $metricId, hours: $hours) {
      timestamp value qualityFlag
    }
  }
`

// ── Cytoscape topology ────────────────────────────────────────────────────────

const CY_STYLE: cytoscape.Stylesheet[] = [
  {
    selector: 'node',
    style: {
      'background-color': '#1E3A5F',
      'border-color': '#0891B2',
      'border-width': 1.5,
      label: 'data(label)',
      color: '#E2E8F0',
      'font-size': 9,
      'text-valign': 'bottom',
      'text-margin-y': 4,
      width: 36, height: 36,
    },
  },
  {
    selector: 'node[status = "OFFLINE"]',
    style: { 'background-color': '#3D1515', 'border-color': '#E05A5A' },
  },
  {
    selector: 'node[status = "DEGRADED"]',
    style: { 'background-color': '#3D2E0A', 'border-color': '#F59E0B' },
  },
  {
    selector: 'node[isRoot = "true"]',
    style: {
      'background-color': '#0C3050',
      'border-color': '#0891B2',
      'border-width': 3,
      width: 48, height: 48,
    },
  },
  {
    selector: 'edge',
    style: {
      'line-color': '#1E3A5F',
      'target-arrow-color': '#0891B2',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      width: 1.5,
      label: 'data(relType)',
      'font-size': 7,
      color: '#64748B',
      'text-rotation': 'autorotate',
    },
  },
]

function TopologyGraph({
  entityId,
  entities,
  relationships,
}: {
  entityId: string
  entities: any[]
  relationships: any[]
}) {
  const ref = useRef<HTMLDivElement>(null)
  const cyRef = useRef<cytoscape.Core | null>(null)

  useEffect(() => {
    if (!ref.current || !entities.length) return

    const nodes = entities.map(e => ({
      data: {
        id: e.entityId,
        label: e.canonicalName.length > 14 ? e.canonicalName.slice(0, 13) + '…' : e.canonicalName,
        entityClass: e.entityClass,
        status: e.operationalStatus || 'UNKNOWN',
        isRoot: e.entityId === entityId ? 'true' : 'false',
      },
    }))

    const edges = relationships.map((r, i) => ({
      data: {
        id: `e${i}`,
        source: r.fromEntityId,
        target: r.toEntityId,
        relType: r.relationshipType,
      },
    }))

    if (cyRef.current) {
      cyRef.current.destroy()
    }

    cyRef.current = cytoscape({
      container: ref.current,
      elements: { nodes, edges },
      style: CY_STYLE,
      layout: { name: 'cose', animate: false, padding: 20, randomize: false },
      userZoomingEnabled: true,
      userPanningEnabled: true,
      boxSelectionEnabled: false,
    })

    return () => { cyRef.current?.destroy() }
  }, [entities, relationships, entityId])

  return (
    <Box ref={ref}
         sx={{ width: '100%', height: 320, bgcolor: '#080F18', borderRadius: 1,
               border: '1px solid rgba(255,255,255,0.06)' }} />
  )
}

// ── D3 metric sparkline ───────────────────────────────────────────────────────

function MetricSparkline({ data, color = '#0891B2' }: { data: { timestamp: string; value: number }[]; color?: string }) {
  const ref = useRef<SVGSVGElement>(null)

  useEffect(() => {
    if (!ref.current || !data.length) return
    const svg = d3.select(ref.current)
    svg.selectAll('*').remove()

    const W = ref.current.clientWidth || 280
    const H = 60
    const margin = { top: 6, right: 8, bottom: 16, left: 32 }
    const w = W - margin.left - margin.right
    const h = H - margin.top - margin.bottom

    const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)

    const x = d3.scaleTime().domain(d3.extent(data, d => new Date(d.timestamp)) as [Date, Date]).range([0, w])
    const y = d3.scaleLinear().domain([0, d3.max(data, d => d.value) ?? 100]).nice().range([h, 0])

    // Area fill
    const area = d3.area<{ timestamp: string; value: number }>()
      .x(d => x(new Date(d.timestamp)))
      .y0(h)
      .y1(d => y(d.value))
      .curve(d3.curveMonotoneX)

    g.append('path').datum(data).attr('fill', `${color}25`).attr('d', area)

    // Line
    const line = d3.line<{ timestamp: string; value: number }>()
      .x(d => x(new Date(d.timestamp)))
      .y(d => y(d.value))
      .curve(d3.curveMonotoneX)

    g.append('path').datum(data)
      .attr('fill', 'none')
      .attr('stroke', color)
      .attr('stroke-width', 1.5)
      .attr('d', line)

    // X axis (minimal)
    g.append('g').attr('transform', `translate(0,${h})`)
      .call(d3.axisBottom(x).ticks(4).tickSize(2))
      .call(ax => {
        ax.select('.domain').attr('stroke', '#1E3A5F')
        ax.selectAll('text').attr('fill', '#64748B').attr('font-size', 7)
        ax.selectAll('.tick line').attr('stroke', '#1E3A5F')
      })

    // Y axis
    g.append('g').call(d3.axisLeft(y).ticks(3).tickSize(2))
      .call(ax => {
        ax.select('.domain').attr('stroke', '#1E3A5F')
        ax.selectAll('text').attr('fill', '#64748B').attr('font-size', 7)
        ax.selectAll('.tick line').attr('stroke', '#1E3A5F')
      })
  }, [data, color])

  return (
    <svg ref={ref} width="100%" height={60}
         style={{ display: 'block' }} />
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

// Placeholder metric IDs — in production pulled from metric_catalogue
const METRICS = [
  { id: 'cpu_utilisation_pct',   label: 'CPU %',       color: '#0891B2' },
  { id: 'power_draw_w',          label: 'Power (W)',   color: '#F59E0B' },
  { id: 'inlet_temperature_c',   label: 'Temp (°C)',   color: '#E05A5A' },
  { id: 'mem_utilisation_pct',   label: 'Memory %',    color: '#059669' },
]

export default function RackDetail({ tenantId }: { tenantId: string }) {
  const { entityId } = useParams<{ entityId: string }>()
  const navigate = useNavigate()

  const { data, loading, error } = useQuery(RACK_DETAIL_QUERY, {
    variables: { entityId },
    skip: !entityId,
  })

  const entity = data?.entity
  const subgraph = data?.topologySubgraph

  if (loading) return (
    <Box sx={{ display: 'flex', justifyContent: 'center', pt: 8 }}>
      <CircularProgress />
    </Box>
  )

  if (error || !entity) return (
    <Box sx={{ p: 3 }}>
      <Button startIcon={<BackIcon />} onClick={() => navigate('/')} sx={{ mb: 2 }}>Back</Button>
      <Alert severity="error">{error?.message || 'Entity not found'}</Alert>
    </Box>
  )

  const border = healthColor(entity.operationalStatus, entity.healthScore ?? 0)
  const devices = subgraph?.entities?.filter((e: any) => e.entityClass === 'DEVICE') ?? []

  return (
    <Box sx={{ p: 2 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2 }}>
        <Button startIcon={<BackIcon />} size="small" onClick={() => navigate('/')}>
          Rack Health
        </Button>
        <Divider orientation="vertical" flexItem />
        <Box sx={{ borderLeft: `3px solid ${border}`, pl: 1.5 }}>
          <Typography variant="h2">{entity.canonicalName}</Typography>
          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
            {entity.entityId} · {entity.entityClass}
          </Typography>
        </Box>
        <Box sx={{ ml: 'auto', display: 'flex', gap: 1 }}>
          <Chip label={entity.operationalStatus}
            sx={{ bgcolor: `${border}22`, color: border, fontWeight: 700 }} />
          {entity.criticalityLevel && (
            <Chip label={entity.criticalityLevel} size="small"
              sx={{ bgcolor: 'rgba(255,255,255,0.06)' }} />
          )}
          {entity.activeAlertCount > 0 && (
            <Chip label={`${entity.activeAlertCount} alerts`} size="small"
              sx={{ bgcolor: '#E05A5A22', color: '#E05A5A', fontWeight: 700 }} />
          )}
        </Box>
      </Box>

      <Grid container spacing={2}>
        {/* Left: topology + metrics */}
        <Grid item xs={12} lg={7}>
          <Card sx={{ mb: 2 }}>
            <CardContent sx={{ pb: '12px!important' }}>
              <Typography variant="h4" sx={{ mb: 1.5 }}>Topology subgraph</Typography>
              {subgraph?.entities?.length > 0 ? (
                <TopologyGraph
                  entityId={entityId!}
                  entities={subgraph.entities}
                  relationships={subgraph.relationships}
                />
              ) : (
                <Alert severity="info" sx={{ fontSize: '0.78rem' }}>
                  No topology data yet — graph-updater populates this as discovery events arrive.
                </Alert>
              )}
            </CardContent>
          </Card>

          {/* Metric sparklines */}
          <Card>
            <CardContent>
              <Typography variant="h4" sx={{ mb: 1.5 }}>Live metrics (24h)</Typography>
              <Grid container spacing={1.5}>
                {METRICS.map(m => (
                  <Grid item xs={12} sm={6} key={m.id}>
                    <MetricSparklineCard entityId={entityId!} metric={m} />
                  </Grid>
                ))}
              </Grid>
            </CardContent>
          </Card>
        </Grid>

        {/* Right: device inventory */}
        <Grid item xs={12} lg={5}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="h4" sx={{ mb: 1.5 }}>
                Device inventory ({devices.length})
              </Typography>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Name</TableCell>
                    <TableCell>Class</TableCell>
                    <TableCell>Status</TableCell>
                    <TableCell align="right">Alerts</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {devices.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={4} align="center">
                        <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                          No devices in graph yet
                        </Typography>
                      </TableCell>
                    </TableRow>
                  ) : devices.map((d: any) => {
                    const c = healthColor(d.operationalStatus, d.healthScore ?? 0)
                    return (
                      <TableRow key={d.entityId} sx={{ '&:hover': { bgcolor: 'rgba(255,255,255,0.02)' } }}>
                        <TableCell>
                          <Typography variant="caption" noWrap sx={{ maxWidth: 140, display: 'block' }}>
                            {d.canonicalName}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                            {d.entityClass}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Chip label={d.operationalStatus} size="small"
                            sx={{ height: 16, fontSize: '0.6rem', bgcolor: `${c}22`, color: c }} />
                        </TableCell>
                        <TableCell align="right">
                          {d.activeAlertCount > 0 && (
                            <Chip label={d.activeAlertCount} size="small"
                              sx={{ height: 16, fontSize: '0.6rem', bgcolor: '#E05A5A22', color: '#E05A5A' }} />
                          )}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>

              {/* Entity properties */}
              <Divider sx={{ my: 1.5 }} />
              <Typography variant="h4" sx={{ mb: 1 }}>Properties</Typography>
              {[
                ['Health score', `${Math.round((entity.healthScore ?? 0) * 100)}%`],
                ['Redundancy', entity.redundancyPosture ?? '—'],
                ['Type', entity.canonicalType ?? '—'],
                ['Last seen', entity.lastSeenAt ? new Date(entity.lastSeenAt).toLocaleString() : '—'],
              ].map(([k, v]) => (
                <Box key={k} sx={{ display: 'flex', justifyContent: 'space-between', py: 0.5 }}>
                  <Typography variant="caption" sx={{ color: 'text.secondary' }}>{k}</Typography>
                  <Typography variant="caption" fontWeight={600}>{v}</Typography>
                </Box>
              ))}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  )
}

// ── Metric sparkline card (fetches its own data) ──────────────────────────────

function MetricSparklineCard({
  entityId,
  metric,
}: {
  entityId: string
  metric: { id: string; label: string; color: string }
}) {
  const { data, loading } = useQuery(METRIC_QUERY, {
    variables: { entityId, metricId: metric.id, hours: 24 },
    fetchPolicy: 'cache-first',
  })

  const points = data?.metricHistory ?? []
  const latest = points[0]?.value

  return (
    <Box sx={{ bgcolor: 'rgba(255,255,255,0.02)', borderRadius: 1, p: 1 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
        <Typography variant="caption" fontWeight={600}>{metric.label}</Typography>
        <Typography variant="caption" sx={{ color: metric.color, fontWeight: 700 }}>
          {loading ? '…' : latest != null ? latest.toFixed(1) : '—'}
        </Typography>
      </Box>
      {loading ? (
        <Box sx={{ height: 60, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <CircularProgress size={16} />
        </Box>
      ) : points.length > 0 ? (
        <MetricSparkline data={[...points].reverse()} color={metric.color} />
      ) : (
        <Box sx={{ height: 60, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Typography variant="caption" sx={{ color: 'text.secondary' }}>No data</Typography>
        </Box>
      )}
    </Box>
  )
}
