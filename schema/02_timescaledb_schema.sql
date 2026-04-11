-- =============================================================================
-- FlowCore — TimescaleDB Schema
-- Layer 3: Telemetry & Live State
-- Version: 1.2  |  Requires TimescaleDB extension on PostgreSQL 15+
--
-- Design notes:
-- * create_hypertable calls use if_not_exists => TRUE so re-runs are safe.
-- * Compression policies are omitted — they require ALTER TABLE SET
--   (timescaledb.compress) plus specific column selections which are
--   version-sensitive. Enable manually after initial load if needed.
-- * ON_ERROR_STOP=1 is used by the loader, so every statement here must
--   be idempotent (IF NOT EXISTS / if_not_exists => TRUE throughout).
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================================================
-- METRIC CATALOGUE
-- =============================================================================

CREATE TABLE IF NOT EXISTS metric_catalogue (
    metric_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID NOT NULL,
    canonical_metric_name   VARCHAR(120) NOT NULL,
    metric_family           VARCHAR(60)
                              CHECK (metric_family IN ('POWER','THERMAL','COMPUTE',
                                     'NETWORK','STORAGE','COOLING','ENVIRONMENTAL')),
    metric_type             VARCHAR(20)
                              CHECK (metric_type IN ('GAUGE','COUNTER','HISTOGRAM','SUMMARY')),
    unit                    VARCHAR(30) NOT NULL,
    description             TEXT,
    aggregation_default     VARCHAR(20)
                              CHECK (aggregation_default IN ('AVG','SUM','MAX','MIN','P95')),
    alert_threshold_warn    FLOAT,
    alert_threshold_crit    FLOAT,
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, canonical_metric_name)
);

CREATE TABLE IF NOT EXISTS metric_source_mapping (
    mapping_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_id               UUID NOT NULL REFERENCES metric_catalogue(metric_id),
    source_id               UUID NOT NULL,
    source_metric_name      VARCHAR(200) NOT NULL,
    source_metric_path      VARCHAR(200),
    unit_conversion_expr    VARCHAR(200),
    scale_factor            FLOAT DEFAULT 1.0,
    entity_class_filter     VARCHAR(40),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- METRIC_DATAPOINT — primary hypertable
-- =============================================================================

CREATE TABLE IF NOT EXISTS metric_datapoint (
    tenant_id     UUID        NOT NULL,
    entity_id     UUID        NOT NULL,
    entity_class  VARCHAR(40),
    metric_id     UUID        NOT NULL REFERENCES metric_catalogue(metric_id),
    source_id     UUID        NOT NULL,
    value         FLOAT       NOT NULL,
    event_ts      TIMESTAMPTZ NOT NULL,
    ingest_ts     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    quality_flag  VARCHAR(20) NOT NULL DEFAULT 'VALID'
                    CHECK (quality_flag IN ('VALID','INTERPOLATED','SUSPECT','LATE','OUT_OF_RANGE'))
);

SELECT create_hypertable('metric_datapoint', 'event_ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mdp_dedup
    ON metric_datapoint(tenant_id, entity_id, metric_id, source_id, event_ts);

CREATE INDEX IF NOT EXISTS idx_mdp_entity_metric
    ON metric_datapoint(entity_id, metric_id, event_ts DESC);

-- =============================================================================
-- METRIC_ROLLUP
-- =============================================================================

CREATE TABLE IF NOT EXISTS metric_rollup (
    tenant_id       UUID        NOT NULL,
    entity_id       UUID        NOT NULL,
    entity_class    VARCHAR(40),
    metric_id       UUID        NOT NULL REFERENCES metric_catalogue(metric_id),
    window_start    TIMESTAMPTZ NOT NULL,
    window_size     VARCHAR(20) NOT NULL CHECK (window_size IN ('5m','1h','24h')),
    avg_value       FLOAT,
    min_value       FLOAT,
    max_value       FLOAT,
    p50_value       FLOAT,
    p95_value       FLOAT,
    p99_value       FLOAT,
    sample_count    INT,
    quality_summary VARCHAR(20)
                      CHECK (quality_summary IN ('CLEAN','PARTIAL','SPARSE','STALE'))
);

SELECT create_hypertable('metric_rollup', 'window_start',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE);

CREATE UNIQUE INDEX IF NOT EXISTS idx_rollup_dedup
    ON metric_rollup(tenant_id, entity_id, metric_id, window_size, window_start);

CREATE INDEX IF NOT EXISTS idx_rollup_entity
    ON metric_rollup(entity_id, metric_id, window_size, window_start DESC);

-- =============================================================================
-- METRIC_BASELINE
-- =============================================================================

CREATE TABLE IF NOT EXISTS metric_baseline (
    baseline_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID NOT NULL,
    entity_id             UUID NOT NULL,
    metric_id             UUID NOT NULL REFERENCES metric_catalogue(metric_id),
    mean_value            FLOAT,
    stddev_value          FLOAT,
    p5_value              FLOAT,
    p95_value             FLOAT,
    baseline_window_days  VARCHAR(20),
    sample_count          INT,
    computed_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_from            TIMESTAMPTZ NOT NULL,
    valid_to              TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_baseline_entity
    ON metric_baseline(entity_id, metric_id, valid_from DESC);

-- =============================================================================
-- ALERT CATALOGUE
-- =============================================================================

CREATE TABLE IF NOT EXISTS alert_catalogue (
    alert_type_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID NOT NULL,
    canonical_alert_name  VARCHAR(120) NOT NULL,
    alert_category        VARCHAR(60),
    default_severity      VARCHAR(20)
                            CHECK (default_severity IN ('CRITICAL','HIGH','MEDIUM','LOW')),
    entity_class_scope    VARCHAR(40),
    description           TEXT,
    is_active             BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS alert_source_mapping (
    mapping_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_type_id           UUID NOT NULL REFERENCES alert_catalogue(alert_type_id),
    source_id               UUID NOT NULL,
    source_alert_name       VARCHAR(200),
    source_severity_map     JSONB,
    source_entity_id_field  VARCHAR(120),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- ALERT_EVENT — hypertable
-- =============================================================================

CREATE TABLE IF NOT EXISTS alert_event (
    alert_id            UUID        NOT NULL DEFAULT gen_random_uuid(),
    tenant_id           UUID        NOT NULL,
    entity_id           UUID        NOT NULL,
    entity_class        VARCHAR(40),
    alert_type_id       UUID        REFERENCES alert_catalogue(alert_type_id),
    source_id           UUID        NOT NULL,
    canonical_severity  VARCHAR(20) NOT NULL
                          CHECK (canonical_severity IN ('CRITICAL','HIGH','MEDIUM','LOW')),
    source_severity     VARCHAR(40),
    metric_value        FLOAT,
    metric_id           UUID,
    source_alert_id     VARCHAR(200),
    event_ts            TIMESTAMPTZ NOT NULL,
    ingest_ts           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status              VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
                          CHECK (status IN ('ACTIVE','ACKNOWLEDGED','RESOLVED','SUPPRESSED')),
    incident_id         UUID
);

SELECT create_hypertable('alert_event', 'event_ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_alert_entity   ON alert_event(entity_id, event_ts DESC);
CREATE INDEX IF NOT EXISTS idx_alert_tenant   ON alert_event(tenant_id, event_ts DESC);
CREATE INDEX IF NOT EXISTS idx_alert_status   ON alert_event(status, event_ts DESC);
CREATE INDEX IF NOT EXISTS idx_alert_incident ON alert_event(incident_id)
    WHERE incident_id IS NOT NULL;

-- =============================================================================
-- GRAPH_MUTATION_LOG — hypertable
-- =============================================================================

CREATE TABLE IF NOT EXISTS graph_mutation_log (
    tenant_id         UUID        NOT NULL,
    mutation_id       UUID        NOT NULL DEFAULT gen_random_uuid(),
    operation_type    VARCHAR(30) NOT NULL
                        CHECK (operation_type IN ('CREATE_NODE','UPDATE_NODE','DELETE_NODE',
                               'CREATE_EDGE','UPDATE_EDGE','DELETE_EDGE')),
    entity_class      VARCHAR(40),
    entity_id         UUID,
    relationship_type VARCHAR(60),
    from_entity_id    UUID,
    to_entity_id      UUID,
    before_state      JSONB,
    after_state       JSONB,
    source_service    VARCHAR(120),
    kafka_topic       VARCHAR(200),
    occurred_at       TIMESTAMPTZ NOT NULL
);

SELECT create_hypertable('graph_mutation_log', 'occurred_at',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_gml_entity ON graph_mutation_log(entity_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_gml_tenant ON graph_mutation_log(tenant_id, occurred_at DESC);

-- =============================================================================
-- STALE_TELEMETRY_EVENT — hypertable
-- =============================================================================

CREATE TABLE IF NOT EXISTS stale_telemetry_event (
    event_id              UUID        NOT NULL DEFAULT gen_random_uuid(),
    tenant_id             UUID        NOT NULL,
    entity_id             UUID        NOT NULL,
    entity_class          VARCHAR(40),
    source_id             UUID        NOT NULL,
    silence_duration_s    INT,
    threshold_s           INT,
    status                VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
                            CHECK (status IN ('ACTIVE','RESOLVED')),
    stale_since           TIMESTAMPTZ NOT NULL,
    resolved_at           TIMESTAMPTZ
);

SELECT create_hypertable('stale_telemetry_event', 'stale_since',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE);

-- =============================================================================
-- LOG_EVENT — hypertable (FR-TL-03 ELK/OpenSearch ingestion)
-- =============================================================================

CREATE TABLE IF NOT EXISTS log_event (
    log_id            UUID        NOT NULL DEFAULT gen_random_uuid(),
    tenant_id         UUID        NOT NULL,
    entity_id         UUID,
    entity_class      VARCHAR(40),
    source_id         UUID        NOT NULL,
    log_level         VARCHAR(20) NOT NULL
                        CHECK (log_level IN ('DEBUG','INFO','WARN','ERROR','CRITICAL')),
    log_source        VARCHAR(120),
    message           TEXT        NOT NULL,
    structured_fields JSONB,
    raw_payload_ref   VARCHAR(500),
    event_ts          TIMESTAMPTZ NOT NULL,
    ingest_ts         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    quality_flag      VARCHAR(20) NOT NULL DEFAULT 'VALID'
                        CHECK (quality_flag IN ('VALID','PARTIAL','UNRESOLVED_ENTITY','LATE'))
);

SELECT create_hypertable('log_event', 'event_ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_log_entity ON log_event(entity_id, event_ts DESC);
CREATE INDEX IF NOT EXISTS idx_log_level  ON log_event(log_level, event_ts DESC);
CREATE INDEX IF NOT EXISTS idx_log_tenant ON log_event(tenant_id, event_ts DESC);
