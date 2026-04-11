"""
Canonical Kafka message schemas for all 5 FlowCore topics.
All timestamps are ISO-8601 strings. All IDs are UUID strings.
"""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime
import uuid


def new_uuid() -> str:
    return str(uuid.uuid4())


# ── dcim.config.normalized ───────────────────────────────────────────────────

class EntityAttribute(BaseModel):
    namespace: str
    key: str
    value: str
    value_type: str = "STRING"


class CapacitySpec(BaseModel):
    dimension: str          # power_kw | space_u | cooling_kw | bandwidth_gbps
    rated_value: float
    usable_value: Optional[float] = None
    unit: str


class EntityRelationship(BaseModel):
    relationship_type: str  # in_rack | powered_by | connected_to | runs | depends_on
    to_entity_id: str
    properties: dict[str, Any] = {}


class IdentitySignal(BaseModel):
    signal_type: str        # MAC_ADDRESS | SERIAL_NUMBER | IP_ADDRESS | HOSTNAME | SNMP_OID | ASSET_TAG | REDFISH_ID
    signal_value: str
    confidence: float = 1.0


class DcimNormalizedMessage(BaseModel):
    message_id: str = Field(default_factory=new_uuid)
    tenant_id: str
    source_id: str
    record_id: str = Field(default_factory=new_uuid)
    entity_class: str       # RACK | DEVICE | PDU | FEED | INTERFACE | SENSOR | SERVICE
    canonical_name: str
    canonical_type: Optional[str] = None
    operational_status: str = "UNKNOWN"
    criticality_level: Optional[str] = None
    redundancy_posture: Optional[str] = None
    location_id: Optional[str] = None
    dc_id: Optional[str] = None
    attributes: list[EntityAttribute] = []
    capacity_specs: list[CapacitySpec] = []
    relationships: list[EntityRelationship] = []
    identity_signals: list[IdentitySignal] = []
    event_ts: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    ingest_ts: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ── metrics.timeseries.raw ───────────────────────────────────────────────────

class MetricDatapointMessage(BaseModel):
    message_id: str = Field(default_factory=new_uuid)
    tenant_id: str
    entity_id: str
    entity_class: str
    metric_id: str
    source_id: str
    value: float
    quality_flag: str = "VALID"   # VALID | INTERPOLATED | SUSPECT | LATE | OUT_OF_RANGE
    event_ts: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    ingest_ts: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ── alerts.raw ───────────────────────────────────────────────────────────────

class AlertRawMessage(BaseModel):
    message_id: str = Field(default_factory=new_uuid)
    alert_id: str = Field(default_factory=new_uuid)
    tenant_id: str
    entity_id: str
    entity_class: str
    alert_type_id: str
    source_id: str
    canonical_severity: str   # CRITICAL | MAJOR | MINOR | WARNING | INFO
    source_severity: str
    metric_value: Optional[float] = None
    metric_id: Optional[str] = None
    source_alert_id: Optional[str] = None
    status: str = "ACTIVE"    # ACTIVE | RESOLVED
    event_ts: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    ingest_ts: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ── discovery.snmp.results ───────────────────────────────────────────────────

class SNMPInterfaceEntry(BaseModel):
    if_index: int
    if_descr: str
    if_type: int
    if_speed: int           # bits/sec
    if_oper_status: int     # 1=up, 2=down
    if_phys_address: Optional[str] = None


class DiscoverySnmpMessage(BaseModel):
    message_id: str = Field(default_factory=new_uuid)
    tenant_id: str
    source_id: str
    target_ip: str
    sys_oid: Optional[str] = None
    sys_descr: Optional[str] = None
    sys_name: Optional[str] = None
    sys_location: Optional[str] = None
    serial_number: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    ip_addresses: list[str] = []
    mac_addresses: list[str] = []
    if_table: list[SNMPInterfaceEntry] = []
    scan_ts: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    ingest_ts: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ── discovery.bmc.results ────────────────────────────────────────────────────

class DiscoveryBmcMessage(BaseModel):
    message_id: str = Field(default_factory=new_uuid)
    tenant_id: str
    source_id: str
    target_ip: str
    redfish_type: Optional[str] = None       # @odata.type
    chassis_type: Optional[str] = None       # Rack, Blade, Tower, etc.
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    firmware_version: Optional[str] = None
    power_state: Optional[str] = None
    health_state: Optional[str] = None
    processor_count: Optional[int] = None
    memory_gib: Optional[float] = None
    capabilities: dict[str, Any] = {}        # routing_enabled, poe_capable, redundant_psu, etc.
    scan_ts: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    ingest_ts: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ── graph.mutations (internal, published by graph-updater) ───────────────────

class GraphMutationMessage(BaseModel):
    message_id: str = Field(default_factory=new_uuid)
    tenant_id: str
    mutation_id: str = Field(default_factory=new_uuid)
    operation_type: str     # CREATE | UPDATE | DELETE | MERGE
    entity_class: str
    entity_id: str
    relationship_type: Optional[str] = None
    from_entity_id: Optional[str] = None
    to_entity_id: Optional[str] = None
    before_state: Optional[dict] = None
    after_state: Optional[dict] = None
    source_service: str = "graph-updater"
    kafka_topic: Optional[str] = None
    occurred_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ── drift.events (published by topology-agent) ───────────────────────────────

class DriftEventMessage(BaseModel):
    message_id: str = Field(default_factory=new_uuid)
    drift_id: str = Field(default_factory=new_uuid)
    tenant_id: str
    drift_type: str         # MISSING_IN_DCIM | MISSING_IN_REALITY | POSITION_MISMATCH | ATTRIBUTE_CONFLICT | CAPACITY_DISCREPANCY
    severity: str           # CRITICAL | MAJOR | MINOR
    affected_entity_id: str
    affected_entity_class: str
    source_a_id: str
    source_a_state: dict = {}
    source_b_id: str
    source_b_state: dict = {}
    conflict_field: Optional[str] = None
    description: str
    detection_confidence: float
    agent_version: str = "topology-reconciliation-agent@1.0.0"
    detected_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ── classification.results (published by classification-agent) ────────────────

class ClassificationResultMessage(BaseModel):
    message_id: str = Field(default_factory=new_uuid)
    result_id: str = Field(default_factory=new_uuid)
    tenant_id: str
    entity_id: str
    inferred_entity_type: str
    capability_flags: dict[str, Any] = {}
    confidence_score: float
    needs_review: bool = False
    evidence_signals: list[dict] = []
    mlflow_run_id: Optional[str] = None
    classified_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
