-- =============================================================================
-- FlowCore — PostgreSQL Schema
-- Layer 2: Source Normalisation  |  Layer 4: Agent Outputs & Operations
-- Version: 1.1  |  Compatible with PostgreSQL 15+
-- =============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================================================
-- LAYER 1 REFERENCE — Tenant / Site / DC / Location / Entity IDs
-- These tables are authoritative in Neo4j; PostgreSQL holds lightweight
-- reference copies for FK integrity in Layer 2 and Layer 4 queries.
-- =============================================================================

CREATE TABLE IF NOT EXISTS tenant (
    tenant_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name              VARCHAR(120) NOT NULL,
    slug              VARCHAR(60)  NOT NULL UNIQUE,
    plan_tier         VARCHAR(30)  NOT NULL CHECK (plan_tier IN ('STARTER','PROFESSIONAL','ENTERPRISE')),
    neo4j_partition_key VARCHAR(80) NOT NULL UNIQUE,
    status            VARCHAR(20)  NOT NULL DEFAULT 'ACTIVE'
                        CHECK (status IN ('ACTIVE','SUSPENDED','TRIAL','OFFBOARDED')),
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS site (
    site_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES tenant(tenant_id),
    canonical_name    VARCHAR(200) NOT NULL,
    country_code      VARCHAR(2),
    city              VARCHAR(80),
    timezone          VARCHAR(50),
    status            VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS data_center (
    dc_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id           UUID NOT NULL REFERENCES site(site_id),
    tenant_id         UUID NOT NULL REFERENCES tenant(tenant_id),
    canonical_name    VARCHAR(200) NOT NULL,
    total_power_kw    FLOAT,
    floor_area_m2     FLOAT,
    tier_classification VARCHAR(10),
    status            VARCHAR(20) NOT NULL DEFAULT 'OPERATIONAL',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS infrastructure_entity_ref (
    -- Lightweight reference copy; full node lives in Neo4j
    entity_id         UUID PRIMARY KEY,
    tenant_id         UUID NOT NULL REFERENCES tenant(tenant_id),
    entity_class      VARCHAR(40) NOT NULL,
    canonical_name    VARCHAR(200) NOT NULL,
    dc_id             UUID REFERENCES data_center(dc_id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- LAYER 1 — COLLECTION_AGENT  (operational registry per site)
-- =============================================================================

CREATE TABLE IF NOT EXISTS collection_agent (
    agent_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id           UUID NOT NULL REFERENCES site(site_id),
    tenant_id         UUID NOT NULL REFERENCES tenant(tenant_id),
    agent_name        VARCHAR(120) NOT NULL,
    agent_version     VARCHAR(40)  NOT NULL,
    deployment_mode   VARCHAR(30)  NOT NULL
                        CHECK (deployment_mode IN ('KUBERNETES_POD','BARE_METAL','VM')),
    status            VARCHAR(20)  NOT NULL DEFAULT 'ACTIVE'
                        CHECK (status IN ('ACTIVE','DEGRADED','OFFLINE','DECOMMISSIONED')),
    config_ref        VARCHAR(200),
    last_heartbeat_at TIMESTAMPTZ,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- LAYER 1 — PLATFORM_CONFIG  (configurable operational thresholds)
-- =============================================================================

CREATE TABLE IF NOT EXISTS platform_config (
    config_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES tenant(tenant_id),
    config_scope      VARCHAR(60)  NOT NULL,
    config_key        VARCHAR(120) NOT NULL,
    config_value      VARCHAR(500) NOT NULL,
    value_type        VARCHAR(20)  NOT NULL DEFAULT 'STRING'
                        CHECK (value_type IN ('INTEGER','FLOAT','BOOLEAN','STRING','JSON')),
    description       TEXT,
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, config_scope, config_key)
);

-- =============================================================================
-- LAYER 2 — SOURCE NORMALISATION
-- =============================================================================

CREATE TABLE IF NOT EXISTS source_system (
    source_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES tenant(tenant_id),
    source_name       VARCHAR(120) NOT NULL,
    source_class      VARCHAR(30)  NOT NULL
                        CHECK (source_class IN ('DCIM','TELEMETRY','DISCOVERY','LOG','MANUAL')),
    vendor_name       VARCHAR(80),
    product_name      VARCHAR(80),
    product_version   VARCHAR(40),
    connection_type   VARCHAR(40)
                        CHECK (connection_type IN ('REST_API','MQTT','SNMP','WEBHOOK',
                                                    'CSV_IMPORT','KAFKA_TOPIC','GRPC')),
    connection_config JSONB,
    auth_type         VARCHAR(30)
                        CHECK (auth_type IN ('NONE','BASIC','BEARER','API_KEY',
                                             'OAUTH2','MTLS','SNMP_V2C','SNMP_V3')),
    status            VARCHAR(20)  NOT NULL DEFAULT 'ACTIVE'
                        CHECK (status IN ('ACTIVE','DEGRADED','PAUSED','ERROR','DECOMMISSIONED')),
    last_sync_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS source_record (
    record_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id             UUID NOT NULL REFERENCES source_system(source_id),
    tenant_id             UUID NOT NULL REFERENCES tenant(tenant_id),
    source_entity_type    VARCHAR(60),
    source_entity_id      VARCHAR(200),
    canonical_entity_id   UUID REFERENCES infrastructure_entity_ref(entity_id),
    raw_payload_ref       VARCHAR(500),
    schema_version        VARCHAR(20),
    ingest_mode           VARCHAR(30),
    event_ts              TIMESTAMPTZ,
    ingest_ts             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processing_status     VARCHAR(30) NOT NULL DEFAULT 'PENDING'
                            CHECK (processing_status IN ('PENDING','MAPPED','REJECTED','ARCHIVED')),
    rejection_reason      TEXT
);

CREATE INDEX IF NOT EXISTS idx_source_record_source ON source_record(source_id);
CREATE INDEX IF NOT EXISTS idx_source_record_tenant ON source_record(tenant_id);
CREATE INDEX IF NOT EXISTS idx_source_record_entity ON source_record(canonical_entity_id);
CREATE INDEX IF NOT EXISTS idx_source_record_ingest ON source_record(ingest_ts DESC);

CREATE TABLE IF NOT EXISTS field_mapping (
    mapping_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id             UUID NOT NULL REFERENCES source_system(source_id),
    source_entity_type    VARCHAR(60)  NOT NULL,
    source_field_path     VARCHAR(200) NOT NULL,
    canonical_target      VARCHAR(80)
                            CHECK (canonical_target IN ('ENTITY_FIELD','ENTITY_ATTRIBUTE',
                                   'IDENTITY_SIGNAL','CAPACITY_SPEC','RELATIONSHIP')),
    canonical_namespace   VARCHAR(80),
    canonical_key         VARCHAR(120),
    transform_type        VARCHAR(30)
                            CHECK (transform_type IN ('DIRECT','UNIT_CONVERT','ENUM_MAP',
                                   'EXPRESSION','CONSTANT','EXTRACT','PER_ROW')),
    transform_expression  TEXT,
    value_type            VARCHAR(20)
                            CHECK (value_type IN ('STRING','INTEGER','FLOAT',
                                   'BOOLEAN','JSON','TIMESTAMP')),
    is_identity_field     BOOLEAN NOT NULL DEFAULT FALSE,
    is_required           BOOLEAN NOT NULL DEFAULT FALSE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS identity_signal (
    signal_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id         UUID REFERENCES infrastructure_entity_ref(entity_id),
    source_id         UUID NOT NULL REFERENCES source_system(source_id),
    tenant_id         UUID NOT NULL REFERENCES tenant(tenant_id),
    source_record_id  UUID REFERENCES source_record(record_id),
    signal_type       VARCHAR(40) NOT NULL
                        CHECK (signal_type IN ('MAC_ADDRESS','SERIAL_NUMBER','IP_ADDRESS',
                               'HOSTNAME','SNMP_OID','RACK_USLOT','ASSET_TAG','REDFISH_ID')),
    signal_value      VARCHAR(200) NOT NULL,
    match_confidence  FLOAT CHECK (match_confidence BETWEEN 0 AND 1),
    resolution_status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
                        CHECK (resolution_status IN ('PENDING','RESOLVED','CONFLICT','UNRESOLVABLE')),
    observed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_identity_signal_entity  ON identity_signal(entity_id);
CREATE INDEX IF NOT EXISTS idx_identity_signal_type    ON identity_signal(signal_type, signal_value);
CREATE INDEX IF NOT EXISTS idx_identity_signal_tenant  ON identity_signal(tenant_id);

CREATE TABLE IF NOT EXISTS entity_resolution_rule (
    rule_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID NOT NULL REFERENCES tenant(tenant_id),
    rule_name             VARCHAR(120) NOT NULL,
    match_strategy        VARCHAR(40)
                            CHECK (match_strategy IN ('EXACT_SERIAL','MAC_ADDRESS','IP_ADDRESS',
                                   'HOSTNAME_FUZZY','RACK_USLOT_POSITION','OID_PREFIX','ASSET_TAG')),
    match_criteria        JSONB NOT NULL DEFAULT '{}',
    confidence_threshold  FLOAT NOT NULL DEFAULT 0.85,
    conflict_resolution   VARCHAR(30)
                            CHECK (conflict_resolution IN ('HIGHEST_CONFIDENCE','MANUAL_REVIEW',
                                   'NEWEST_SOURCE','DCIM_WINS')),
    priority              INT NOT NULL DEFAULT 10,
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sync_log (
    log_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id         UUID NOT NULL REFERENCES source_system(source_id),
    tenant_id         UUID NOT NULL REFERENCES tenant(tenant_id),
    sync_type         VARCHAR(30),
    sync_mode         VARCHAR(30),
    records_received  INT DEFAULT 0,
    records_mapped    INT DEFAULT 0,
    records_rejected  INT DEFAULT 0,
    entities_created  INT DEFAULT 0,
    entities_updated  INT DEFAULT 0,
    rejection_summary TEXT,
    duration_ms       FLOAT,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at      TIMESTAMPTZ,
    status            VARCHAR(20) NOT NULL DEFAULT 'RUNNING'
                        CHECK (status IN ('RUNNING','COMPLETED','PARTIAL','FAILED'))
);

CREATE INDEX IF NOT EXISTS idx_sync_log_source  ON sync_log(source_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sync_log_tenant  ON sync_log(tenant_id, started_at DESC);

CREATE TABLE IF NOT EXISTS dead_letter_record (
    record_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id         UUID NOT NULL REFERENCES source_system(source_id),
    tenant_id         UUID NOT NULL REFERENCES tenant(tenant_id),
    kafka_topic       VARCHAR(200),
    kafka_partition   INT,
    kafka_offset      BIGINT,
    rejection_stage   VARCHAR(60),
    rejection_reason  TEXT,
    raw_payload_ref   VARCHAR(500),
    received_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolution_status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
                        CHECK (resolution_status IN ('PENDING','REPLAYED','DISCARDED'))
);

CREATE TABLE IF NOT EXISTS kafka_topic (
    topic_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_name        VARCHAR(200) NOT NULL UNIQUE,
    producer_service  VARCHAR(120),
    consumer_services VARCHAR(500),
    content_class     VARCHAR(60),
    schema_version    VARCHAR(20),
    phase_introduced  VARCHAR(10),
    is_active         BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS discovery_scan_log (
    scan_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id             UUID NOT NULL REFERENCES source_system(source_id),
    tenant_id             UUID NOT NULL REFERENCES tenant(tenant_id),
    scan_type             VARCHAR(30) NOT NULL
                            CHECK (scan_type IN ('SNMP_WALK','BMC_REDFISH','BMC_IPMI')),
    target_range          VARCHAR(200) NOT NULL,
    hosts_targeted        INT DEFAULT 0,
    hosts_responded       INT DEFAULT 0,
    entities_discovered   INT DEFAULT 0,
    entities_created      INT DEFAULT 0,
    entities_updated      INT DEFAULT 0,
    rejection_summary     TEXT,
    duration_ms           FLOAT,
    started_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at          TIMESTAMPTZ,
    status                VARCHAR(20) NOT NULL DEFAULT 'RUNNING'
                            CHECK (status IN ('RUNNING','COMPLETED','PARTIAL','FAILED'))
);

-- =============================================================================
-- LAYER 4 — AGENT OUTPUTS & OPERATIONS
-- =============================================================================

CREATE TABLE IF NOT EXISTS "user" (
    user_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES tenant(tenant_id),
    email             VARCHAR(200) NOT NULL UNIQUE,
    display_name      VARCHAR(120) NOT NULL,
    rbac_role         VARCHAR(30)  NOT NULL
                        CHECK (rbac_role IN ('NOC_OPERATOR','CHANGE_MANAGER',
                               'DC_ADMIN','PLATFORM_ADMIN')),
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS drift_event (
    drift_id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID NOT NULL REFERENCES tenant(tenant_id),
    drift_type              VARCHAR(60) NOT NULL
                              CHECK (drift_type IN ('MISSING_IN_DCIM','MISSING_IN_REALITY',
                                     'POSITION_MISMATCH','POWER_PATH_MISMATCH',
                                     'ATTRIBUTE_CONFLICT','CAPACITY_DISCREPANCY')),
    severity                VARCHAR(20) NOT NULL
                              CHECK (severity IN ('CRITICAL','MAJOR','MINOR')),
    affected_entity_id      UUID REFERENCES infrastructure_entity_ref(entity_id),
    affected_entity_class   VARCHAR(40),
    source_a_id             UUID REFERENCES source_system(source_id),
    source_a_state          JSONB,
    source_b_id             UUID REFERENCES source_system(source_id),
    source_b_state          JSONB,
    conflict_field          VARCHAR(120),
    description             TEXT,
    detection_confidence    FLOAT CHECK (detection_confidence BETWEEN 0 AND 1),
    status                  VARCHAR(20) NOT NULL DEFAULT 'OPEN'
                              CHECK (status IN ('OPEN','ACCEPTED','DISMISSED','ESCALATED','RESOLVED')),
    agent_version           VARCHAR(40),
    itsm_ticket_ref         VARCHAR(120),
    detected_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at             TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_drift_event_tenant   ON drift_event(tenant_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_drift_event_status   ON drift_event(status);
CREATE INDEX IF NOT EXISTS idx_drift_event_entity   ON drift_event(affected_entity_id);

CREATE TABLE IF NOT EXISTS drift_suggestion (
    suggestion_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    drift_id              UUID NOT NULL REFERENCES drift_event(drift_id),
    tenant_id             UUID NOT NULL REFERENCES tenant(tenant_id),
    proposed_action       TEXT,
    proposed_namespace_ref VARCHAR(200),
    operator_decision     VARCHAR(30)
                            CHECK (operator_decision IN ('ACCEPTED','DISMISSED','ESCALATED')),
    decided_by            UUID REFERENCES "user"(user_id),
    decided_at            TIMESTAMPTZ,
    decision_notes        TEXT
);

CREATE TABLE IF NOT EXISTS classification_result (
    result_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id             UUID REFERENCES infrastructure_entity_ref(entity_id),
    tenant_id             UUID NOT NULL REFERENCES tenant(tenant_id),
    inferred_entity_type  VARCHAR(80) NOT NULL,
    capability_flags      JSONB,
    confidence_score      FLOAT CHECK (confidence_score BETWEEN 0 AND 1),
    needs_review          BOOLEAN NOT NULL DEFAULT FALSE,
    evidence_signals      JSONB,
    mlflow_run_id         VARCHAR(120),
    classified_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    operator_feedback     VARCHAR(80),
    feedback_by           UUID REFERENCES "user"(user_id),
    feedback_at           TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_classresult_tenant ON classification_result(tenant_id, classified_at DESC);
CREATE INDEX IF NOT EXISTS idx_classresult_review ON classification_result(needs_review) WHERE needs_review = TRUE;

CREATE TABLE IF NOT EXISTS correlated_incident (
    incident_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID NOT NULL REFERENCES tenant(tenant_id),
    root_cause_entity_id    UUID REFERENCES infrastructure_entity_ref(entity_id),
    root_cause_entity_class VARCHAR(40),
    root_cause_label        VARCHAR(200) NOT NULL,
    confidence_score        FLOAT CHECK (confidence_score BETWEEN 0 AND 1),
    evidence_entity_ids     JSONB,
    contributing_alert_ids  JSONB,
    affected_entity_count   INT NOT NULL DEFAULT 0,
    severity                VARCHAR(20) NOT NULL
                              CHECK (severity IN ('CRITICAL','HIGH','MEDIUM','LOW')),
    status                  VARCHAR(20) NOT NULL DEFAULT 'DETECTED'
                              CHECK (status IN ('DETECTED','INVESTIGATING',
                                     'MITIGATING','RESOLVED','FALSE_POSITIVE')),
    narrative               TEXT,
    mlflow_run_id           VARCHAR(120),
    first_event_at          TIMESTAMPTZ NOT NULL,
    detected_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at             TIMESTAMPTZ,
    operator_verdict        VARCHAR(40)
                              CHECK (operator_verdict IN ('CONFIRMED','FALSE_POSITIVE',
                                     'PARTIALLY_CORRECT','ROOT_CAUSE_WRONG')),
    is_false_positive       BOOLEAN DEFAULT FALSE,
    itsm_ticket_ref         VARCHAR(120),
    agent_version           VARCHAR(40)
);

CREATE INDEX IF NOT EXISTS idx_incident_tenant  ON correlated_incident(tenant_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_incident_status  ON correlated_incident(status);
CREATE INDEX IF NOT EXISTS idx_incident_fp      ON correlated_incident(is_false_positive, detected_at DESC);

CREATE TABLE IF NOT EXISTS capacity_forecast (
    forecast_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES tenant(tenant_id),
    entity_id         UUID REFERENCES infrastructure_entity_ref(entity_id),
    entity_class      VARCHAR(40),
    scope_level       VARCHAR(20)
                        CHECK (scope_level IN ('RACK','ROW','DATA_CENTER','SITE')),
    metric_id         UUID,  -- FK to metric_catalogue (TimescaleDB)
    generated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    horizon_ts        TIMESTAMPTZ NOT NULL,
    horizon_label     VARCHAR(20)
                        CHECK (horizon_label IN ('7d','30d','90d')),
    predicted_value   FLOAT NOT NULL,
    predicted_lower   FLOAT,
    predicted_upper   FLOAT,
    unit              VARCHAR(30) NOT NULL,
    exhaustion_flag   BOOLEAN NOT NULL DEFAULT FALSE,
    model_mape        FLOAT,
    mlflow_run_id     VARCHAR(120),
    agent_version     VARCHAR(40)
);

CREATE INDEX IF NOT EXISTS idx_forecast_tenant     ON capacity_forecast(tenant_id, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_forecast_exhaustion ON capacity_forecast(exhaustion_flag) WHERE exhaustion_flag = TRUE;
CREATE INDEX IF NOT EXISTS idx_forecast_entity     ON capacity_forecast(entity_id, horizon_label);

CREATE TABLE IF NOT EXISTS anomaly_flag (
    flag_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES tenant(tenant_id),
    entity_id         UUID REFERENCES infrastructure_entity_ref(entity_id),
    entity_class      VARCHAR(40),
    metric_id         UUID,
    observed_value    FLOAT,
    baseline_mean     FLOAT,
    deviation_sigma   FLOAT,
    severity          VARCHAR(20)
                        CHECK (severity IN ('CRITICAL','HIGH','MEDIUM','LOW')),
    mlflow_run_id     VARCHAR(120),
    flagged_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status            VARCHAR(20) NOT NULL DEFAULT 'OPEN'
                        CHECK (status IN ('OPEN','ACKNOWLEDGED','RESOLVED','FALSE_POSITIVE'))
);

CREATE INDEX IF NOT EXISTS idx_anomaly_tenant  ON anomaly_flag(tenant_id, flagged_at DESC);
CREATE INDEX IF NOT EXISTS idx_anomaly_entity  ON anomaly_flag(entity_id, flagged_at DESC);
CREATE INDEX IF NOT EXISTS idx_anomaly_status  ON anomaly_flag(status);

CREATE TABLE IF NOT EXISTS failure_probability (
    score_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID NOT NULL REFERENCES tenant(tenant_id),
    entity_id             UUID REFERENCES infrastructure_entity_ref(entity_id),
    entity_class          VARCHAR(40),
    probability_score     FLOAT CHECK (probability_score BETWEEN 0 AND 1),
    contributing_factors  JSONB,
    horizon_label         VARCHAR(20),
    mlflow_run_id         VARCHAR(120),
    agent_version         VARCHAR(40),
    computed_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_failure_prob_tenant ON failure_probability(tenant_id, computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_failure_prob_score  ON failure_probability(probability_score DESC);

CREATE TABLE IF NOT EXISTS simulation_scenario (
    scenario_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID NOT NULL REFERENCES tenant(tenant_id),
    name                  VARCHAR(200) NOT NULL,
    description           TEXT,
    target_entity_id      UUID REFERENCES infrastructure_entity_ref(entity_id),
    target_entity_class   VARCHAR(40),
    failure_mode          VARCHAR(60),
    change_type           VARCHAR(60),
    chained_steps         JSONB,
    created_by            UUID REFERENCES "user"(user_id),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status                VARCHAR(20) NOT NULL DEFAULT 'DRAFT'
                            CHECK (status IN ('DRAFT','RUNNING','COMPLETED','FAILED')),
    is_saved              BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS simulation_result (
    result_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id             UUID NOT NULL REFERENCES simulation_scenario(scenario_id),
    tenant_id               UUID NOT NULL REFERENCES tenant(tenant_id),
    affected_entity_count   INT DEFAULT 0,
    affected_entity_ids     JSONB,
    impact_severity_map     JSONB,
    redundancy_assessment   TEXT,
    estimated_degradation_pct FLOAT,
    graph_snapshot_ref      VARCHAR(500),
    execution_duration_ms   FLOAT,
    agent_version           VARCHAR(40),
    executed_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS node_quality_score (
    score_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES tenant(tenant_id),
    entity_id         UUID REFERENCES infrastructure_entity_ref(entity_id),
    entity_class      VARCHAR(40),
    completeness_score FLOAT CHECK (completeness_score BETWEEN 0 AND 1),
    freshness_score   FLOAT CHECK (freshness_score BETWEEN 0 AND 1),
    overall_score     FLOAT CHECK (overall_score BETWEEN 0 AND 1),
    missing_fields    JSONB,
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nqs_entity  ON node_quality_score(entity_id, computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_nqs_overall ON node_quality_score(overall_score);

CREATE TABLE IF NOT EXISTS itsm_integration_config (
    config_id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                 UUID NOT NULL REFERENCES tenant(tenant_id),
    target_system             VARCHAR(30) NOT NULL
                                CHECK (target_system IN ('SERVICENOW','JIRA',
                                       'GENERIC_CMDB','PAGERDUTY','OPSGENIE')),
    target_system_url         VARCHAR(500) NOT NULL,
    auth_type                 VARCHAR(30)
                                CHECK (auth_type IN ('BASIC','BEARER','API_KEY','OAUTH2')),
    auth_config               JSONB,
    trigger_event_type        VARCHAR(60)
                                CHECK (trigger_event_type IN ('DRIFT_EVENT',
                                       'CORRELATED_INCIDENT','BOTH')),
    payload_mapping_template  JSONB NOT NULL DEFAULT '{}',
    incident_type_map         JSONB,
    severity_map              JSONB,
    is_active                 BOOLEAN NOT NULL DEFAULT TRUE,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_log_entry (
    log_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenant(tenant_id),
    user_id         UUID REFERENCES "user"(user_id),
    action          VARCHAR(120) NOT NULL,
    resource_type   VARCHAR(60),
    resource_id     VARCHAR(200),
    ip_address      VARCHAR(45),
    change_payload  JSONB,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_immutable    BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_audit_tenant    ON audit_log_entry(tenant_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user      ON audit_log_entry(user_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_resource  ON audit_log_entry(resource_type, resource_id);

-- =============================================================================
-- Kafka topic registry seed (static reference data)
-- =============================================================================

INSERT INTO kafka_topic (topic_name, producer_service, consumer_services, content_class, schema_version, phase_introduced, is_active) VALUES
('dcim.config.raw',       'dcim-ingestion-service',         'event-archive-service',                                                                    'DCIM_RAW',          'v1', '1', TRUE),
('dcim.config.normalized','dcim-ingestion-service',         'graph-updater-service,topology-reconciliation-agent',                                       'DCIM_NORMALIZED',   'v1', '1', TRUE),
('metrics.timeseries.raw','telemetry-gateway-service',      'graph-updater-service,timeseries-writer-service',                                           'METRIC',            'v1', '1', TRUE),
('alerts.raw',            'telemetry-gateway-service',      'graph-updater-service,correlation-root-cause-agent',                                        'ALERT',             'v1', '1', TRUE),
('events.raw',            'telemetry-gateway-service',      'event-archive-service',                                                                     'EVENT',             'v1', '1', TRUE),
('discovery.snmp.results','active-discovery-service',       'graph-updater-service,topology-reconciliation-agent,classification-capability-agent',        'DISCOVERY_SNMP',    'v1', '1', TRUE),
('discovery.bmc.results', 'active-discovery-service',       'graph-updater-service,classification-capability-agent',                                     'DISCOVERY_BMC',     'v1', '1', TRUE),
('graph.mutations',       'graph-updater-service',          'topology-reconciliation-agent,event-archive-service',                                       'GRAPH_MUTATION',    'v1', '1', TRUE),
('drift.events',          'topology-reconciliation-agent',  'eventing-integration-service,insights-api-service',                                         'DRIFT',             'v1', '1', TRUE),
('drift.suggestions',     'topology-reconciliation-agent',  'insights-api-service',                                                                      'DRIFT_SUGGESTION',  'v1', '1', TRUE),
('classification.results','classification-capability-agent','graph-updater-service,insights-api-service',                                                'CLASSIFICATION',    'v1', '1', TRUE),
('incidents.correlated',  'correlation-root-cause-agent',   'eventing-integration-service,insights-api-service',                                         'INCIDENT',          'v1', '2', TRUE)
ON CONFLICT (topic_name) DO NOTHING;
