#!/usr/bin/env python3
"""
FlowCore Synthetic Data Generator
==================================
Generates Medium-scale staging data:
  - 2 tenants, 3 sites, ~500 devices, 30 days of metrics
  - Mixed geography: EU (nlyte/Prometheus) + US (Sunbird/SNMP)
  - Full Layer 1-4 coverage including Layer 4 agent outputs

Outputs:
  - generators/output/postgresql_seed.sql
  - generators/output/timescaledb_seed.sql
  - generators/output/neo4j_seed.cypher

Usage:
  python3 generate_all.py [--days 30] [--devices 500] [--seed 42]
"""

import uuid, random, datetime, json, math, sys, os, argparse

# ── CLI args ──────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description='FlowCore synthetic data generator')
parser.add_argument('--days',    type=int, default=30,  help='Days of metric history')
parser.add_argument('--devices', type=int, default=500, help='Target device count')
parser.add_argument('--seed',    type=int, default=42,  help='Random seed')
args = parser.parse_args()

random.seed(args.seed)
DAYS        = args.days
TARGET_DEVS = args.devices
NOW         = datetime.datetime.utcnow().replace(microsecond=0, tzinfo=datetime.timezone.utc)
START_TS    = NOW - datetime.timedelta(days=DAYS)

OUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
os.makedirs(OUT_DIR, exist_ok=True)

# ── Helpers ───────────────────────────────────────────────────────────────────
def uid(): return str(uuid.uuid4())
def ts(dt): return dt.strftime("'%Y-%m-%d %H:%M:%S+00'")
def tsn(dt): return "NULL" if dt is None else ts(dt)
def sq(s):   return "'" + str(s).replace("'", "''") + "'"
def jq(d):   return sq(json.dumps(d))
def fl(v, decimals=4): return round(float(v), decimals)
def bf(v):   return 'TRUE' if v else 'FALSE'
def nl(v):   return 'NULL' if v is None else sq(v)

def rng_ts(start=None, end=None):
    s = start or START_TS
    e = end   or NOW
    delta = (e - s).total_seconds()
    return s + datetime.timedelta(seconds=random.uniform(0, delta))

def ago(days=0, hours=0, minutes=0):
    return NOW - datetime.timedelta(days=days, hours=hours, minutes=minutes)

# ── Writers ───────────────────────────────────────────────────────────────────
pg_lines   = []
ts_lines   = []
neo_lines  = []

def pg(s):  pg_lines.append(s)
def tsd(s): ts_lines.append(s)
def neo(s): neo_lines.append(s)

def pg_insert(table, cols, vals_list):
    """Emit one complete single-row INSERT per entry — safe across all psql versions."""
    if not vals_list:
        return  # guard: never emit a bare VALUES header with no data
    col_str = ', '.join(cols)
    for vals in vals_list:
        row = ', '.join(str(v) for v in vals)
        pg(f"INSERT INTO {table} ({col_str}) VALUES ({row});")
    pg('')

def ts_insert(table, cols, vals_list):
    """Emit one complete single-row INSERT per entry for TimescaleDB."""
    if not vals_list:
        return
    col_str = ', '.join(cols)
    for vals in vals_list:
        row = ', '.join(str(v) for v in vals)
        tsd(f"INSERT INTO {table} ({col_str}) VALUES ({row});")
    tsd('')

# =============================================================================
# SEED DATA CONSTANTS
# =============================================================================

VENDOR_PAIRS = [
    # (dcim_vendor, telemetry_vendor, country, city, tz, site_label)
    ('nlyte',   'Prometheus', 'IT', 'Naples',   'Europe/Rome',    'EU-PROD'),
    ('Sunbird', 'SNMP',       'US', 'Ashburn',  'America/New_York','US-PROD'),
    ('nlyte',   'Prometheus', 'DE', 'Frankfurt','Europe/Berlin',  'EU-DR'),
]

RACK_PREFIXES    = ['A', 'B', 'C', 'D', 'E', 'F']
DEVICE_MAKES     = {
    'server':  [('Dell',   'PowerEdge R750',  'iDRAC9'),
                ('HP',     'ProLiant DL380',  'iLO5'),
                ('Lenovo', 'ThinkSystem SR650','XCC')],
    'switch':  [('Cisco',  'Nexus 93180YC',  'NX-OS'),
                ('Arista', '7050CX3-32S',    'EOS'),
                ('Juniper','QFX5120-48Y',    'Junos')],
    'pdu':     [('Vertiv', 'Geist rPDU',     'GPDM'),
                ('APC',    'AP8888',          'NMC3'),
                ('Raritan','PX3-5190CR',      'EMX')],
    'storage': [('NetApp', 'AFF A400',        'ONTAP'),
                ('Pure',   'FlashArray//X70', 'Purity')],
    'firewall':[('Palo Alto','PA-5250',       'PAN-OS'),
                ('Fortinet','FortiGate 3000D','FortiOS')],
}

METRIC_DEFS = [
    # (canonical_name, family, type, unit, agg, warn, crit)
    ('cpu_utilisation_pct',          'COMPUTE',     'GAUGE',   '%',    'AVG',  75.0, 90.0),
    ('mem_utilisation_pct',          'COMPUTE',     'GAUGE',   '%',    'AVG',  80.0, 95.0),
    ('power_draw_w',                 'POWER',       'GAUGE',   'W',    'AVG',  None, None),
    ('inlet_temperature_c',          'THERMAL',     'GAUGE',   '°C',   'MAX',  28.0, 35.0),
    ('outlet_temperature_c',         'THERMAL',     'GAUGE',   '°C',   'MAX',  35.0, 42.0),
    ('fan_speed_rpm',                'THERMAL',     'GAUGE',   'RPM',  'AVG',  None, None),
    ('net_rx_bytes_per_sec',         'NETWORK',     'GAUGE',   'Bps',  'AVG',  None, None),
    ('net_tx_bytes_per_sec',         'NETWORK',     'GAUGE',   'Bps',  'AVG',  None, None),
    ('disk_io_read_bytes_per_sec',   'STORAGE',     'GAUGE',   'Bps',  'AVG',  None, None),
    ('disk_io_write_bytes_per_sec',  'STORAGE',     'GAUGE',   'Bps',  'AVG',  None, None),
    ('rack_space_u_used',            'COMPUTE',     'GAUGE',   'U',    'MAX',  None, None),
    ('pdu_total_load_w',             'POWER',       'GAUGE',   'W',    'AVG',  None, None),
    ('pdu_outlet_current_a',         'POWER',       'GAUGE',   'A',    'MAX',  16.0, 20.0),
    ('ups_battery_pct',              'POWER',       'GAUGE',   '%',    'MIN',  30.0, 15.0),
    ('cooling_setpoint_c',           'COOLING',     'GAUGE',   '°C',   'AVG',  None, None),
    ('airflow_cfm',                  'COOLING',     'GAUGE',   'CFM',  'AVG',  None, None),
    ('storage_utilisation_pct',      'STORAGE',     'GAUGE',   '%',    'AVG',  75.0, 90.0),
    ('bandwidth_utilisation_pct',    'NETWORK',     'GAUGE',   '%',    'AVG',  70.0, 90.0),
    ('error_count',                  'COMPUTE',     'COUNTER', 'count','SUM',  10.0, 50.0),
    ('packet_loss_pct',              'NETWORK',     'GAUGE',   '%',    'AVG',   1.0,  5.0),
]

ALERT_DEFS = [
    # (canonical_name, category, default_severity, entity_class_scope)
    ('high_cpu_utilisation',          'PERFORMANCE', 'HIGH',     'DEVICE'),
    ('high_memory_utilisation',       'PERFORMANCE', 'HIGH',     'DEVICE'),
    ('high_inlet_temperature',        'THERMAL',     'CRITICAL', 'DEVICE'),
    ('pdu_overload',                  'POWER',       'CRITICAL', 'PDU'),
    ('pdu_outlet_high_current',       'POWER',       'HIGH',     'PDU'),
    ('ups_battery_low',               'POWER',       'CRITICAL', 'DEVICE'),
    ('high_storage_utilisation',      'CAPACITY',    'HIGH',     'DEVICE'),
    ('high_bandwidth_utilisation',    'NETWORK',     'MEDIUM',   'INTERFACE'),
    ('high_packet_loss',              'NETWORK',     'HIGH',     'INTERFACE'),
    ('hardware_error_spike',          'RELIABILITY', 'HIGH',     'DEVICE'),
    ('fan_failure',                   'THERMAL',     'CRITICAL', 'DEVICE'),
    ('link_down',                     'NETWORK',     'HIGH',     'INTERFACE'),
    ('power_feed_failure',            'POWER',       'CRITICAL', 'FEED'),
    ('rack_space_exhaustion',         'CAPACITY',    'MEDIUM',   'RACK'),
    ('stale_telemetry',               'DATA_QUALITY','LOW',      'DEVICE'),
]

PROMETHEUS_METRIC_MAP = {
    'cpu_utilisation_pct':         ('node_cpu_seconds_total',       'rate(5m)*100',        1.0),
    'mem_utilisation_pct':         ('node_memory_MemUsed_bytes',    'value/MemTotal*100',   1.0),
    'power_draw_w':                ('ipmi_power_watts',             'value',                1.0),
    'inlet_temperature_c':         ('node_temperature_celsius',     'value',                1.0),
    'net_rx_bytes_per_sec':        ('node_network_receive_bytes_total','rate(5m)',          1.0),
    'net_tx_bytes_per_sec':        ('node_network_transmit_bytes_total','rate(5m)',         1.0),
    'disk_io_read_bytes_per_sec':  ('node_disk_read_bytes_total',   'rate(5m)',             1.0),
    'disk_io_write_bytes_per_sec': ('node_disk_written_bytes_total','rate(5m)',             1.0),
    'error_count':                 ('node_edac_correctable_errors_total','rate(1h)',        1.0),
    'bandwidth_utilisation_pct':   ('node_network_receive_bytes_total','rate(5m)/speed*100',1.0),
}

SNMP_METRIC_MAP = {
    'cpu_utilisation_pct':         ('hrProcessorLoad',              'value',                1.0),
    'mem_utilisation_pct':         ('hrStorageUsed/hrStorageSize',  'value*100',            1.0),
    'power_draw_w':                ('upsOutputPower',               'value',                1.0),
    'inlet_temperature_c':         ('entPhysicalTemperature',       'value',                1.0),
    'net_rx_bytes_per_sec':        ('ifInOctets',                   'rate(5m)',             1.0),
    'net_tx_bytes_per_sec':        ('ifOutOctets',                  'rate(5m)',             1.0),
    'pdu_total_load_w':            ('pduTotalPower',                'value',                1.0),
    'pdu_outlet_current_a':        ('pduOutletCurrent',             'value/10',             0.1),
    'bandwidth_utilisation_pct':   ('ifHighSpeed',                  'rate(5m)/speed*100',   1.0),
}

# =============================================================================
# PHASE 1 — TENANT & SITE STRUCTURE
# =============================================================================

print(">>> Phase 1: Generating tenants, sites, DCs, locations...")

pg("-- ============================================================")
pg("-- FlowCore PostgreSQL Seed Data")
pg(f"-- Generated: {NOW.isoformat()}")
pg(f"-- Scale: 2 tenants, 3 sites, ~{TARGET_DEVS} devices, {DAYS} days")
pg("-- ============================================================")
pg("")
pg("SET session_replication_role = replica;  -- disable FK checks during bulk load")
pg("BEGIN;")
pg("")

tsd("-- ============================================================")
tsd("-- FlowCore TimescaleDB Seed Data")
tsd(f"-- Generated: {NOW.isoformat()}")
tsd("-- ============================================================")
tsd("")
tsd("BEGIN;")
tsd("")

neo("// ============================================================")
neo("// FlowCore Neo4j Seed Data — Layer 1 Knowledge Graph")
neo(f"// Generated: {NOW.isoformat()}")
neo("// ============================================================")
neo("")
neo("// ── Schema constraints (idempotent) ──")
neo("// Schema constraints are applied separately by run_all.sh before this seed loads.")
neo("")

# ── TENANTS ──────────────────────────────────────────────────────────────────
TENANTS = [
    {'tenant_id': uid(), 'name': 'ENEA Fusion Research',
     'slug': 'enea-fusion', 'plan_tier': 'ENTERPRISE',
     'neo4j_partition_key': 'tenant_enea', 'status': 'ACTIVE'},
    {'tenant_id': uid(), 'name': 'Meridian Cloud Services',
     'slug': 'meridian-cloud', 'plan_tier': 'PROFESSIONAL',
     'neo4j_partition_key': 'tenant_meridian', 'status': 'ACTIVE'},
]

pg("-- TENANTS")
for t in TENANTS:
    pg(f"INSERT INTO tenant (tenant_id, name, slug, plan_tier, neo4j_partition_key, status, created_at) VALUES")
    pg(f"  ({sq(t['tenant_id'])}, {sq(t['name'])}, {sq(t['slug'])}, {sq(t['plan_tier'])},")
    pg(f"   {sq(t['neo4j_partition_key'])}, {sq(t['status'])}, {ts(ago(200))});")
pg("")

neo("// ── TENANTS")
for t in TENANTS:
    neo(f"MERGE (t:Tenant {{tenant_id: {sq(t['tenant_id'])}}}) SET")
    neo(f"  t.name = {sq(t['name'])}, t.slug = {sq(t['slug'])},")
    neo(f"  t.plan_tier = {sq(t['plan_tier'])}, t.neo4j_partition_key = {sq(t['neo4j_partition_key'])},")
    created_str = sq(str(ago(200)))
    neo(f"  t.status = {sq(t['status'])}, t.created_at = {created_str};")
neo("")

# ── SITES (3 total, distributed across 2 tenants) ────────────────────────────
SITES = []
site_assignments = [(0, 0), (1, 1), (0, 2)]  # (tenant_idx, vendor_pair_idx)

for tenant_idx, vp_idx in site_assignments:
    t     = TENANTS[tenant_idx]
    vp    = VENDOR_PAIRS[vp_idx]
    site  = {
        'site_id':       uid(),
        'tenant_id':     t['tenant_id'],
        'canonical_name': f"{vp[5]} Site — {vp[3]}",
        'country_code':  vp[2],
        'city':          vp[3],
        'timezone':      vp[4],
        'status':        'ACTIVE',
        'dcim_vendor':   vp[0],
        'telem_vendor':  vp[1],
    }
    SITES.append(site)

pg("-- SITES")
for s in SITES:
    pg(f"INSERT INTO site (site_id, tenant_id, canonical_name, country_code, city, timezone, status, created_at, updated_at) VALUES")
    pg(f"  ({sq(s['site_id'])}, {sq(s['tenant_id'])}, {sq(s['canonical_name'])},")
    pg(f"   {sq(s['country_code'])}, {sq(s['city'])}, {sq(s['timezone'])},")
    pg(f"   {sq(s['status'])}, {ts(ago(180))}, {ts(ago(1))});")
pg("")

neo("// ── SITES")
for s in SITES:
    neo(f"MERGE (s:Site {{site_id: {sq(s['site_id'])}}}) SET")
    neo(f"  s.canonical_name = {sq(s['canonical_name'])}, s.country_code = {sq(s['country_code'])},")
    neo(f"  s.city = {sq(s['city'])}, s.timezone = {sq(s['timezone'])}, s.status = {sq(s['status'])},")
    neo(f"  s.tenant_id = {sq(s['tenant_id'])};")
    neo(f"MATCH (t:Tenant {{tenant_id: {sq(s['tenant_id'])}}}), (s:Site {{site_id: {sq(s['site_id'])}}})")
    neo(f"MERGE (t)-[:OWNS]->(s);")
neo("")

# ── COLLECTION AGENTS ─────────────────────────────────────────────────────────
COLLECTION_AGENTS = []
pg("-- COLLECTION AGENTS")
for s in SITES:
    for i in range(2):  # 2 agents per site
        agent = {
            'agent_id':      uid(),
            'site_id':       s['site_id'],
            'tenant_id':     s['tenant_id'],
            'agent_name':    f"collector-{s['city'].lower()}-{i+1:02d}",
            'agent_version': '1.4.2',
            'deployment_mode': 'KUBERNETES_POD',
            'status':        'ACTIVE',
            'config_ref':    f"helm/flowcore-collector@v1.4.2",
            'last_heartbeat_at': ago(minutes=random.randint(1, 5)),
        }
        COLLECTION_AGENTS.append(agent)
        pg(f"INSERT INTO collection_agent (agent_id, site_id, tenant_id, agent_name, agent_version, deployment_mode, status, config_ref, last_heartbeat_at, created_at, updated_at) VALUES")
        pg(f"  ({sq(agent['agent_id'])}, {sq(agent['site_id'])}, {sq(agent['tenant_id'])},")
        pg(f"   {sq(agent['agent_name'])}, {sq(agent['agent_version'])}, {sq(agent['deployment_mode'])},")
        pg(f"   {sq(agent['status'])}, {sq(agent['config_ref'])}, {ts(agent['last_heartbeat_at'])},")
        pg(f"   {ts(ago(180))}, {ts(ago(0))});")
pg("")

neo("// ── COLLECTION AGENTS")
for a in COLLECTION_AGENTS:
    neo(f"MERGE (ca:CollectionAgent {{agent_id: {sq(a['agent_id'])}}}) SET")
    neo(f"  ca.agent_name = {sq(a['agent_name'])}, ca.agent_version = {sq(a['agent_version'])},")
    neo(f"  ca.deployment_mode = {sq(a['deployment_mode'])}, ca.status = {sq(a['status'])},")
    neo(f"  ca.tenant_id = {sq(a['tenant_id'])};")
    neo(f"MATCH (s:Site {{site_id: {sq(a['site_id'])}}}), (ca:CollectionAgent {{agent_id: {sq(a['agent_id'])}}})")
    neo(f"MERGE (s)-[:DEPLOYS]->(ca);")
neo("")

# ── PLATFORM CONFIG ───────────────────────────────────────────────────────────
pg("-- PLATFORM CONFIG (operational thresholds)")
for t in TENANTS:
    configs = [
        ('telemetry',         'stale_telemetry_threshold_s',  '300',  'INTEGER', 'Silence duration before STALE_TELEMETRY_EVENT is raised (seconds)'),
        ('telemetry',         'last_known_state_window_s',     '600',  'INTEGER', 'Max staleness for NFR-09 last-known-state mode (seconds)'),
        ('entity_resolution', 'confidence_min',                '0.85', 'FLOAT',  'Min match_confidence for entity resolution rule acceptance'),
        ('alerting',          'correlation_window_s',          '300',  'INTEGER', 'Temporal window for M3 alert clustering (seconds)'),
        ('data_quality',      'completeness_warn_threshold',   '0.70', 'FLOAT',  'NODE_QUALITY_SCORE completeness below this triggers DQ warning'),
        ('simulation',        'max_execution_ms',              '10000','INTEGER', 'NFR-04: max what-if simulation wall-clock time (milliseconds)'),
    ]
    for scope, key, val, vtype, desc in configs:
        pg(f"INSERT INTO platform_config (config_id, tenant_id, config_scope, config_key, config_value, value_type, description, created_at, updated_at) VALUES")
        pg(f"  ({sq(uid())}, {sq(t['tenant_id'])}, {sq(scope)}, {sq(key)}, {sq(val)}, {sq(vtype)}, {sq(desc)}, {ts(ago(180))}, {ts(ago(1))});")
pg("")

# ── DATA CENTERS ──────────────────────────────────────────────────────────────
DATA_CENTERS = []
dc_configs = [
    ('CRESCO 6 HPC Cluster',        12000.0, 4500.0, 'IV'),
    ('Meridian Ashburn DC-1',        8000.0, 3200.0, 'III'),
    ('ENEA Frankfurt DR',            4000.0, 1800.0, 'III'),
]
pg("-- DATA CENTERS")
for i, (site, (dc_name, power, area, tier)) in enumerate(zip(SITES, dc_configs)):
    dc = {
        'dc_id':             uid(),
        'site_id':           site['site_id'],
        'tenant_id':         site['tenant_id'],
        'canonical_name':    dc_name,
        'total_power_kw':    power,
        'floor_area_m2':     area,
        'tier_classification': tier,
        'status':            'OPERATIONAL',
    }
    DATA_CENTERS.append(dc)
    pg(f"INSERT INTO data_center (dc_id, site_id, tenant_id, canonical_name, total_power_kw, floor_area_m2, tier_classification, status, created_at, updated_at) VALUES")
    pg(f"  ({sq(dc['dc_id'])}, {sq(dc['site_id'])}, {sq(dc['tenant_id'])}, {sq(dc['canonical_name'])},")
    pg(f"   {fl(dc['total_power_kw'])}, {fl(dc['floor_area_m2'])}, {sq(dc['tier_classification'])},")
    pg(f"   {sq(dc['status'])}, {ts(ago(180))}, {ts(ago(1))});")
pg("")

neo("// ── DATA CENTERS")
for dc in DATA_CENTERS:
    neo(f"MERGE (dc:DataCenter {{dc_id: {sq(dc['dc_id'])}}}) SET")
    neo(f"  dc.canonical_name = {sq(dc['canonical_name'])}, dc.total_power_kw = {dc['total_power_kw']},")
    neo(f"  dc.floor_area_m2 = {dc['floor_area_m2']}, dc.tier_classification = {sq(dc['tier_classification'])},")
    neo(f"  dc.status = {sq(dc['status'])}, dc.tenant_id = {sq(dc['tenant_id'])};")
    neo(f"MATCH (s:Site {{site_id: {sq(dc['site_id'])}}}), (dc:DataCenter {{dc_id: {sq(dc['dc_id'])}}})")
    neo(f"MERGE (s)-[:CONTAINS]->(dc);")
    neo(f"MATCH (t:Tenant {{tenant_id: {sq(dc['tenant_id'])}}}), (dc:DataCenter {{dc_id: {sq(dc['dc_id'])}}})")
    neo(f"MERGE (t)-[:OWNS]->(dc);")
neo("")

# =============================================================================
# PHASE 2 — LOCATIONS (rooms, aisles, rows per DC)
# =============================================================================

print(">>> Phase 2: Generating location hierarchy...")

LOCATIONS = []  # list of location dicts

def make_location(dc_id, tenant_id, loc_type, name, parent_id=None, depth=0):
    loc = {
        'location_id': uid(),
        'dc_id':       dc_id,
        'tenant_id':   tenant_id,
        'location_type': loc_type,
        'canonical_name': name,
        'parent_location_id': parent_id,
        'depth_level': depth,
        'spatial_attributes': json.dumps({'x_grid': random.randint(0,20), 'y_grid': random.randint(0,20)}),
    }
    LOCATIONS.append(loc)
    return loc

dc_room_counts = [3, 2, 2]  # rooms per DC
dc_row_counts  = [4, 3, 3]  # rows per room

ROOMS_BY_DC = {}  # dc_id -> list of (room_loc, [row_locs])

for dc, n_rooms, n_rows in zip(DATA_CENTERS, dc_room_counts, dc_row_counts):
    rooms = []
    for ri in range(n_rooms):
        room_label = f"Server Hall {chr(65+ri)}"
        room = make_location(dc['dc_id'], dc['tenant_id'], 'ROOM', room_label, None, 0)
        rows = []
        for rw in range(n_rows):
            aisle_cold = make_location(dc['dc_id'], dc['tenant_id'], 'AISLE',
                                       f"{room_label} Cold Aisle {rw+1}",
                                       room['location_id'], 1)
            row = make_location(dc['dc_id'], dc['tenant_id'], 'ROW',
                                f"{room_label} Row {rw+1}",
                                aisle_cold['location_id'], 2)
            rows.append(row)
        rooms.append((room, rows))
    ROOMS_BY_DC[dc['dc_id']] = rooms

pg("-- LOCATIONS (Neo4j nodes only — no PG entity_ref rows for locations)")

# Write locations directly to Neo4j
neo("// ── LOCATIONS")
for loc in LOCATIONS:
    parent_clause = f"l.parent_location_id = {sq(loc['parent_location_id'])}" if loc['parent_location_id'] else "l.parent_location_id = null"
    neo(f"MERGE (l:Location {{location_id: {sq(loc['location_id'])}}}) SET")
    neo(f"  l.location_type = {sq(loc['location_type'])}, l.canonical_name = {sq(loc['canonical_name'])},")
    neo(f"  l.depth_level = {loc['depth_level']}, {parent_clause},")
    neo(f"  l.dc_id = {sq(loc['dc_id'])}, l.tenant_id = {sq(loc['tenant_id'])},")
    neo(f"  l.spatial_attributes = {sq(loc['spatial_attributes'])};")
    neo(f"MATCH (dc:DataCenter {{dc_id: {sq(loc['dc_id'])}}}), (l:Location {{location_id: {sq(loc['location_id'])}}})")
    neo(f"MERGE (dc)-[:ORGANISES]->(l);")
    if loc['parent_location_id']:
        neo(f"MATCH (p:Location {{location_id: {sq(loc['parent_location_id'])}}}), (l:Location {{location_id: {sq(loc['location_id'])}}})")
        neo(f"MERGE (p)-[:NESTS]->(l);")
neo("")

# =============================================================================
# PHASE 3 — INFRASTRUCTURE ENTITIES (racks, devices, PDUs, feeds, interfaces)
# =============================================================================

print(">>> Phase 3: Generating infrastructure entities (~500 devices)...")

ALL_ENTITIES = []  # {entity_id, tenant_id, dc_id, entity_class, canonical_name, canonical_type, ...}
RACK_LIST    = []
DEVICE_LIST  = []
PDU_LIST     = []
FEED_LIST    = []
IFACE_LIST   = []

entity_rel_pairs = []  # (from_id, to_id, rel_type, props_dict)

# Distribute device target across DCs
dc_device_allocs = [int(TARGET_DEVS * 0.50), int(TARGET_DEVS * 0.35), int(TARGET_DEVS * 0.15)]

for dc_idx, (dc, n_devices) in enumerate(zip(DATA_CENTERS, dc_device_allocs)):
    rooms = ROOMS_BY_DC[dc['dc_id']]
    rows  = [row for room, row_list in rooms for row in row_list]

    # Calculate racks needed  (avg 10 devices per rack)
    n_racks = max(4, n_devices // 10)

    # --- POWER FEEDS (2 per DC — A and B)
    for feed_label in ['Feed-A', 'Feed-B']:
        feed = {
            'entity_id':       uid(),
            'tenant_id':       dc['tenant_id'],
            'dc_id':           dc['dc_id'],
            'location_id':     rooms[0][0]['location_id'],
            'entity_class':    'FEED',
            'canonical_name':  f"{dc['canonical_name']} {feed_label}",
            'canonical_type':  'PowerFeed',
            'operational_status': 'ONLINE',
            'health_score':    round(random.uniform(0.92, 1.0), 3),
            'active_alert_count': 0,
            'criticality_level':  'P1',
            'redundancy_posture': '2N',
            'data_quality_score': round(random.uniform(0.88, 1.0), 3),
            'last_seen_at':    ago(minutes=random.randint(1, 10)),
            'last_known_good_at': ago(minutes=random.randint(1, 10)),
            'stale_since':     None,
        }
        FEED_LIST.append(feed)
        ALL_ENTITIES.append(feed)

    # --- RACKS & DEVICES
    for rack_num in range(n_racks):
        prefix  = random.choice(RACK_PREFIXES)
        row_loc = rows[rack_num % len(rows)]
        rack_u  = random.choice([42, 47, 48])
        rack = {
            'entity_id':      uid(),
            'tenant_id':      dc['tenant_id'],
            'dc_id':          dc['dc_id'],
            'location_id':    row_loc['location_id'],
            'entity_class':   'RACK',
            'canonical_name': f"RACK-{prefix}{rack_num+1:03d}",
            'canonical_type': 'StandardRack',
            'operational_status': 'ONLINE',
            'health_score':   round(random.uniform(0.7, 1.0), 3),
            'active_alert_count': random.randint(0, 3),
            'criticality_level':  random.choice(['P1', 'P2', 'P2', 'P3']),
            'redundancy_posture': random.choice(['N+1', '2N', 'N+1']),
            'data_quality_score': round(random.uniform(0.75, 1.0), 3),
            'rack_u_total':   rack_u,
            'rack_u_used':    random.randint(10, rack_u - 4),
            'last_seen_at':   ago(minutes=random.randint(1, 15)),
            'last_known_good_at': ago(minutes=random.randint(1, 15)),
            'stale_since':    None,
        }
        RACK_LIST.append(rack)
        ALL_ENTITIES.append(rack)

        # PDU per rack (2 — A and B legs)
        rack_pdus = []
        for pdu_leg in ['A', 'B']:
            pdu_make = random.choice(DEVICE_MAKES['pdu'])
            pdu = {
                'entity_id':      uid(),
                'tenant_id':      dc['tenant_id'],
                'dc_id':          dc['dc_id'],
                'location_id':    row_loc['location_id'],
                'entity_class':   'PDU',
                'canonical_name': f"{rack['canonical_name']}-PDU-{pdu_leg}",
                'canonical_type': 'RackPDU',
                'operational_status': 'ONLINE',
                'health_score':   round(random.uniform(0.85, 1.0), 3),
                'active_alert_count': 0,
                'criticality_level': rack['criticality_level'],
                'redundancy_posture': '2N',
                'data_quality_score': round(random.uniform(0.80, 1.0), 3),
                'vendor':         pdu_make[0],
                'model':          pdu_make[1],
                'last_seen_at':   ago(minutes=random.randint(1, 10)),
                'last_known_good_at': ago(minutes=random.randint(1, 10)),
                'stale_since':    None,
            }
            PDU_LIST.append(pdu)
            ALL_ENTITIES.append(pdu)
            rack_pdus.append(pdu)

            # PDU → FEED relationship
            feed = random.choice(FEED_LIST[-2:] if len(FEED_LIST) >= 2 else FEED_LIST)
            entity_rel_pairs.append((pdu['entity_id'], feed['entity_id'], 'POWERED_BY',
                                     {'cable_id': f"CAB-{uid()[:8]}"}))
            # PDU IN_RACK
            entity_rel_pairs.append((pdu['entity_id'], rack['entity_id'], 'IN_RACK', {}))

        # Devices in this rack
        devs_in_rack = random.randint(6, 14)
        u_offset = 1
        for d_idx in range(devs_in_rack):
            dev_role = random.choices(
                ['server', 'switch', 'storage', 'firewall'],
                weights=[70, 15, 10, 5])[0]
            dev_make  = random.choice(DEVICE_MAKES[dev_role])
            u_size    = 2 if dev_role == 'server' else (1 if dev_role == 'switch' else 4)
            age_days  = random.randint(30, 1800)
            health    = round(random.uniform(0.55, 1.0), 3)
            crit      = random.choice(['P1','P2','P2','P3','P3'])
            dev = {
                'entity_id':      uid(),
                'tenant_id':      dc['tenant_id'],
                'dc_id':          dc['dc_id'],
                'location_id':    row_loc['location_id'],
                'entity_class':   'DEVICE',
                'canonical_name': f"{rack['canonical_name']}-{dev_role.upper()}-{d_idx+1:02d}",
                'canonical_type': dev_role.capitalize() + ('-Server' if dev_role=='server' else ''),
                'operational_status': random.choices(
                    ['ONLINE','ONLINE','ONLINE','DEGRADED','OFFLINE'],
                    weights=[80, 80, 80, 12, 5])[0],
                'health_score':   health,
                'active_alert_count': 0 if health > 0.9 else random.randint(0, 4),
                'criticality_level': crit,
                'redundancy_posture': random.choice(['N+1', 'N', '2N']),
                'data_quality_score': round(random.uniform(0.65, 1.0), 3),
                'vendor':         dev_make[0],
                'model':          dev_make[1],
                'mgmt_protocol':  dev_make[2],
                'age_days':       age_days,
                'rack_u_slot':    u_offset,
                'rack_u_size':    u_size,
                'last_seen_at':   ago(minutes=random.randint(0, 30)),
                'last_known_good_at': ago(minutes=random.randint(0, 30)),
                'stale_since':    None,
            }
            u_offset += u_size
            DEVICE_LIST.append(dev)
            ALL_ENTITIES.append(dev)

            # IN_RACK
            entity_rel_pairs.append((dev['entity_id'], rack['entity_id'], 'IN_RACK',
                                     {'u_slot': u_offset, 'u_size': u_size}))
            # POWERED_BY one of the rack PDUs
            entity_rel_pairs.append((dev['entity_id'],
                                     random.choice(rack_pdus)['entity_id'],
                                     'POWERED_BY', {}))

            # Network interfaces (2 per server/storage, 1 for others)
            n_ifaces = 2 if dev_role in ('server', 'storage') else 1
            for iface_idx in range(n_ifaces):
                iface = {
                    'entity_id':      uid(),
                    'tenant_id':      dc['tenant_id'],
                    'dc_id':          dc['dc_id'],
                    'location_id':    row_loc['location_id'],
                    'entity_class':   'INTERFACE',
                    'canonical_name': f"{dev['canonical_name']}-eth{iface_idx}",
                    'canonical_type': 'EthernetInterface',
                    'operational_status': 'ONLINE' if dev['operational_status']=='ONLINE' else 'OFFLINE',
                    'health_score':   round(random.uniform(0.85, 1.0), 3),
                    'active_alert_count': 0,
                    'criticality_level': crit,
                    'redundancy_posture': 'N',
                    'data_quality_score': round(random.uniform(0.75, 1.0), 3),
                    'speed_gbps':     random.choice([1, 10, 25, 100]),
                    'mac_address':    ':'.join(f'{random.randint(0,255):02X}' for _ in range(6)),
                    'last_seen_at':   ago(minutes=random.randint(0, 20)),
                    'last_known_good_at': ago(minutes=random.randint(0, 20)),
                    'stale_since':    None,
                }
                IFACE_LIST.append(iface)
                ALL_ENTITIES.append(iface)
                entity_rel_pairs.append((iface['entity_id'], dev['entity_id'], 'CONNECTED_TO',
                                         {'port': f'eth{iface_idx}', 'speed_gbps': iface['speed_gbps']}))

print(f"    Entities: {len(ALL_ENTITIES)} total "
      f"({len(RACK_LIST)} racks, {len(DEVICE_LIST)} devices, "
      f"{len(PDU_LIST)} PDUs, {len(FEED_LIST)} feeds, {len(IFACE_LIST)} ifaces)")

# ── Write entity_ref table to PostgreSQL ──────────────────────────────────────
pg("-- INFRASTRUCTURE ENTITY REF (lightweight FK anchor for Layer 2 & 4)")
BATCH_SIZE = 200
entity_rows = []
for e in ALL_ENTITIES:
    entity_rows.append((sq(e['entity_id']), sq(e['tenant_id']),
                        sq(e['entity_class']), sq(e['canonical_name']),
                        sq(e.get('dc_id', None)) if e.get('dc_id') else 'NULL',
                        ts(ago(random.randint(1, 180)))))
for i in range(0, len(entity_rows), BATCH_SIZE):
    batch = entity_rows[i:i+BATCH_SIZE]
    pg_insert('infrastructure_entity_ref',
              ['entity_id','tenant_id','entity_class','canonical_name','dc_id','created_at'],
              batch)

# ── Write full nodes to Neo4j ─────────────────────────────────────────────────
neo("// ── INFRASTRUCTURE ENTITIES")
for e in ALL_ENTITIES:
    neo(f"MERGE (n:InfrastructureEntity {{entity_id: {sq(e['entity_id'])}}}) SET")
    neo(f"  n.entity_class = {sq(e['entity_class'])},")
    neo(f"  n.canonical_name = {sq(e['canonical_name'])},")
    neo(f"  n.canonical_type = {sq(e.get('canonical_type',''))},")
    neo(f"  n.operational_status = {sq(e['operational_status'])},")
    neo(f"  n.health_score = {e['health_score']},")
    neo(f"  n.active_alert_count = {e['active_alert_count']},")
    neo(f"  n.criticality_level = {sq(e['criticality_level'])},")
    neo(f"  n.redundancy_posture = {sq(e['redundancy_posture'])},")
    neo(f"  n.data_quality_score = {e['data_quality_score']},")
    neo(f"  n.tenant_id = {sq(e['tenant_id'])},")
    last_seen = e.get('last_seen_at') or ago(minutes=30)
    neo(f"  n.last_seen_at = {sq(str(last_seen))},")
    last_good = e.get('last_known_good_at') or ago(minutes=30)
    neo(f"  n.last_known_good_at = {sq(str(last_good))};")
    # Location relationship
    neo(f"MATCH (l:Location {{location_id: {sq(e['location_id'])}}}), (n:InfrastructureEntity {{entity_id: {sq(e['entity_id'])}}})")
    neo(f"MERGE (l)-[:CONTAINS]->(n);")

neo("")
neo("// ── ENTITY RELATIONSHIPS")
for from_id, to_id, rel_type, props in entity_rel_pairs:
    props_str = ', '.join(f"r.{k} = {sq(str(v))}" for k, v in props.items()) if props else "r.created = true"
    neo(f"MATCH (a:InfrastructureEntity {{entity_id: {sq(from_id)}}}),")
    neo(f"      (b:InfrastructureEntity {{entity_id: {sq(to_id)}}})")
    neo(f"MERGE (a)-[r:{rel_type}]->(b) SET {props_str};")
neo("")

# =============================================================================
# PHASE 4 — SOURCE SYSTEMS & FIELD MAPPINGS
# =============================================================================

print(">>> Phase 4: Source systems, field mappings, identity signals...")

SOURCE_SYSTEMS = []

# One DCIM + one telemetry source per site
for site in SITES:
    # DCIM
    dcim_vendor = site['dcim_vendor']
    dcim = {
        'source_id':       uid(),
        'tenant_id':       site['tenant_id'],
        'source_name':     f"{dcim_vendor}-{site['city'].lower()}-prod",
        'source_class':    'DCIM',
        'vendor_name':     dcim_vendor,
        'product_name':    'nlyte Energy Manager' if dcim_vendor == 'nlyte' else 'Sunbird dcTrack',
        'product_version': '12.1' if dcim_vendor == 'nlyte' else '8.3',
        'connection_type': 'REST_API',
        'connection_config': json.dumps({'base_url': f'https://{dcim_vendor.lower()}.{site["city"].lower()}.internal/api/v2',
                                          'poll_interval_s': 300}),
        'auth_type':       'BEARER',
        'status':          'ACTIVE',
        'last_sync_at':    ago(minutes=random.randint(5, 30)),
        'site_id':         site['site_id'],
    }
    SOURCE_SYSTEMS.append(dcim)

    # Telemetry
    telem_vendor = site['telem_vendor']
    telem = {
        'source_id':       uid(),
        'tenant_id':       site['tenant_id'],
        'source_name':     f"{telem_vendor.lower()}-{site['city'].lower()}-gateway",
        'source_class':    'TELEMETRY',
        'vendor_name':     telem_vendor,
        'product_name':    'Prometheus Remote Write' if telem_vendor == 'Prometheus' else 'SNMP Gateway',
        'product_version': '2.45' if telem_vendor == 'Prometheus' else '3.0',
        'connection_type': 'WEBHOOK' if telem_vendor == 'Prometheus' else 'SNMP',
        'connection_config': json.dumps({'endpoint': f'http://telemetry-gw.{site["city"].lower()}.internal',
                                          'poll_interval_s': 60}),
        'auth_type':       'BEARER' if telem_vendor == 'Prometheus' else 'SNMP_V3',
        'status':          'ACTIVE',
        'last_sync_at':    ago(minutes=random.randint(1, 5)),
        'site_id':         site['site_id'],
    }
    SOURCE_SYSTEMS.append(telem)

    # Discovery (SNMP walk)
    disc = {
        'source_id':       uid(),
        'tenant_id':       site['tenant_id'],
        'source_name':     f"snmp-discovery-{site['city'].lower()}",
        'source_class':    'DISCOVERY',
        'vendor_name':     'FlowCore',
        'product_name':    'active-discovery-service',
        'product_version': '1.4.2',
        'connection_type': 'SNMP',
        'connection_config': json.dumps({'cidr': f"10.{random.randint(1,254)}.0.0/24",
                                          'community': 'flowcore-ro', 'version': 'v3'}),
        'auth_type':       'SNMP_V3',
        'status':          'ACTIVE',
        'last_sync_at':    ago(hours=random.randint(1, 6)),
        'site_id':         site['site_id'],
    }
    SOURCE_SYSTEMS.append(disc)

# Store source_id by site for later use
SITE_DCIM_SOURCE   = {s['site_id']: SOURCE_SYSTEMS[i*3]   for i, s in enumerate(SITES)}
SITE_TELEM_SOURCE  = {s['site_id']: SOURCE_SYSTEMS[i*3+1] for i, s in enumerate(SITES)}
SITE_DISC_SOURCE   = {s['site_id']: SOURCE_SYSTEMS[i*3+2] for i, s in enumerate(SITES)}

pg("-- SOURCE SYSTEMS")
for ss in SOURCE_SYSTEMS:
    pg(f"INSERT INTO source_system (source_id, tenant_id, source_name, source_class, vendor_name, product_name, product_version, connection_type, connection_config, auth_type, status, last_sync_at, created_at) VALUES")
    pg(f"  ({sq(ss['source_id'])}, {sq(ss['tenant_id'])}, {sq(ss['source_name'])}, {sq(ss['source_class'])},")
    pg(f"   {sq(ss['vendor_name'])}, {sq(ss['product_name'])}, {sq(ss['product_version'])},")
    pg(f"   {sq(ss['connection_type'])}, {sq(ss['connection_config'])}, {sq(ss['auth_type'])},")
    pg(f"   {sq(ss['status'])}, {ts(ss['last_sync_at'])}, {ts(ago(180))});")
pg("")

# ── FIELD MAPPINGS (representative set for nlyte + Sunbird + Prometheus + SNMP)
pg("-- FIELD MAPPINGS")
# nlyte mappings
nlyte_ss = [ss for ss in SOURCE_SYSTEMS if ss['vendor_name'] == 'nlyte'][0]
nlyte_mappings = [
    ('rack',   '$.rack.name',                    'ENTITY_FIELD',     None,        None,          'DIRECT',       None,           'STRING', True,  True),
    ('rack',   '$.rack.RackMaxPower',             'CAPACITY_SPEC',    'dcim.nlyte','power_kw',    'UNIT_CONVERT', 'value/1000',   'FLOAT',  False, False),
    ('rack',   '$.rack.RackUHeight',              'CAPACITY_SPEC',    'dcim.nlyte','space_u',     'DIRECT',       None,           'INTEGER',False, False),
    ('rack',   '$.rack.CabinetOwner',             'ENTITY_ATTRIBUTE', 'dcim.nlyte','owner',       'DIRECT',       None,           'STRING', False, False),
    ('rack',   '$.rack.CriticalityLevel',         'ENTITY_FIELD',     None,        None,          'ENUM_MAP',     '{"High":"P1","Med":"P2","Low":"P3"}','STRING',False,False),
    ('rack',   '$.rack.AssetTag',                 'IDENTITY_SIGNAL',  None,        None,          'DIRECT',       None,           'STRING', True,  False),
    ('rack',   '$.rack.SerialNumber',             'IDENTITY_SIGNAL',  None,        None,          'DIRECT',       None,           'STRING', True,  False),
    ('device', '$.device.DeviceType',             'ENTITY_FIELD',     None,        None,          'ENUM_MAP',     '{"Server":"DEVICE","PDU":"PDU"}','STRING',False,True),
    ('device', '$.device.PowerFeedA_Name',        'RELATIONSHIP',     None,        None,          'DIRECT',       None,           'STRING', False, False),
    ('device', '$.device.ip_address',             'IDENTITY_SIGNAL',  None,        None,          'DIRECT',       None,           'STRING', True,  False),
]
for (etype, path, target, ns, key, ttype, texpr, vtype, is_id, is_req) in nlyte_mappings:
    ns_v   = sq(ns)   if ns   else 'NULL'
    key_v  = sq(key)  if key  else 'NULL'
    expr_v = sq(texpr)if texpr else 'NULL'
    pg(f"INSERT INTO field_mapping (mapping_id, source_id, source_entity_type, source_field_path, canonical_target, canonical_namespace, canonical_key, transform_type, transform_expression, value_type, is_identity_field, is_required, created_at, updated_at) VALUES")
    pg(f"  ({sq(uid())}, {sq(nlyte_ss['source_id'])}, {sq(etype)}, {sq(path)}, {sq(target)}, {ns_v}, {key_v}, {sq(ttype)}, {expr_v}, {sq(vtype)}, {bf(is_id)}, {bf(is_req)}, {ts(ago(180))}, {ts(ago(1))});")

# Sunbird mappings
sunbird_ss = next((ss for ss in SOURCE_SYSTEMS if ss['vendor_name'] == 'Sunbird'), None)
if sunbird_ss:
    sunbird_mappings = [
        ('cabinet','$.cabinet.name',             'ENTITY_FIELD',     None,         None,         'DIRECT',  None,               'STRING', True,  True),
        ('cabinet','$.cabinet.MaxPowerCapacity',  'CAPACITY_SPEC',   'dcim.sunbird','power_kw',  'UNIT_CONVERT','value/1000',    'FLOAT',  False, False),
        ('cabinet','$.cabinet.CoolingZoneLabel',  'ENTITY_ATTRIBUTE','dcim.sunbird','cooling_zone','DIRECT', None,              'STRING', False, False),
        ('asset',  '$.asset.serialNumber',        'IDENTITY_SIGNAL',  None,        None,          'DIRECT',  None,              'STRING', True,  False),
        ('asset',  '$.asset.assetTag',            'IDENTITY_SIGNAL',  None,        None,          'DIRECT',  None,              'STRING', True,  False),
        ('asset',  '$.asset.ipAddress',           'IDENTITY_SIGNAL',  None,        None,          'DIRECT',  None,              'STRING', True,  False),
    ]
    for (etype, path, target, ns, key, ttype, texpr, vtype, is_id, is_req) in sunbird_mappings:
        ns_v = sq(ns) if ns else 'NULL'; key_v = sq(key) if key else 'NULL'
        expr_v = sq(texpr) if texpr else 'NULL'
        pg(f"INSERT INTO field_mapping (mapping_id, source_id, source_entity_type, source_field_path, canonical_target, canonical_namespace, canonical_key, transform_type, transform_expression, value_type, is_identity_field, is_required, created_at, updated_at) VALUES")
        pg(f"  ({sq(uid())}, {sq(sunbird_ss['source_id'])}, {sq(etype)}, {sq(path)}, {sq(target)}, {ns_v}, {key_v}, {sq(ttype)}, {expr_v}, {sq(vtype)}, {bf(is_id)}, {bf(is_req)}, {ts(ago(180))}, {ts(ago(1))});")
pg("")

# ── ENTITY RESOLUTION RULES
pg("-- ENTITY RESOLUTION RULES")
for t in TENANTS:
    rules = [
        ('Primary — Serial Number Match',  'EXACT_SERIAL',      '{"field":"serial_number"}',         0.95, 'DCIM_WINS',         1),
        ('Secondary — Asset Tag',          'ASSET_TAG',         '{"field":"asset_tag"}',             0.90, 'HIGHEST_CONFIDENCE',2),
        ('Tertiary — MAC Address',         'MAC_ADDRESS',       '{"field":"mac_address"}',           0.88, 'HIGHEST_CONFIDENCE',3),
        ('Fallback — Rack+U-Slot',         'RACK_USLOT_POSITION','{"rack_field":"rack_name","u_field":"rack_u_slot"}',0.80,'MANUAL_REVIEW',4),
        ('SNMP — OID Prefix',              'OID_PREFIX',        '{"oid_prefix":"1.3.6.1.4.1"}',      0.75, 'HIGHEST_CONFIDENCE',5),
        ('Tertiary — IP Address',          'IP_ADDRESS',        '{"field":"ip_address"}',            0.70, 'MANUAL_REVIEW',     6),
    ]
    for rule_name, strategy, criteria, conf, conflict, priority in rules:
        pg(f"INSERT INTO entity_resolution_rule (rule_id, tenant_id, rule_name, match_strategy, match_criteria, confidence_threshold, conflict_resolution, priority, is_active, created_at) VALUES")
        pg(f"  ({sq(uid())}, {sq(t['tenant_id'])}, {sq(rule_name)}, {sq(strategy)}, {sq(criteria)}, {conf}, {sq(conflict)}, {priority}, TRUE, {ts(ago(180))});")
pg("")

# ── ITSM INTEGRATION CONFIG
pg("-- ITSM INTEGRATION CONFIG")
for t in TENANTS:
    pg(f"INSERT INTO itsm_integration_config (config_id, tenant_id, target_system, target_system_url, auth_type, auth_config, trigger_event_type, payload_mapping_template, incident_type_map, severity_map, is_active, created_at, updated_at) VALUES")
    pg(f"  ({sq(uid())}, {sq(t['tenant_id'])}, 'SERVICENOW',")
    pg(f"   'https://itsm.{t['slug']}.internal/api/now/table/incident',")
    pg(f"   'BEARER', {sq(json.dumps({'token_env': 'SNOW_TOKEN'}))},")
    pg(f"   'BOTH',")
    pg(f"   {sq(json.dumps({'short_description': '{{drift_type}}: {{canonical_name}}','description': '{{description}}','caller_id': 'flowcore-agent','category': 'Infrastructure'}))},")
    pg(f"   {sq(json.dumps({'DRIFT_EVENT': 'infrastructure_alert','CORRELATED_INCIDENT': 'infrastructure_incident'}))},")
    pg(f"   {sq(json.dumps({'CRITICAL': '1','HIGH': '2','MAJOR': '2','MEDIUM': '3','MINOR': '3'}))},")
    pg(f"   TRUE, {ts(ago(180))}, {ts(ago(1))});")
pg("")

# ── USERS
pg("-- USERS")
USERS = []
user_defs = [
    ('noc.operator.1@enea.internal',     'Marco Ferretti',     'NOC_OPERATOR',    0),
    ('noc.operator.2@enea.internal',     'Giulia Rossi',       'NOC_OPERATOR',    0),
    ('change.manager@enea.internal',     'Luca Marino',        'CHANGE_MANAGER',  0),
    ('dc.admin@enea.internal',           'Sofia Conti',        'DC_ADMIN',        0),
    ('platform.admin@enea.internal',     'Alessandro Ricci',   'PLATFORM_ADMIN',  0),
    ('noc.operator.1@meridian.internal', 'James Carter',       'NOC_OPERATOR',    1),
    ('noc.operator.2@meridian.internal', 'Sarah Chen',         'NOC_OPERATOR',    1),
    ('dc.admin@meridian.internal',       'Michael Torres',     'DC_ADMIN',        1),
    ('platform.admin@meridian.internal', 'Emily Walsh',        'PLATFORM_ADMIN',  1),
]
for email, display, role, tenant_idx in user_defs:
    u = {'user_id': uid(), 'tenant_id': TENANTS[tenant_idx]['tenant_id'],
         'email': email, 'display_name': display, 'rbac_role': role,
         'last_login_at': ago(hours=random.randint(0, 72))}
    USERS.append(u)
    pg(f"INSERT INTO \"user\" (user_id, tenant_id, email, display_name, rbac_role, is_active, created_at, last_login_at) VALUES")
    pg(f"  ({sq(u['user_id'])}, {sq(u['tenant_id'])}, {sq(u['email'])}, {sq(u['display_name'])},")
    pg(f"   {sq(u['rbac_role'])}, TRUE, {ts(ago(200))}, {ts(u['last_login_at'])});")
pg("")

# ── SYNC LOGS (one per source per day for last 7 days)
pg("-- SYNC LOGS")
for ss in SOURCE_SYSTEMS:
    if ss['source_class'] == 'DCIM':
        for day_back in range(7):
            start_t = ago(days=day_back, hours=random.randint(0,2))
            recs = random.randint(400, 1200)
            mapped = int(recs * random.uniform(0.94, 0.99))
            rejected = recs - mapped
            pg(f"INSERT INTO sync_log (log_id, source_id, tenant_id, sync_type, sync_mode, records_received, records_mapped, records_rejected, entities_created, entities_updated, duration_ms, started_at, completed_at, status) VALUES")
            pg(f"  ({sq(uid())}, {sq(ss['source_id'])}, {sq(ss['tenant_id'])}, 'DCIM_SYNC', 'INCREMENTAL',")
            pg(f"   {recs}, {mapped}, {rejected}, {random.randint(0,5)}, {random.randint(10,120)},")
            pg(f"   {fl(random.uniform(4000, 45000))}, {ts(start_t)}, {ts(start_t + datetime.timedelta(seconds=random.randint(30,120)))}, 'COMPLETED');")
pg("")

# ── DISCOVERY SCAN LOGS
pg("-- DISCOVERY SCAN LOGS")
for site in SITES:
    disc_ss = SITE_DISC_SOURCE[site['site_id']]
    for day_back in range(7):
        start_t = ago(days=day_back, hours=random.randint(2, 8))
        targeted = random.randint(254, 512)
        responded = int(targeted * random.uniform(0.70, 0.95))
        pg(f"INSERT INTO discovery_scan_log (scan_id, source_id, tenant_id, scan_type, target_range, hosts_targeted, hosts_responded, entities_discovered, entities_created, entities_updated, duration_ms, started_at, completed_at, status) VALUES")
        pg(f"  ({sq(uid())}, {sq(disc_ss['source_id'])}, {sq(disc_ss['tenant_id'])}, 'SNMP_WALK',")
        pg(f"   {sq(disc_ss['connection_config'])},")
        pg(f"   {targeted}, {responded}, {responded + random.randint(0, responded//2)},")
        pg(f"   {random.randint(0, 5)}, {random.randint(20, 200)},")
        pg(f"   {fl(random.uniform(30000, 180000))}, {ts(start_t)},")
        pg(f"   {ts(start_t + datetime.timedelta(seconds=random.randint(60, 300)))}, 'COMPLETED');")
pg("")

# =============================================================================
# PHASE 5 — METRIC CATALOGUE & TIMESCALEDB SEED
# =============================================================================

print(">>> Phase 5: Metric catalogue, source mappings, alert catalogue...")

tsd("-- METRIC CATALOGUE")
METRIC_CATALOGUE = []
for t in TENANTS:
    for (name, family, mtype, unit, agg, warn, crit) in METRIC_DEFS:
        m = {'metric_id': uid(), 'tenant_id': t['tenant_id'],
             'canonical_metric_name': name, 'metric_family': family,
             'metric_type': mtype, 'unit': unit, 'aggregation_default': agg,
             'alert_threshold_warn': warn, 'alert_threshold_crit': crit}
        METRIC_CATALOGUE.append(m)
        warn_v = str(warn) if warn is not None else 'NULL'
        crit_v = str(crit) if crit is not None else 'NULL'
        tsd(f"INSERT INTO metric_catalogue (metric_id, tenant_id, canonical_metric_name, metric_family, metric_type, unit, aggregation_default, alert_threshold_warn, alert_threshold_crit, is_active, created_at) VALUES")
        tsd(f"  ({sq(m['metric_id'])}, {sq(m['tenant_id'])}, {sq(name)}, {sq(family)}, {sq(mtype)},")
        tsd(f"   {sq(unit)}, {sq(agg)}, {warn_v}, {crit_v}, TRUE, {ts(ago(180))});")
tsd("")

# Quick lookup: (tenant_id, metric_name) -> metric_id
METRIC_ID_MAP = {(m['tenant_id'], m['canonical_metric_name']): m['metric_id']
                 for m in METRIC_CATALOGUE}

# METRIC SOURCE MAPPINGS
tsd("-- METRIC SOURCE MAPPINGS")
for ss in SOURCE_SYSTEMS:
    if ss['source_class'] not in ('TELEMETRY',): continue
    telem_vendor = ss['vendor_name']
    metric_map = PROMETHEUS_METRIC_MAP if telem_vendor == 'Prometheus' else SNMP_METRIC_MAP
    # Find metrics for this tenant
    tenant_metrics = [m for m in METRIC_CATALOGUE if m['tenant_id'] == ss['tenant_id']]
    for m in tenant_metrics:
        if m['canonical_metric_name'] in metric_map:
            src_name, src_expr, scale = metric_map[m['canonical_metric_name']]
            tsd(f"INSERT INTO metric_source_mapping (mapping_id, metric_id, source_id, source_metric_name, unit_conversion_expr, scale_factor, created_at) VALUES")
            tsd(f"  ({sq(uid())}, {sq(m['metric_id'])}, {sq(ss['source_id'])},")
            tsd(f"   {sq(src_name)}, {sq(src_expr)}, {scale}, {ts(ago(180))});")
tsd("")

# ALERT CATALOGUE
tsd("-- ALERT CATALOGUE")
ALERT_CATALOGUE = []
for t in TENANTS:
    for (name, category, sev, scope) in ALERT_DEFS:
        a = {'alert_type_id': uid(), 'tenant_id': t['tenant_id'],
             'canonical_alert_name': name, 'alert_category': category,
             'default_severity': sev, 'entity_class_scope': scope}
        ALERT_CATALOGUE.append(a)
        tsd(f"INSERT INTO alert_catalogue (alert_type_id, tenant_id, canonical_alert_name, alert_category, default_severity, entity_class_scope, is_active) VALUES")
        tsd(f"  ({sq(a['alert_type_id'])}, {sq(a['tenant_id'])}, {sq(name)}, {sq(category)}, {sq(sev)}, {sq(scope)}, TRUE);")
tsd("")

ALERT_ID_MAP = {(a['tenant_id'], a['canonical_alert_name']): a['alert_type_id']
                for a in ALERT_CATALOGUE}

# =============================================================================
# PHASE 6 — METRIC DATAPOINTS (30 days, 5-min interval for DEVICE entities)
# =============================================================================

print(f">>> Phase 6: Generating {DAYS}-day metric time series (this may take a moment)...")

# Metric generation parameters per metric name
METRIC_PARAMS = {
    'cpu_utilisation_pct':        {'base': 35, 'amp': 40, 'noise': 5,   'min': 0,  'max': 100},
    'mem_utilisation_pct':        {'base': 55, 'amp': 20, 'noise': 3,   'min': 0,  'max': 100},
    'power_draw_w':               {'base': 300,'amp': 150,'noise': 20,  'min': 50, 'max': 900},
    'inlet_temperature_c':        {'base': 22, 'amp': 6,  'noise': 1.5, 'min': 15, 'max': 45},
    'outlet_temperature_c':       {'base': 32, 'amp': 8,  'noise': 2,   'min': 20, 'max': 55},
    'fan_speed_rpm':              {'base': 5000,'amp':2000,'noise': 200, 'min':1000,'max':15000},
    'net_rx_bytes_per_sec':       {'base': 5e6,'amp': 8e6,'noise': 1e6, 'min': 0,  'max': 1e9},
    'net_tx_bytes_per_sec':       {'base': 3e6,'amp': 5e6,'noise': 5e5, 'min': 0,  'max': 1e9},
    'disk_io_read_bytes_per_sec': {'base': 2e7,'amp': 5e7,'noise': 5e6, 'min': 0,  'max': 1e9},
    'disk_io_write_bytes_per_sec':{'base': 1e7,'amp': 3e7,'noise': 3e6, 'min': 0,  'max': 1e9},
    'pdu_total_load_w':           {'base': 3000,'amp':1000,'noise': 100,'min': 500,'max': 8000},
    'pdu_outlet_current_a':       {'base': 8,  'amp': 6,  'noise': 0.5, 'min': 0,  'max': 24},
    'storage_utilisation_pct':    {'base': 60, 'amp': 15, 'noise': 2,   'min': 0,  'max': 100},
    'bandwidth_utilisation_pct':  {'base': 30, 'amp': 30, 'noise': 5,   'min': 0,  'max': 100},
    'error_count':                {'base': 0,  'amp': 2,  'noise': 1,   'min': 0,  'max': 1000},
    'packet_loss_pct':            {'base': 0,  'amp': 0.5,'noise': 0.2, 'min': 0,  'max': 100},
    'ups_battery_pct':            {'base': 95, 'amp': 5,  'noise': 1,   'min': 0,  'max': 100},
    'cooling_setpoint_c':         {'base': 18, 'amp': 2,  'noise': 0.5, 'min': 15, 'max': 28},
    'airflow_cfm':                {'base': 800,'amp': 200,'noise': 50,  'min': 0,  'max': 3000},
    'rack_space_u_used':          {'base': 30, 'amp': 5,  'noise': 1,   'min': 0,  'max': 48},
}

def simulate_metric(metric_name, t_hours, dev_phase=0, anomaly=False):
    """Simulate a realistic metric value using diurnal + weekly pattern + noise."""
    p  = METRIC_PARAMS.get(metric_name, {'base':50,'amp':20,'noise':5,'min':0,'max':100})
    # Diurnal cycle (24h) + weekly cycle (168h)
    diurnal = math.sin(2 * math.pi * (t_hours % 24) / 24 + dev_phase) * p['amp'] * 0.5
    weekly  = math.sin(2 * math.pi * (t_hours % 168) / 168) * p['amp'] * 0.2
    noise   = random.gauss(0, p['noise'])
    val     = p['base'] + diurnal + weekly + noise
    if anomaly:
        val += p['amp'] * random.uniform(1.2, 2.0)  # spike
    val = max(p['min'], min(p['max'], val))
    return round(val, 3)

# Sample devices for metrics (use all devices for rollups; limit datapoints)
DEVICE_SAMPLE = DEVICE_LIST  # all devices get metrics
PDU_SAMPLE    = PDU_LIST

# 5-min interval for 30 days = 8640 datapoints per entity per metric
# With ~500 devices × 5 key metrics × 8640 = 21.6M rows — too large for seed SQL.
# Use 1-hour interval for full coverage, 5-min for first 3 days on a sample.
INTERVAL_H = 1  # hours (hourly for all 30 days)
SAMPLE_5MIN_DAYS = 3

metric_dp_rows = []

DEVICE_METRIC_NAMES = [
    'cpu_utilisation_pct', 'mem_utilisation_pct', 'power_draw_w',
    'inlet_temperature_c', 'net_rx_bytes_per_sec',
]
PDU_METRIC_NAMES = ['pdu_total_load_w', 'pdu_outlet_current_a']

def flush_metric_batch():
    if not metric_dp_rows: return
    BSIZE = 500
    for i in range(0, len(metric_dp_rows), BSIZE):
        batch = metric_dp_rows[i:i+BSIZE]
        tsd("INSERT INTO metric_datapoint (tenant_id, entity_id, entity_class, metric_id, source_id, value, event_ts, ingest_ts, quality_flag) VALUES")
        for j, row in enumerate(batch):
            suffix = ';' if j == len(batch)-1 else ','
            tsd(f"  {row}{suffix}")
        tsd("")

total_hours = DAYS * 24
n_steps = total_hours // INTERVAL_H

# Pick a random anomaly window per tenant (for realistic incident generation later)
ANOMALY_WINDOWS = {}
for t in TENANTS:
    t_devs = [d for d in DEVICE_LIST if d['tenant_id'] == t['tenant_id']]
    if t_devs:
        anon_dev = random.choice(t_devs)
        anon_start = random.randint(DAYS//2 * 24, (DAYS-3) * 24)  # hours from START
        ANOMALY_WINDOWS[t['tenant_id']] = {
            'entity_id': anon_dev['entity_id'],
            'start_h': anon_start,
            'end_h':   anon_start + random.randint(3, 8),
        }

dev_count = 0
for dev in DEVICE_SAMPLE:
    dev_phase = random.uniform(0, math.pi * 2)
    telem_ss  = SITE_TELEM_SOURCE.get(
        next((s['site_id'] for s in SITES if s['tenant_id'] == dev['tenant_id']), None))
    if not telem_ss: continue
    aw = ANOMALY_WINDOWS.get(dev['tenant_id'], {})

    for mn in DEVICE_METRIC_NAMES:
        mid = METRIC_ID_MAP.get((dev['tenant_id'], mn))
        if not mid: continue
        for step in range(0, n_steps, 1):
            t_hours = step * INTERVAL_H
            cur_ts  = START_TS + datetime.timedelta(hours=t_hours)
            is_anom = (aw.get('entity_id') == dev['entity_id'] and
                       aw.get('start_h', -1) <= t_hours <= aw.get('end_h', -1))
            val = simulate_metric(mn, t_hours, dev_phase, is_anom)
            ingest_t = cur_ts + datetime.timedelta(seconds=random.randint(1, 30))
            row = (f"({sq(dev['tenant_id'])},{sq(dev['entity_id'])},{sq('DEVICE')},"
                   f"{sq(mid)},{sq(telem_ss['source_id'])},"
                   f"{fl(val)},{ts(cur_ts)},{ts(ingest_t)},'VALID')")
            metric_dp_rows.append(row)

    if len(metric_dp_rows) >= 3000:
        flush_metric_batch()
        metric_dp_rows.clear()
    dev_count += 1

for pdu in PDU_SAMPLE:
    telem_ss = SITE_TELEM_SOURCE.get(
        next((s['site_id'] for s in SITES if s['tenant_id'] == pdu['tenant_id']), None))
    if not telem_ss: continue
    for mn in PDU_METRIC_NAMES:
        mid = METRIC_ID_MAP.get((pdu['tenant_id'], mn))
        if not mid: continue
        for step in range(0, n_steps, 2):  # 2h interval for PDUs
            t_hours = step * 2
            cur_ts  = START_TS + datetime.timedelta(hours=t_hours)
            val = simulate_metric(mn, t_hours, random.uniform(0, math.pi))
            ingest_t = cur_ts + datetime.timedelta(seconds=random.randint(1, 60))
            row = (f"({sq(pdu['tenant_id'])},{sq(pdu['entity_id'])},{sq('PDU')},"
                   f"{sq(mid)},{sq(telem_ss['source_id'])},"
                   f"{fl(val)},{ts(cur_ts)},{ts(ingest_t)},'VALID')")
            metric_dp_rows.append(row)

flush_metric_batch()
metric_dp_rows.clear()
print(f"    Metric datapoints written for {len(DEVICE_SAMPLE)} devices + {len(PDU_SAMPLE)} PDUs")

# =============================================================================
# PHASE 7 — METRIC ROLLUPS (hourly and daily summaries)
# =============================================================================

print(">>> Phase 7: Generating metric rollups and baselines...")

rollup_rows = []

def flush_rollup_batch():
    if not rollup_rows: return
    BSIZE = 400
    for i in range(0, len(rollup_rows), BSIZE):
        batch = rollup_rows[i:i+BSIZE]
        tsd("INSERT INTO metric_rollup (tenant_id, entity_id, entity_class, metric_id, window_start, window_size, avg_value, min_value, max_value, p50_value, p95_value, p99_value, sample_count, quality_summary) VALUES")
        for j, row in enumerate(batch):
            tsd(f"  {row}{';' if j==len(batch)-1 else ','}")
        tsd("")

# Daily rollups for all devices × 5 metrics × 30 days
for dev in DEVICE_SAMPLE[:100]:  # limit for seed file size
    dev_phase = random.uniform(0, math.pi * 2)
    for mn in DEVICE_METRIC_NAMES:
        mid = METRIC_ID_MAP.get((dev['tenant_id'], mn))
        if not mid: continue
        for day_back in range(DAYS):
            win_start = START_TS + datetime.timedelta(days=day_back)
            # Simulate 24 hourly samples
            samples = [simulate_metric(mn, day_back*24 + h, dev_phase) for h in range(24)]
            samples.sort()
            avg_v = round(sum(samples)/len(samples), 3)
            row = (f"({sq(dev['tenant_id'])},{sq(dev['entity_id'])},{sq('DEVICE')},"
                   f"{sq(mid)},{ts(win_start)},'24h',"
                   f"{avg_v},{fl(samples[0])},{fl(samples[-1])},"
                   f"{fl(samples[11])},{fl(samples[22])},{fl(samples[23])},"
                   f"24,'CLEAN')")
            rollup_rows.append(row)

    if len(rollup_rows) >= 2000:
        flush_rollup_batch()
        rollup_rows.clear()

flush_rollup_batch()
rollup_rows.clear()

# METRIC BASELINES
tsd("-- METRIC BASELINES (computed from rollup history)")
for dev in DEVICE_SAMPLE[:50]:
    dev_phase = random.uniform(0, math.pi * 2)
    for mn in DEVICE_METRIC_NAMES:
        mid = METRIC_ID_MAP.get((dev['tenant_id'], mn))
        if not mid: continue
        p = METRIC_PARAMS.get(mn, {'base':50,'amp':20,'noise':5,'min':0,'max':100})
        mean_v   = round(p['base'] + random.gauss(0, p['noise']), 3)
        stddev_v = round(p['noise'] * 1.5, 3)
        tsd(f"INSERT INTO metric_baseline (baseline_id, tenant_id, entity_id, metric_id, mean_value, stddev_value, p5_value, p95_value, baseline_window_days, sample_count, computed_at, valid_from, valid_to) VALUES")
        tsd(f"  ({sq(uid())}, {sq(dev['tenant_id'])}, {sq(dev['entity_id'])}, {sq(mid)},")
        tsd(f"   {mean_v}, {stddev_v}, {round(mean_v - 2*stddev_v, 3)}, {round(mean_v + 2*stddev_v, 3)},")
        tsd(f"   '30', {DAYS * 24}, {ts(ago(1))}, {ts(START_TS)}, NULL);")
tsd("")

# =============================================================================
# PHASE 8 — ALERT EVENTS + STALE TELEMETRY + LOG EVENTS + GRAPH MUTATIONS
# =============================================================================

print(">>> Phase 8: Alert events, stale telemetry, log events, graph mutations...")

# ALERT EVENTS
tsd("-- ALERT EVENTS")
ALERT_EVENT_IDS = []  # store for incident linking

def make_alert_event(tenant_id, entity_id, entity_class, alert_name, severity,
                     source_id, metric_val=None, metric_id=None, event_t=None, status='ACTIVE'):
    alert_type_id = ALERT_ID_MAP.get((tenant_id, alert_name))
    if not alert_type_id: return None
    aid = uid()
    et  = event_t or rng_ts(ago(days=DAYS), NOW)
    it  = et + datetime.timedelta(seconds=random.randint(1, 30))
    mv  = str(fl(metric_val)) if metric_val is not None else 'NULL'
    mi  = sq(metric_id)       if metric_id else 'NULL'
    tsd(f"INSERT INTO alert_event (alert_id, tenant_id, entity_id, entity_class, alert_type_id, source_id, canonical_severity, source_severity, metric_value, metric_id, event_ts, ingest_ts, status) VALUES")
    tsd(f"  ({sq(aid)}, {sq(tenant_id)}, {sq(entity_id)}, {sq(entity_class)},")
    tsd(f"   {sq(alert_type_id)}, {sq(source_id)}, {sq(severity)}, {sq(severity)},")
    tsd(f"   {mv}, {mi}, {ts(et)}, {ts(it)}, {sq(status)});")
    return aid, et

# Generate alert storm around the anomaly window for each tenant
ALERT_EVENT_STORE = []  # list of (alert_id, tenant_id, entity_id, event_ts, severity)

for t in TENANTS:
    aw = ANOMALY_WINDOWS.get(t['tenant_id'], {})
    t_devs = [d for d in DEVICE_LIST if d['tenant_id'] == t['tenant_id']]
    telem_ss = next((ss for ss in SOURCE_SYSTEMS
                     if ss['tenant_id'] == t['tenant_id'] and ss['source_class'] == 'TELEMETRY'), None)
    if not telem_ss: continue

    # Anomaly window alerts (storm cluster)
    if aw:
        anon_dev = next((d for d in t_devs if d['entity_id'] == aw['entity_id']), None)
        if anon_dev:
            anon_start_ts = START_TS + datetime.timedelta(hours=aw['start_h'])
            anon_end_ts   = START_TS + datetime.timedelta(hours=aw['end_h'])
            cpu_mid = METRIC_ID_MAP.get((t['tenant_id'], 'cpu_utilisation_pct'))
            temp_mid= METRIC_ID_MAP.get((t['tenant_id'], 'inlet_temperature_c'))

            for alert_name, sev, mval, mid in [
                ('high_cpu_utilisation',   'CRITICAL', 95.2, cpu_mid),
                ('high_inlet_temperature', 'CRITICAL', 38.5, temp_mid),
                ('hardware_error_spike',   'HIGH',     None,  None),
                ('fan_failure',            'CRITICAL', None,  None),
            ]:
                for repeat in range(random.randint(3, 8)):
                    et = rng_ts(anon_start_ts, anon_end_ts)
                    res = make_alert_event(t['tenant_id'], anon_dev['entity_id'],
                                          'DEVICE', alert_name, sev,
                                          telem_ss['source_id'], mval, mid, et, 'RESOLVED')
                    if res:
                        ALERT_EVENT_STORE.append((res[0], t['tenant_id'], anon_dev['entity_id'], res[1], sev))

            # Cascade: downstream devices also alert
            cascade_devs = random.sample(t_devs, min(8, len(t_devs)))
            for cd in cascade_devs:
                et = rng_ts(anon_start_ts,
                             anon_start_ts + datetime.timedelta(hours=2))
                res = make_alert_event(t['tenant_id'], cd['entity_id'], 'DEVICE',
                                       'high_cpu_utilisation', 'HIGH',
                                       telem_ss['source_id'], random.uniform(82, 94), cpu_mid, et, 'RESOLVED')
                if res:
                    ALERT_EVENT_STORE.append((res[0], t['tenant_id'], cd['entity_id'], res[1], 'HIGH'))

    # Background alerts (scattered over 30 days)
    for _ in range(60):
        dev = random.choice(t_devs)
        alert_name = random.choice(['high_cpu_utilisation','high_memory_utilisation',
                                    'high_storage_utilisation','high_packet_loss',
                                    'hardware_error_spike'])
        sev_map = {'high_cpu_utilisation':'HIGH','high_memory_utilisation':'MEDIUM',
                   'high_storage_utilisation':'MEDIUM','high_packet_loss':'HIGH',
                   'hardware_error_spike':'HIGH'}
        sev = sev_map[alert_name]
        et  = rng_ts(START_TS, NOW)
        status = random.choices(['RESOLVED','ACTIVE'],weights=[80,20])[0]
        res = make_alert_event(t['tenant_id'], dev['entity_id'], 'DEVICE',
                               alert_name, sev, telem_ss['source_id'],
                               random.uniform(75, 98), None, et, status)
        if res:
            ALERT_EVENT_STORE.append((res[0], t['tenant_id'], dev['entity_id'], res[1], sev))

    # PDU alerts
    t_pdus = [p for p in PDU_LIST if p['tenant_id'] == t['tenant_id']]
    for _ in range(10):
        pdu = random.choice(t_pdus) if t_pdus else None
        if not pdu: continue
        res = make_alert_event(t['tenant_id'], pdu['entity_id'], 'PDU',
                               'pdu_overload', 'CRITICAL', telem_ss['source_id'],
                               random.uniform(7500, 9000), None,
                               rng_ts(ago(days=DAYS), NOW),
                               random.choices(['RESOLVED','ACTIVE'],[85,15])[0])
        if res:
            ALERT_EVENT_STORE.append((res[0], t['tenant_id'], pdu['entity_id'], res[1], 'CRITICAL'))

tsd("")

# STALE TELEMETRY EVENTS
tsd("-- STALE TELEMETRY EVENTS")
for t in TENANTS:
    t_devs = [d for d in DEVICE_LIST if d['tenant_id'] == t['tenant_id']]
    disc_ss = next((ss for ss in SOURCE_SYSTEMS
                    if ss['tenant_id'] == t['tenant_id'] and ss['source_class'] == 'DISCOVERY'), None)
    if not disc_ss: continue
    stale_sample = random.sample(t_devs, min(8, len(t_devs)))
    for dev in stale_sample:
        stale_t = rng_ts(ago(days=DAYS), ago(days=1))
        resolved_t = stale_t + datetime.timedelta(minutes=random.randint(6, 60))
        tsd(f"INSERT INTO stale_telemetry_event (event_id, tenant_id, entity_id, entity_class, source_id, silence_duration_s, threshold_s, status, stale_since, resolved_at) VALUES")
        tsd(f"  ({sq(uid())}, {sq(t['tenant_id'])}, {sq(dev['entity_id'])}, 'DEVICE',")
        tsd(f"   {sq(disc_ss['source_id'])}, {random.randint(310, 1200)}, 300, 'RESOLVED',")
        tsd(f"   {ts(stale_t)}, {ts(resolved_t)});")
tsd("")

# LOG EVENTS
tsd("-- LOG EVENTS (ELK/OpenSearch, FR-TL-03)")
log_templates = [
    ('INFO',  'kernel',   'NIC driver loaded successfully',       {'driver': 'ixgbe', 'speed': '10G'}),
    ('WARN',  'hardware', 'DIMM correctable error detected',      {'dimm_slot': 'A2', 'error_count': 1}),
    ('ERROR', 'hardware', 'Fan module degraded, speed below threshold', {'fan_id': 3, 'rpm': 1200}),
    ('INFO',  'os',       'System boot complete',                 {'uptime': 0}),
    ('WARN',  'network',  'Interface flap detected',              {'interface': 'eth0', 'count': 3}),
    ('ERROR', 'storage',  'Disk I/O latency spike detected',      {'disk': 'sda', 'latency_ms': 450}),
    ('INFO',  'security', 'SSH login successful',                 {'user': 'admin', 'src_ip': '10.0.1.5'}),
    ('CRITICAL','hardware','PSU failure detected — redundancy lost',{'psu_id': 1}),
    ('DEBUG', 'agent',    'SNMP polling completed',               {'oid_count': 142, 'duration_ms': 280}),
    ('WARN',  'thermal',  'Inlet temperature above normal range', {'temp_c': 29.5, 'threshold_c': 28}),
]
for t in TENANTS:
    t_devs = [d for d in DEVICE_LIST if d['tenant_id'] == t['tenant_id']]
    disc_ss = next((ss for ss in SOURCE_SYSTEMS
                    if ss['tenant_id'] == t['tenant_id'] and ss['source_class'] == 'DISCOVERY'), None)
    if not disc_ss: continue
    for _ in range(200):
        dev   = random.choice(t_devs)
        tmpl  = random.choice(log_templates)
        et    = rng_ts(START_TS, NOW)
        it    = et + datetime.timedelta(seconds=random.randint(1, 10))
        fields = dict(tmpl[3])
        fields['hostname'] = dev['canonical_name']
        tsd(f"INSERT INTO log_event (log_id, tenant_id, entity_id, entity_class, source_id, log_level, log_source, message, structured_fields, event_ts, ingest_ts, quality_flag) VALUES")
        tsd(f"  ({sq(uid())}, {sq(t['tenant_id'])}, {sq(dev['entity_id'])}, 'DEVICE',")
        tsd(f"   {sq(disc_ss['source_id'])}, {sq(tmpl[0])}, {sq(tmpl[1])}, {sq(tmpl[2])},")
        tsd(f"   {sq(json.dumps(fields))}, {ts(et)}, {ts(it)}, 'VALID');")
tsd("")

# GRAPH MUTATION LOG
tsd("-- GRAPH MUTATION LOG")
for t in TENANTS:
    t_devs = [d for d in DEVICE_LIST if d['tenant_id'] == t['tenant_id']]
    for day_back in range(DAYS):
        n_mutations = random.randint(1, 8)
        for _ in range(n_mutations):
            dev = random.choice(t_devs)
            ops = ['CREATE_NODE','UPDATE_NODE','CREATE_EDGE','UPDATE_EDGE']
            op  = random.choice(ops)
            occurred = rng_ts(START_TS + datetime.timedelta(days=day_back),
                              START_TS + datetime.timedelta(days=day_back+1))
            before = json.dumps({'operational_status': 'ONLINE', 'health_score': round(random.uniform(0.6,1.0),3)})
            after  = json.dumps({'operational_status': random.choice(['ONLINE','DEGRADED']), 'health_score': round(random.uniform(0.6,1.0),3)})
            tsd(f"INSERT INTO graph_mutation_log (tenant_id, mutation_id, operation_type, entity_class, entity_id, source_service, kafka_topic, before_state, after_state, occurred_at) VALUES")
            tsd(f"  ({sq(t['tenant_id'])}, {sq(uid())}, {sq(op)}, 'DEVICE', {sq(dev['entity_id'])},")
            tsd(f"   'graph-updater-service', 'graph.mutations', {sq(before)}, {sq(after)}, {ts(occurred)});")
tsd("")

# =============================================================================
# PHASE 9 — LAYER 4 AGENT OUTPUTS
# =============================================================================

print(">>> Phase 9: Agent outputs — drift events, incidents, forecasts, anomalies...")

pg("-- ================================================================")
pg("-- LAYER 4: AGENT OUTPUT DATA")
pg("-- ================================================================")
pg("")

AGENT_VER_TOPO  = 'topology-reconciliation-agent@1.4.2'
AGENT_VER_CLASS = 'classification-capability-agent@1.4.2'
AGENT_VER_CORR  = 'correlation-root-cause-agent@1.2.1'
AGENT_VER_PRED  = 'prediction-capacity-agent@1.1.0'
AGENT_VER_WI    = 'what-if-planning-agent@1.0.3'
MLFLOW_RUN      = lambda: f"mlflow-run-{uid()[:12]}"

# ── CLASSIFICATION RESULTS (for all devices)
pg("-- CLASSIFICATION RESULTS")
device_type_map = {
    'server':  [('ToR-Switch', {'routing_enabled':False,'poe_capable':False,'redundant_psu':True}),
                ('GPU-Server', {'gpu_count':8,'rdma_capable':True,'redundant_psu':True}),
                ('Compute-Server', {'redundant_psu':True,'ipmi_enabled':True})],
    'switch':  [('ToR-Switch', {'routing_enabled':True,'poe_capable':False,'bgp_capable':True}),
                ('Spine-Switch',{'routing_enabled':True,'bgp_capable':True,'mpls_capable':True})],
    'storage': [('SAN-Array',  {'fc_capable':True,'nvme_capable':True,'dedup_enabled':True}),
                ('NAS-Array',  {'nfs_capable':True,'smb_capable':True})],
    'firewall':[('NGFW',       {'ips_enabled':True,'ssl_inspection':True,'ha_capable':True})],
}
for dev in DEVICE_LIST[:300]:  # classification for first 300 devices
    role = dev['canonical_type'].lower()
    role_key = 'server'
    for k in device_type_map:
        if k in role: role_key = k; break
    choices = device_type_map.get(role_key, device_type_map['server'])
    inf_type, caps = random.choice(choices)
    conf  = round(random.uniform(0.72, 0.99), 3)
    needs_review = conf < 0.85
    evidence = json.dumps([{'signal_type': 'SNMP_OID', 'value': '1.3.6.1.4.1.' + str(random.randint(100,9999))},
                            {'signal_type': 'HOSTNAME', 'value': dev['canonical_name']}])
    pg(f"INSERT INTO classification_result (result_id, entity_id, tenant_id, inferred_entity_type, capability_flags, confidence_score, needs_review, evidence_signals, mlflow_run_id, classified_at) VALUES")
    pg(f"  ({sq(uid())}, {sq(dev['entity_id'])}, {sq(dev['tenant_id'])}, {sq(inf_type)},")
    pg(f"   {sq(json.dumps(caps))}, {conf}, {bf(needs_review)},")
    pg(f"   {sq(evidence)}, {sq(MLFLOW_RUN())}, {ts(rng_ts(ago(days=7), NOW))});")
pg("")

# ── NODE QUALITY SCORES
pg("-- NODE QUALITY SCORES")
for e in ALL_ENTITIES[:200]:
    comp = round(random.uniform(0.60, 1.0), 3)
    fresh= round(random.uniform(0.70, 1.0), 3)
    overall = round((comp + fresh) / 2, 3)
    missing = json.dumps([] if comp > 0.9 else ['vendor_model','serial_number'] if comp < 0.75 else ['serial_number'])
    pg(f"INSERT INTO node_quality_score (score_id, tenant_id, entity_id, entity_class, completeness_score, freshness_score, overall_score, missing_fields, computed_at) VALUES")
    pg(f"  ({sq(uid())}, {sq(e['tenant_id'])}, {sq(e['entity_id'])}, {sq(e['entity_class'])},")
    pg(f"   {comp}, {fresh}, {overall}, {sq(missing)}, {ts(ago(hours=random.randint(1,6)))});")
pg("")

# ── DRIFT EVENTS
pg("-- DRIFT EVENTS")
DRIFT_EVENT_IDS = []
drift_types_severity = [
    ('MISSING_IN_DCIM',      'MAJOR',    'Device discovered in reality but absent from DCIM inventory'),
    ('MISSING_IN_REALITY',   'CRITICAL', 'Device present in DCIM but not responding to discovery'),
    ('POSITION_MISMATCH',    'MINOR',    'Rack U-slot position differs between DCIM record and discovery'),
    ('ATTRIBUTE_CONFLICT',   'MINOR',    'Vendor model field differs between DCIM and discovery source'),
    ('POWER_PATH_MISMATCH',  'MAJOR',    'PDU power feed assignment differs from DCIM design'),
    ('CAPACITY_DISCREPANCY', 'MINOR',    'Rack power capacity differs between DCIM and metered value'),
]
for t in TENANTS:
    t_devs   = [d for d in DEVICE_LIST if d['tenant_id'] == t['tenant_id']]
    dcim_ss  = next((ss for ss in SOURCE_SYSTEMS if ss['tenant_id'] == t['tenant_id'] and ss['source_class'] == 'DCIM'), None)
    disc_ss  = next((ss for ss in SOURCE_SYSTEMS if ss['tenant_id'] == t['tenant_id'] and ss['source_class'] == 'DISCOVERY'), None)
    if not dcim_ss or not disc_ss: continue
    users_t  = [u for u in USERS if u['tenant_id'] == t['tenant_id'] and u['rbac_role'] in ('DC_ADMIN','NOC_OPERATOR')]

    for i, (drift_type, severity, desc) in enumerate(drift_types_severity * 3):
        dev = random.choice(t_devs)
        det_at = rng_ts(ago(days=DAYS), ago(days=1))
        status = random.choices(['OPEN','ACCEPTED','DISMISSED','RESOLVED'],
                                weights=[30,20,15,35])[0]
        res_at = det_at + datetime.timedelta(hours=random.randint(2, 48)) if status == 'RESOLVED' else None
        itsm   = f"INC{random.randint(1000000,9999999)}" if status in ('ACCEPTED','RESOLVED') else None
        src_a  = json.dumps({'position': f"U{random.randint(1,42)}", 'power_kw': round(random.uniform(0.5,5),2)})
        src_b  = json.dumps({'position': f"U{random.randint(1,42)}", 'power_kw': round(random.uniform(0.5,5),2)})
        conf   = round(random.uniform(0.88, 0.99), 3)
        drift_id = uid()
        DRIFT_EVENT_IDS.append((drift_id, t['tenant_id'], dev['entity_id'], det_at))
        itsm_v = sq(itsm) if itsm else 'NULL'
        res_v  = ts(res_at) if res_at else 'NULL'
        pg(f"INSERT INTO drift_event (drift_id, tenant_id, drift_type, severity, affected_entity_id, affected_entity_class, source_a_id, source_a_state, source_b_id, source_b_state, conflict_field, description, detection_confidence, status, agent_version, itsm_ticket_ref, detected_at, resolved_at) VALUES")
        pg(f"  ({sq(drift_id)}, {sq(t['tenant_id'])}, {sq(drift_type)}, {sq(severity)},")
        pg(f"   {sq(dev['entity_id'])}, 'DEVICE', {sq(dcim_ss['source_id'])}, {sq(src_a)},")
        pg(f"   {sq(disc_ss['source_id'])}, {sq(src_b)}, {sq('rack_u_slot' if 'POSITION' in drift_type else 'canonical_name')},")
        pg(f"   {sq(desc)}, {conf}, {sq(status)}, {sq(AGENT_VER_TOPO)},")
        pg(f"   {itsm_v}, {ts(det_at)}, {res_v});")

        # Drift suggestions for open/accepted drifts
        if status in ('OPEN','ACCEPTED'):
            user = random.choice(users_t) if users_t else None
            decided_by_v = sq(user['user_id']) if (user and status=='ACCEPTED') else 'NULL'
            decided_at_v = ts(det_at + datetime.timedelta(hours=random.randint(1,24))) if status == 'ACCEPTED' else 'NULL'
            pg(f"INSERT INTO drift_suggestion (suggestion_id, drift_id, tenant_id, proposed_action, proposed_namespace_ref, operator_decision, decided_by, decided_at) VALUES")
            pg(f"  ({sq(uid())}, {sq(drift_id)}, {sq(t['tenant_id'])},")
            dev_name = dev["canonical_name"]
            pg(f"   {sq(f'Update DCIM record: set rack_u_slot to discovered value for {dev_name}')},")
            pg(f"   {sq('neo4j://proposed/' + drift_id[:8])},")
            pg(f"   {'NULL' if status=='OPEN' else sq('ACCEPTED')}, {decided_by_v}, {decided_at_v});")
pg("")

# ── CORRELATED INCIDENTS
pg("-- CORRELATED INCIDENTS")
INCIDENT_IDS = {}  # tenant_id -> list of incident_ids

for t in TENANTS:
    INCIDENT_IDS[t['tenant_id']] = []
    aw = ANOMALY_WINDOWS.get(t['tenant_id'], {})
    t_devs = [d for d in DEVICE_LIST if d['tenant_id'] == t['tenant_id']]
    t_alerts = [a for a in ALERT_EVENT_STORE if a[1] == t['tenant_id']]

    # Major incident (around anomaly window)
    if aw and t_alerts:
        root_dev = next((d for d in t_devs if d['entity_id'] == aw['entity_id']), random.choice(t_devs))
        anon_start_ts = START_TS + datetime.timedelta(hours=aw['start_h'])
        first_event_ts = anon_start_ts
        det_ts = first_event_ts + datetime.timedelta(seconds=random.randint(15, 45))
        aff_ids = [a[2] for a in t_alerts[:6]]
        contrib_alerts = [a[0] for a in t_alerts[:10]]
        inc_id = uid()
        INCIDENT_IDS[t['tenant_id']].append(inc_id)
        pg(f"INSERT INTO correlated_incident (incident_id, tenant_id, root_cause_entity_id, root_cause_entity_class, root_cause_label, confidence_score, evidence_entity_ids, contributing_alert_ids, affected_entity_count, severity, status, narrative, mlflow_run_id, first_event_at, detected_at, resolved_at, operator_verdict, is_false_positive, itsm_ticket_ref, agent_version) VALUES")
        pg(f"  ({sq(inc_id)}, {sq(t['tenant_id'])},")
        pg(f"   {sq(root_dev['entity_id'])}, 'DEVICE',")
        pg(f"   {sq('Fan module failure on ' + root_dev['canonical_name'] + ' caused thermal cascade')},")
        pg(f"   0.923, {sq(json.dumps(aff_ids[:6]))}, {sq(json.dumps(contrib_alerts[:10]))},")
        pg(f"   {len(aff_ids)}, 'CRITICAL', 'RESOLVED',")
        pg(f"   {sq('Fan module failure on ' + root_dev['canonical_name'] + ' caused inlet temperature to spike to 38.5°C. Thermal throttling on co-located devices propagated as high-CPU alerts within 4 minutes. Root cause confirmed as fan_module_3 physical failure. Redundancy lost. Resolved by hardware replacement at ' + str(det_ts + datetime.timedelta(hours=3)))},")
        pg(f"   {sq(MLFLOW_RUN())}, {ts(first_event_ts)}, {ts(det_ts)},")
        pg(f"   {ts(det_ts + datetime.timedelta(hours=random.randint(2,6)))},")
        pg(f"   'CONFIRMED', FALSE, {sq('INC' + str(random.randint(1000000,9999999)))}, {sq(AGENT_VER_CORR)});")

    # Background incidents
    for _ in range(random.randint(4, 8)):
        if not t_devs: continue
        root = random.choice(t_devs)
        first_t = rng_ts(START_TS, ago(days=2))
        det_t   = first_t + datetime.timedelta(seconds=random.randint(15, 60))
        sev     = random.choice(['HIGH','MEDIUM','LOW'])
        status  = random.choices(['RESOLVED','INVESTIGATING','DETECTED'],[60,20,20])[0]
        inc_id  = uid()
        INCIDENT_IDS[t['tenant_id']].append(inc_id)
        pg(f"INSERT INTO correlated_incident (incident_id, tenant_id, root_cause_entity_id, root_cause_entity_class, root_cause_label, confidence_score, evidence_entity_ids, contributing_alert_ids, affected_entity_count, severity, status, narrative, mlflow_run_id, first_event_at, detected_at, resolved_at, is_false_positive, agent_version) VALUES")
        pg(f"  ({sq(inc_id)}, {sq(t['tenant_id'])},")
        pg(f"   {sq(root['entity_id'])}, 'DEVICE',")
        pg(f"   {sq(random.choice(['High CPU load on ' + root['canonical_name'], 'Storage I/O saturation on ' + root['canonical_name'], 'Network congestion detected on ' + root['canonical_name']]))},")
        pg(f"   {round(random.uniform(0.70,0.95),3)}, {sq(json.dumps([root['entity_id']]))}, {sq(json.dumps([]))},")
        pg(f"   {random.randint(1,5)}, {sq(sev)}, {sq(status)},")
        pg(f"   {sq('Automated root cause analysis identified ' + root['canonical_name'] + ' as probable root cause based on alert timing and graph topology.')},")
        pg(f"   {sq(MLFLOW_RUN())}, {ts(first_t)}, {ts(det_t)},")
        pg(f"   {'NULL' if status!='RESOLVED' else ts(det_t + datetime.timedelta(hours=random.randint(1,4)))},")
        pg(f"   FALSE, {sq(AGENT_VER_CORR)});")
pg("")

# ── CAPACITY FORECASTS
pg("-- CAPACITY FORECASTS")
for t in TENANTS:
    t_racks = [r for r in RACK_LIST if r['tenant_id'] == t['tenant_id']]
    t_dcs   = [dc for dc in DATA_CENTERS if dc['tenant_id'] == t['tenant_id']]
    power_mid = METRIC_ID_MAP.get((t['tenant_id'], 'power_draw_w'))
    rack_u_mid= METRIC_ID_MAP.get((t['tenant_id'], 'rack_space_u_used'))

    sample_racks = random.sample(t_racks, min(20, len(t_racks)))
    for rack in sample_racks:
        for horizon, label, days_ahead in [(7,'7d',7),(30,'30d',30),(90,'90d',90)]:
            # Power forecast
            base_power = random.uniform(1500, 4500)
            growth     = 1 + random.uniform(0.02, 0.15) * (days_ahead/30)
            pred       = round(base_power * growth, 1)
            exh        = pred > 7500
            pg(f"INSERT INTO capacity_forecast (forecast_id, tenant_id, entity_id, entity_class, scope_level, metric_id, generated_at, horizon_ts, horizon_label, predicted_value, predicted_lower, predicted_upper, unit, exhaustion_flag, model_mape, mlflow_run_id, agent_version) VALUES")
            pg(f"  ({sq(uid())}, {sq(t['tenant_id'])}, {sq(rack['entity_id'])}, 'RACK', 'RACK',")
            pg(f"   {sq(power_mid) if power_mid else 'NULL'},")
            pg(f"   {ts(ago(hours=6))}, {ts(NOW + datetime.timedelta(days=days_ahead))},")
            pg(f"   {sq(label)}, {pred}, {round(pred*0.9,1)}, {round(pred*1.1,1)},")
            pg(f"   'W', {bf(exh)}, {round(random.uniform(0.04,0.09),4)},")
            pg(f"   {sq(MLFLOW_RUN())}, {sq(AGENT_VER_PRED)});")
        # Rack space forecast
        used_u = rack.get('rack_u_used', 30)
        for horizon, label, days_ahead in [(30,'30d',30),(90,'90d',90)]:
            pred_u = min(rack.get('rack_u_total',42), used_u + random.uniform(0, 8) * (days_ahead/30))
            exh_u  = pred_u >= rack.get('rack_u_total',42) * 0.95
            pg(f"INSERT INTO capacity_forecast (forecast_id, tenant_id, entity_id, entity_class, scope_level, metric_id, generated_at, horizon_ts, horizon_label, predicted_value, predicted_lower, predicted_upper, unit, exhaustion_flag, model_mape, mlflow_run_id, agent_version) VALUES")
            pg(f"  ({sq(uid())}, {sq(t['tenant_id'])}, {sq(rack['entity_id'])}, 'RACK', 'RACK',")
            pg(f"   {sq(rack_u_mid) if rack_u_mid else 'NULL'},")
            pg(f"   {ts(ago(hours=6))}, {ts(NOW + datetime.timedelta(days=days_ahead))},")
            pg(f"   {sq(label)}, {round(pred_u,1)}, {round(pred_u*0.95,1)}, {round(pred_u*1.05,1)},")
            pg(f"   'U', {bf(exh_u)}, {round(random.uniform(0.04,0.08),4)},")
            pg(f"   {sq(MLFLOW_RUN())}, {sq(AGENT_VER_PRED)});")
    # DC-level power forecast
    for dc in t_dcs:
        for horizon, label, days_ahead in [(30,'30d',30),(90,'90d',90)]:
            pred = round(dc['total_power_kw'] * random.uniform(0.60, 0.88) * (1 + 0.05*days_ahead/30), 1)
            exh  = pred >= dc['total_power_kw'] * 0.95
            pg(f"INSERT INTO capacity_forecast (forecast_id, tenant_id, entity_id, entity_class, scope_level, metric_id, generated_at, horizon_ts, horizon_label, predicted_value, predicted_lower, predicted_upper, unit, exhaustion_flag, model_mape, mlflow_run_id, agent_version) VALUES")
            pg(f"  ({sq(uid())}, {sq(t['tenant_id'])}, {sq(dc['dc_id'])}, 'DATA_CENTER', 'DATA_CENTER',")
            pg(f"   {sq(power_mid) if power_mid else 'NULL'},")
            pg(f"   {ts(ago(hours=6))}, {ts(NOW + datetime.timedelta(days=days_ahead))},")
            pg(f"   {sq(label)}, {pred}, {round(pred*0.92,1)}, {round(pred*1.08,1)},")
            pg(f"   'kW', {bf(exh)}, {round(random.uniform(0.03,0.08),4)},")
            pg(f"   {sq(MLFLOW_RUN())}, {sq(AGENT_VER_PRED)});")
pg("")

# ── ANOMALY FLAGS
pg("-- ANOMALY FLAGS")
for t in TENANTS:
    aw = ANOMALY_WINDOWS.get(t['tenant_id'], {})
    t_devs  = [d for d in DEVICE_LIST if d['tenant_id'] == t['tenant_id']]
    cpu_mid = METRIC_ID_MAP.get((t['tenant_id'], 'cpu_utilisation_pct'))
    temp_mid= METRIC_ID_MAP.get((t['tenant_id'], 'inlet_temperature_c'))

    # Anomaly window flags
    if aw:
        anon_dev = next((d for d in t_devs if d['entity_id'] == aw['entity_id']), None)
        if anon_dev and temp_mid:
            anon_ts = START_TS + datetime.timedelta(hours=aw['start_h'])
            for dev_sigma, obs_val, bline, sev, mid in [
                (4.2, 38.5, 22.3, 'CRITICAL', temp_mid),
                (3.1, 95.2, 35.1, 'HIGH',     cpu_mid),
            ]:
                pg(f"INSERT INTO anomaly_flag (flag_id, tenant_id, entity_id, entity_class, metric_id, observed_value, baseline_mean, deviation_sigma, severity, mlflow_run_id, flagged_at, status) VALUES")
                pg(f"  ({sq(uid())}, {sq(t['tenant_id'])}, {sq(anon_dev['entity_id'])}, 'DEVICE',")
                pg(f"   {sq(mid) if mid else 'NULL'}, {obs_val}, {bline}, {dev_sigma},")
                pg(f"   {sq(sev)}, {sq(MLFLOW_RUN())}, {ts(anon_ts)}, 'RESOLVED');")

    # Background anomalies
    for _ in range(30):
        dev  = random.choice(t_devs)
        sigma= round(random.uniform(3.0, 6.5), 2)
        sev  = 'CRITICAL' if sigma > 5 else 'HIGH' if sigma > 4 else 'MEDIUM'
        bline= round(random.uniform(30, 60), 1)
        obs  = round(bline + sigma * random.uniform(4, 12), 1)
        pg(f"INSERT INTO anomaly_flag (flag_id, tenant_id, entity_id, entity_class, metric_id, observed_value, baseline_mean, deviation_sigma, severity, mlflow_run_id, flagged_at, status) VALUES")
        pg(f"  ({sq(uid())}, {sq(t['tenant_id'])}, {sq(dev['entity_id'])}, 'DEVICE',")
        pg(f"   {sq(cpu_mid) if cpu_mid else 'NULL'}, {obs}, {bline}, {sigma},")
        pg(f"   {sq(sev)}, {sq(MLFLOW_RUN())},")
        pg(f"   {ts(rng_ts(START_TS, NOW))},")
        pg(f"   {sq(random.choices(['OPEN','RESOLVED','ACKNOWLEDGED'],[20,65,15])[0])});")
pg("")

# ── FAILURE PROBABILITY SCORES
pg("-- FAILURE PROBABILITY SCORES")
for t in TENANTS:
    t_devs = [d for d in DEVICE_LIST if d['tenant_id'] == t['tenant_id']]
    scored = random.sample(t_devs, min(80, len(t_devs)))
    for dev in scored:
        age_days = dev.get('age_days', 365)
        base_prob = min(0.95, max(0.01,
            0.05 + (age_days / 1800) * 0.3 +
            (1 - dev['health_score']) * 0.4 +
            random.gauss(0, 0.05)))
        factors = {
            'thermal_history_score': round(random.uniform(0.1, 0.9), 3),
            'age_ratio':             round(age_days / 1825, 3),
            'error_rate_trend':      round(random.uniform(0.0, 0.3), 3),
            'anomaly_flag_count_30d':random.randint(0, 5),
            'last_maintenance_days': random.randint(0, 400),
        }
        pg(f"INSERT INTO failure_probability (score_id, tenant_id, entity_id, entity_class, probability_score, contributing_factors, horizon_label, mlflow_run_id, agent_version, computed_at) VALUES")
        pg(f"  ({sq(uid())}, {sq(t['tenant_id'])}, {sq(dev['entity_id'])}, 'DEVICE',")
        pg(f"   {round(base_prob,4)}, {sq(json.dumps(factors))},")
        pg(f"   '30d', {sq(MLFLOW_RUN())}, {sq(AGENT_VER_PRED)}, {ts(ago(hours=random.randint(1,24)))});")
pg("")

# ── SIMULATION SCENARIOS & RESULTS
pg("-- SIMULATION SCENARIOS & RESULTS")
for t in TENANTS:
    t_devs   = [d for d in DEVICE_LIST if d['tenant_id'] == t['tenant_id']]
    t_racks  = [r for r in RACK_LIST  if r['tenant_id'] == t['tenant_id']]
    cm_users = [u for u in USERS if u['tenant_id']==t['tenant_id'] and u['rbac_role']=='CHANGE_MANAGER']
    if not cm_users or not t_devs: continue

    scenarios = [
        ('PDU-A Failure Simulation — CRESCO Rack A001',
         'What if PDU-A fails on rack A001? Assess redundancy coverage.',
         'PDU_FAILURE', 'POWER'),
        ('ToR Switch Replacement Impact',
         'Simulate ToR switch going offline for maintenance window.',
         'MAINTENANCE_DOWNTIME', 'NETWORK'),
        ('Rack Power Capacity Upgrade',
         'Model impact of increasing rack power budget from 8kW to 12kW.',
         'CAPACITY_CHANGE', 'POWER'),
    ]
    for sc_name, sc_desc, failure_mode, change_type in scenarios:
        target = random.choice(t_devs + t_racks[:5])
        sc_id  = uid()
        created_by = random.choice(cm_users)
        chained = json.dumps([{'step': 1, 'type': failure_mode, 'target': target['entity_id']},
                               {'step': 2, 'type': 'ASSESS_REDUNDANCY', 'target': 'all'}])
        pg(f"INSERT INTO simulation_scenario (scenario_id, tenant_id, name, description, target_entity_id, target_entity_class, failure_mode, change_type, chained_steps, created_by, created_at, status, is_saved) VALUES")
        pg(f"  ({sq(sc_id)}, {sq(t['tenant_id'])}, {sq(sc_name)}, {sq(sc_desc)},")
        pg(f"   {sq(target['entity_id'])}, {sq(target['entity_class'])},")
        pg(f"   {sq(failure_mode)}, {sq(change_type)}, {sq(chained)},")
        pg(f"   {sq(created_by['user_id'])}, {ts(ago(days=random.randint(1,14)))}, 'COMPLETED', TRUE);")

        # Result
        n_affected = random.randint(3, 40)
        aff_ids    = random.sample([e['entity_id'] for e in t_devs], min(n_affected, len(t_devs)))
        sev_map    = {eid: random.choice(['CRITICAL','HIGH','MEDIUM','LOW']) for eid in aff_ids}
        exec_ms    = round(random.uniform(800, 8500), 1)  # NFR-04: must be < 10000
        pg(f"INSERT INTO simulation_result (result_id, scenario_id, tenant_id, affected_entity_count, affected_entity_ids, impact_severity_map, redundancy_assessment, estimated_degradation_pct, graph_snapshot_ref, execution_duration_ms, agent_version, executed_at) VALUES")
        pg(f"  ({sq(uid())}, {sq(sc_id)}, {sq(t['tenant_id'])},")
        pg(f"   {n_affected}, {sq(json.dumps(aff_ids))}, {sq(json.dumps(sev_map))},")
        pg(f"   {sq(random.choice(['N+1 maintained','Redundancy lost on A-leg','Full redundancy available']))},")
        pg(f"   {round(random.uniform(0, 35), 1)},")
        pg(f"   {sq('neo4j://snapshots/' + uid()[:12])},")
        pg(f"   {exec_ms}, {sq(AGENT_VER_WI)}, {ts(ago(days=random.randint(1,14)))});")
pg("")

# ── AUDIT LOG ENTRIES
pg("-- AUDIT LOG ENTRIES")
audit_actions = [
    ('DRIFT_SUGGESTION_ACCEPTED', 'drift_suggestion'),
    ('DRIFT_SUGGESTION_DISMISSED','drift_suggestion'),
    ('CLASSIFICATION_FEEDBACK',   'classification_result'),
    ('INCIDENT_VERDICT_SUBMITTED','correlated_incident'),
    ('SIMULATION_CREATED',        'simulation_scenario'),
    ('SOURCE_SYSTEM_CONFIGURED',  'source_system'),
    ('USER_LOGIN',                'user'),
    ('PLATFORM_CONFIG_UPDATED',   'platform_config'),
]
for t in TENANTS:
    t_users = [u for u in USERS if u['tenant_id'] == t['tenant_id']]
    for _ in range(100):
        user   = random.choice(t_users)
        action, res_type = random.choice(audit_actions)
        pg(f"INSERT INTO audit_log_entry (log_id, tenant_id, user_id, action, resource_type, resource_id, ip_address, change_payload, occurred_at, is_immutable) VALUES")
        pg(f"  ({sq(uid())}, {sq(t['tenant_id'])}, {sq(user['user_id'])},")
        pg(f"   {sq(action)}, {sq(res_type)}, {sq(uid())},")
        pg(f"   {sq(f'10.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}')},")
        pg(f"   {sq(json.dumps({'previous': 'OPEN', 'new': 'ACCEPTED'} if 'ACCEPTED' in action else {}))},")
        pg(f"   {ts(rng_ts(START_TS, NOW))}, TRUE);")
pg("")

# =============================================================================
# FINALIZE
# =============================================================================

# =============================================================================
# FINALIZE — write files, post-process SQL
# =============================================================================

def collapse_multiline_inserts(lines):
    """
    Post-processor: collapse split INSERT … VALUES / continuation patterns
    into single self-contained statements.

    Pattern emitted by the inline pg() calls:
        INSERT INTO foo (cols) VALUES          <- no semicolon at end
          (val1, val2, ...);                   <- continuation with semicolon

    Collapsed to:
        INSERT INTO foo (cols) VALUES (val1, val2, ...);

    Orphan guard: if a bare VALUES header is immediately followed by a
    non-data line (another INSERT, COMMIT, SET, comment) the header is
    dropped — but the triggering line is NOT consumed; the outer loop
    processes it normally on the next iteration.
    """
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip()

        # Detect a multi-line INSERT: VALUES with no semicolon and no opening paren
        if (stripped.upper().startswith('INSERT INTO') and
                'VALUES' in stripped.upper() and
                not stripped.endswith(';') and
                not stripped.endswith('(')):

            combined = stripped
            j = i + 1
            orphan = False

            while j < len(lines):
                cont = lines[j].strip()
                if not cont:        # skip blank lines in lookahead
                    j += 1
                    continue

                # If the next non-blank line is NOT a data row (i.e. starts with
                # a SQL keyword or comment), the VALUES header is an orphan.
                # Do NOT advance j — leave it for the outer loop to emit normally.
                if (cont.upper().startswith('INSERT') or
                        cont.upper().startswith('COMMIT') or
                        cont.upper().startswith('SET ') or
                        cont.upper().startswith('--')):
                    orphan = True
                    # i advances to j so outer loop picks up the keyword line next
                    i = j
                    break

                # Merge continuation data row
                combined = combined + ' ' + cont
                j += 1
                if cont.endswith(';'):
                    i = j
                    break
            else:
                i = j  # exhausted lines

            if not orphan:
                out.append(combined)
            # if orphan: discard just the bare header; outer loop handles keyword at new i

        else:
            out.append(stripped)
            i += 1

    return out


print(">>> Writing output files...")

# Append transaction terminators before writing
pg("COMMIT;")
pg("SET session_replication_role = DEFAULT;")
tsd("COMMIT;")

for filename, lines in [
    (os.path.join(OUT_DIR, 'postgresql_seed.sql'), pg_lines),
    (os.path.join(OUT_DIR, 'timescaledb_seed.sql'), ts_lines),
    (os.path.join(OUT_DIR, 'neo4j_seed.cypher'),   neo_lines),
]:
    # Post-process SQL files to collapse multi-line INSERTs
    if filename.endswith('.sql'):
        lines = collapse_multiline_inserts(lines)

    # Write with Unix line endings (LF only) — safe for both Linux containers
    # and Windows Git Bash / WSL psql via docker exec
    with open(filename, 'w', newline='\n', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    size_kb = os.path.getsize(filename) / 1024
    print(f"  {os.path.basename(filename)}: {size_kb:.0f} KB")

    # Quick validation: check no bare VALUES headers remain in SQL files
    if filename.endswith('.sql'):
        bare = 0
        with open(filename, 'r', encoding='utf-8') as f:
            for ln in f:
                s = ln.strip()
                if ('VALUES' in s.upper() and
                        s.upper().startswith('INSERT') and
                        not s.endswith(';') and
                        not s.endswith('(')):
                    bare += 1
        if bare:
            print(f"  WARNING: {bare} bare VALUES lines remain in {os.path.basename(filename)}")
        else:
            print(f"  ✓ {os.path.basename(filename)}: all INSERT statements are self-contained")

print(f"\n✓ Synthetic data generation complete.")
print(f"  Tenants:   {len(TENANTS)}")
print(f"  Sites:     {len(SITES)}")
print(f"  DCs:       {len(DATA_CENTERS)}")
print(f"  Entities:  {len(ALL_ENTITIES)} total ({len(DEVICE_LIST)} devices, {len(RACK_LIST)} racks)")
print(f"  Sources:   {len(SOURCE_SYSTEMS)}")
print(f"  Metrics:   {len(METRIC_CATALOGUE)}")
print(f"  Alerts:    {len(ALERT_CATALOGUE)}")
