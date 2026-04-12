/**
 * mocks/index.ts
 * Full set of mock responses for every API endpoint.
 * Activated when VITE_USE_MOCKS=true in .env (or .env.local).
 *
 * Each mock function mirrors the return type of the matching api.* call.
 */

import type {
  FacilitySummary, ThermalZone, RackHeatmapEntry, ThermalControls,
  CoolingUnit, PowerSummary, PowerTimeseries, PowerForecast,
  AlertsResponse, AlertItem, AnalyticsTrend, Report, ReportsResponse,
  AgentStatus, DriftSummary, DriftEvent, ClassResult,
} from '../lib/api'

export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'

// ── Facility ──────────────────────────────────────────────────────────────────
export const mockFacilitySummary = (): FacilitySummary => ({
  facility_name: 'FlowCore EU-West Alpha',
  city: 'Amsterdam',
  country_code: 'NL',
  capacity_kw: 12000,
  current_load_kw: 8400,
  utilisation_pct: 70,
  zone_count: 5,
  period_start: '2025-01-15',
  period_end: '2025-04-15',
  day_number: 42,
  total_days: 90,
  on_track: true,
  pue: 1.43,
  pue_target: 1.20,
  avg_temp_c: 25.6,
  active_alerts: 7,
  ups_load_pct: 68,
})

// ── Thermal ───────────────────────────────────────────────────────────────────
export const mockThermalZones = (): ThermalZone[] => [
  { zone_id: 'z1', zone_name: 'Zone A — Compute',  rack_count: 24, avg_temp_c: 22.1, max_temp_c: 27.4, sensor_count: 48, status: 'NORMAL' },
  { zone_id: 'z2', zone_name: 'Zone B — Storage',  rack_count: 18, avg_temp_c: 24.8, max_temp_c: 31.2, sensor_count: 36, status: 'WARNING' },
  { zone_id: 'z3', zone_name: 'Zone C — Network',  rack_count: 12, avg_temp_c: 21.5, max_temp_c: 25.0, sensor_count: 24, status: 'NORMAL' },
  { zone_id: 'z4', zone_name: 'Zone D — GPU Farm', rack_count: 8,  avg_temp_c: 29.3, max_temp_c: 36.1, sensor_count: 16, status: 'CRITICAL' },
  { zone_id: 'z5', zone_name: 'Zone E — Edge',     rack_count: 6,  avg_temp_c: 20.8, max_temp_c: 23.5, sensor_count: 12, status: 'NORMAL' },
]

export const mockHeatmap = (): RackHeatmapEntry[] => {
  const zones = ['Zone A', 'Zone B', 'Zone C', 'Zone D', 'Zone E']
  return Array.from({ length: 68 }, (_, i) => {
    const temp = 18 + Math.random() * 20
    return {
      rack_id: `rack-${i + 1}`,
      rack_name: `R${String(i + 1).padStart(3, '0')}`,
      location_id: `loc-${(i % 5) + 1}`,
      zone_name: zones[i % 5],
      temp_c: parseFloat(temp.toFixed(1)),
      power_draw_w: 800 + Math.random() * 3200,
      airflow_cfm: 200 + Math.random() * 800,
      status: temp > 35 ? 'CRITICAL' : temp > 30 ? 'WARNING' : 'NORMAL',
    }
  })
}

export const mockThermalControls = (): ThermalControls => ({
  auto_optimise: true,
  target_temp_c: 22,
  eco_mode: false,
})

export const mockCoolingUnits = (): CoolingUnit[] => [
  { unit_id: 'crac-1', unit_name: 'CRAC-01 (Zone A)', utilisation_pct: 72, power_kw: 45, airflow_cfm: 8000, status: 'ONLINE',   zone_id: 'z1', zone_name: 'Zone A' },
  { unit_id: 'crac-2', unit_name: 'CRAC-02 (Zone B)', utilisation_pct: 88, power_kw: 52, airflow_cfm: 9200, status: 'ONLINE',   zone_id: 'z2', zone_name: 'Zone B' },
  { unit_id: 'crac-3', unit_name: 'CRAC-03 (Zone C)', utilisation_pct: 61, power_kw: 38, airflow_cfm: 6800, status: 'ONLINE',   zone_id: 'z3', zone_name: 'Zone C' },
  { unit_id: 'crac-4', unit_name: 'CRAC-04 (Zone D)', utilisation_pct: 95, power_kw: 68, airflow_cfm: 12000, status: 'DEGRADED', zone_id: 'z4', zone_name: 'Zone D' },
  { unit_id: 'crac-5', unit_name: 'CRAC-05 (Zone E)', utilisation_pct: 44, power_kw: 28, airflow_cfm: 4800, status: 'ONLINE',   zone_id: 'z5', zone_name: 'Zone E' },
]

// ── Power ─────────────────────────────────────────────────────────────────────
export const mockPowerSummary = (): PowerSummary => ({
  total_power_draw_mw: 2.4,
  pue: 1.42,
  ups_load_pct: 68,
  energy_cost_eur_today: 3890,
  power_distribution: { it_kw: 1680, cooling_kw: 480, other_kw: 240 },
  pue_history: { current: 1.42, last_hour: 1.44, last_week: 1.51, last_month: 1.58 },
})

export const mockPowerTimeseries = (): PowerTimeseries[] => {
  const now = Date.now()
  return Array.from({ length: 24 }, (_, i) => ({
    timestamp: new Date(now - (23 - i) * 3600000).toISOString(),
    it_load_kw: 1500 + Math.sin(i / 4) * 200 + Math.random() * 100,
    cooling_kw:  420 + Math.sin(i / 4) * 60  + Math.random() * 40,
  }))
}

export const mockPowerForecast = (): PowerForecast[] => [
  { horizon_label: 'Next 1h',  predicted_mw: 2.42, predicted_cost_eur: 387 },
  { horizon_label: 'Next 6h',  predicted_mw: 2.51, predicted_cost_eur: 2410 },
  { horizon_label: 'Next 24h', predicted_mw: 2.48, predicted_cost_eur: 9523 },
]

// ── Alerts ────────────────────────────────────────────────────────────────────
const ALERT_TEMPLATES: Omit<AlertItem, 'alert_id' | 'event_ts'>[] = [
  { title: 'High Inlet Temperature',   severity: 'CRITICAL', status: 'ACTIVE',       zone: 'Zone D', device: 'R042', description: 'Inlet temperature exceeded critical threshold (36.1°C)' },
  { title: 'PDU Overload Warning',     severity: 'WARNING',  status: 'ACTIVE',       zone: 'Zone B', device: 'PDU-B02', description: 'PDU load at 87% of rated capacity' },
  { title: 'UPS Battery Low',          severity: 'WARNING',  status: 'ACKNOWLEDGED', zone: 'Zone A', device: 'UPS-A01', description: 'Battery capacity at 22% — schedule maintenance' },
  { title: 'Fan Speed Degraded',       severity: 'WARNING',  status: 'ACTIVE',       zone: 'Zone D', device: 'CRAC-04', description: 'CRAC unit fan speed below optimal threshold' },
  { title: 'Network Interface Error',  severity: 'INFO',     status: 'ACTIVE',       zone: 'Zone C', device: 'SW-C01', description: 'Elevated packet loss on uplink port 24' },
  { title: 'Disk I/O Saturation',      severity: 'WARNING',  status: 'ACTIVE',       zone: 'Zone B', device: 'STO-B04', description: 'Storage array I/O queue depth exceeding threshold' },
  { title: 'CPU Utilisation Spike',    severity: 'INFO',     status: 'RESOLVED',     zone: 'Zone A', device: 'SRV-A12', description: 'CPU utilisation returned to normal levels' },
  { title: 'Power Factor Anomaly',     severity: 'CRITICAL', status: 'ACTIVE',       zone: 'Zone B', device: 'PDU-B01', description: 'Power factor below 0.85 on phase C' },
]

export const mockAlerts = (): AlertsResponse => {
  const now = Date.now()
  const items: AlertItem[] = ALERT_TEMPLATES.map((t, i) => ({
    ...t,
    alert_id: `alert-${i + 1}`,
    event_ts: new Date(now - i * 900000).toISOString(),
  }))
  return {
    counts: { critical: 2, warning: 4, info: 2, resolved_today: 1 },
    items,
    total: items.length,
  }
}

// ── Analytics ─────────────────────────────────────────────────────────────────
export const mockAnalyticsTrends = (): AnalyticsTrend[] => {
  const now = Date.now()
  return Array.from({ length: 24 }, (_, i) => ({
    timestamp: new Date(now - (23 - i) * 3600000).toISOString(),
    pue:        parseFloat((1.38 + Math.sin(i / 5) * 0.08 + Math.random() * 0.04).toFixed(3)),
    power_mw:   parseFloat((2.2  + Math.sin(i / 4) * 0.3  + Math.random() * 0.1).toFixed(3)),
    avg_temp_c: parseFloat((24   + Math.sin(i / 6) * 2    + Math.random() * 0.5).toFixed(1)),
  }))
}

// ── Reports ───────────────────────────────────────────────────────────────────
export const mockReports = (): ReportsResponse => {
  const items: Report[] = [
    { report_id: 'r1', report_name: 'Energy Report — March 2025',   report_type: 'ENERGY',   period_label: 'March 2025',  description: 'Monthly energy consumption summary', status: 'READY',     s3_download_url: '#', is_template: false, scheduled_cron: '0 8 1 * *', created_at: '2025-04-01T08:00:00Z' },
    { report_id: 'r2', report_name: 'Thermal Report — Week 14',     report_type: 'THERMAL',  period_label: 'Week 14',     description: 'Weekly thermal health analysis',     status: 'READY',     s3_download_url: '#', is_template: false, scheduled_cron: null,         created_at: '2025-04-07T06:00:00Z' },
    { report_id: 'r3', report_name: 'Capacity Q1 2025',             report_type: 'CAPACITY', period_label: 'Q1 2025',     description: 'Quarterly capacity review',           status: 'READY',     s3_download_url: '#', is_template: false, scheduled_cron: null,         created_at: '2025-04-02T10:00:00Z' },
    { report_id: 'r4', report_name: 'Alert Activity — April 2025',  report_type: 'ALERTS',   period_label: 'April 2025',  description: 'Alert volume and MTTR trends',        status: 'GENERATING',s3_download_url: null,is_template: false, scheduled_cron: '0 7 1 * *', created_at: '2025-04-12T07:00:00Z' },
    // templates
    { report_id: 't1', report_name: 'Monthly Energy Report',        report_type: 'ENERGY',   period_label: 'Monthly',     description: 'Full facility energy and PUE breakdown', status: 'READY',  s3_download_url: '#', is_template: true,  scheduled_cron: null,         created_at: '2025-01-01T00:00:00Z' },
    { report_id: 't2', report_name: 'Thermal Health Summary',       report_type: 'THERMAL',  period_label: 'Weekly',      description: 'Zone temps, hotspots, cooling efficiency', status: 'READY',s3_download_url: '#', is_template: true,  scheduled_cron: null,         created_at: '2025-01-01T00:00:00Z' },
    { report_id: 't3', report_name: 'Capacity Planning Report',     report_type: 'CAPACITY', period_label: 'Quarterly',   description: 'Rack utilisation and growth projections', status: 'READY',s3_download_url: '#', is_template: true,  scheduled_cron: null,         created_at: '2025-01-01T00:00:00Z' },
    { report_id: 't4', report_name: 'Alert Activity Report',        report_type: 'ALERTS',   period_label: 'Weekly',      description: 'Alert volume, MTTR, severity distribution', status: 'READY',s3_download_url:'#', is_template: true,  scheduled_cron: null,         created_at: '2025-01-01T00:00:00Z' },
  ]
  return {
    counts: { total: 4, this_month: 3, scheduled: 2, generating: 1 },
    items,
  }
}

// ── Classification ────────────────────────────────────────────────────────────
export const mockClassStatus = (): AgentStatus => ({
  model_loaded: true,
  val_accuracy: 0.924,
  classified: 1847,
  needs_review: 12,
  model_run_id: 'mlflow-run-a1b2c3d4',
})

export const mockClassResults = (): ClassResult[] => {
  const types = ['Server', 'ToR-Switch', 'Storage-Array', 'CRAC', 'UPS', 'PDU', 'GPU-Server', 'Firewall']
  return Array.from({ length: 20 }, (_, i) => {
    const score = 0.55 + Math.random() * 0.45
    return {
      result_id: `cr-${i + 1}`,
      entity_id: `entity-${100 + i}`,
      inferred_entity_type: types[i % types.length],
      confidence_score: parseFloat(score.toFixed(3)),
      needs_review: score < 0.75,
      classified_at: new Date(Date.now() - i * 300000).toISOString(),
      operator_feedback: i < 3 ? types[(i + 1) % types.length] : null,
      feedback_at: i < 3 ? new Date(Date.now() - i * 100000).toISOString() : null,
      mlflow_run_id: 'mlflow-run-a1b2c3d4',
    }
  })
}

// ── Drift ─────────────────────────────────────────────────────────────────────
export const mockDriftSummary = (): DriftSummary => ({
  total_open: 14,
  by_severity: { CRITICAL: 3, MAJOR: 6, MINOR: 5 },
  by_type: {
    MISSING_IN_DCIM: 4, ATTRIBUTE_CONFLICT: 5, POSITION_MISMATCH: 2,
    CAPACITY_DISCREPANCY: 2, MISSING_IN_REALITY: 1, POWER_PATH_MISMATCH: 0,
  },
})

export const mockDriftEvents = (): DriftEvent[] => {
  const types = ['MISSING_IN_DCIM', 'ATTRIBUTE_CONFLICT', 'POSITION_MISMATCH', 'CAPACITY_DISCREPANCY', 'MISSING_IN_REALITY', 'POWER_PATH_MISMATCH']
  const sevs  = ['CRITICAL', 'CRITICAL', 'MAJOR', 'MAJOR', 'MAJOR', 'MINOR', 'MINOR', 'MINOR']
  return Array.from({ length: 14 }, (_, i) => ({
    drift_id: `drift-${i + 1}`,
    drift_type: types[i % types.length],
    severity: sevs[i % sevs.length],
    affected_entity_id: `entity-${200 + i}`,
    affected_entity_class: 'DEVICE',
    description: `Drift detected: ${types[i % types.length].replace(/_/g, ' ').toLowerCase()} on rack R${(i + 1).toString().padStart(3, '0')}`,
    detection_confidence: parseFloat((0.75 + Math.random() * 0.24).toFixed(2)),
    status: 'OPEN',
    detected_at: new Date(Date.now() - i * 3600000).toISOString(),
    source_a_state: { rack_unit: 12 + i, power_path: 'PDU-A' },
    source_b_state: { rack_unit: 14 + i, power_path: 'PDU-B' },
    conflict_field: types[i % types.length] === 'ATTRIBUTE_CONFLICT' ? 'rack_unit' : null,
    itsm_ticket_ref: null,
  }))
}

export const mockTopologyStatus = (): AgentStatus => ({
  consumer_running: true,
  dcim_cache_size: 1247,
  drift_events_generated: 186,
  errors: 2,
})
