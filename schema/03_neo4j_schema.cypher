// =============================================================================
// FlowCore — Neo4j Schema: Constraints & Indexes
// Layer 1: Canonical Physical Registry
// Version: 1.1  |  Requires Neo4j 5.x Enterprise
// Run this BEFORE loading synthetic data with the Cypher loader.
// =============================================================================

// ── Node uniqueness constraints ───────────────────────────────────────────────

CREATE CONSTRAINT tenant_id_unique IF NOT EXISTS
    FOR (n:Tenant) REQUIRE n.tenant_id IS UNIQUE;

CREATE CONSTRAINT site_id_unique IF NOT EXISTS
    FOR (n:Site) REQUIRE n.site_id IS UNIQUE;

CREATE CONSTRAINT collection_agent_id_unique IF NOT EXISTS
    FOR (n:CollectionAgent) REQUIRE n.agent_id IS UNIQUE;

CREATE CONSTRAINT dc_id_unique IF NOT EXISTS
    FOR (n:DataCenter) REQUIRE n.dc_id IS UNIQUE;

CREATE CONSTRAINT location_id_unique IF NOT EXISTS
    FOR (n:Location) REQUIRE n.location_id IS UNIQUE;

CREATE CONSTRAINT entity_id_unique IF NOT EXISTS
    FOR (n:InfrastructureEntity) REQUIRE n.entity_id IS UNIQUE;

CREATE CONSTRAINT platform_config_id_unique IF NOT EXISTS
    FOR (n:PlatformConfig) REQUIRE n.config_id IS UNIQUE;

// ── Property existence constraints (key fields) ───────────────────────────────

CREATE CONSTRAINT tenant_slug_exists IF NOT EXISTS
    FOR (n:Tenant) REQUIRE n.slug IS NOT NULL;

CREATE CONSTRAINT entity_class_exists IF NOT EXISTS
    FOR (n:InfrastructureEntity) REQUIRE n.entity_class IS NOT NULL;

// ── Lookup indexes ────────────────────────────────────────────────────────────

CREATE INDEX tenant_slug_idx IF NOT EXISTS
    FOR (n:Tenant) ON (n.slug);

CREATE INDEX entity_class_idx IF NOT EXISTS
    FOR (n:InfrastructureEntity) ON (n.entity_class);

CREATE INDEX entity_tenant_idx IF NOT EXISTS
    FOR (n:InfrastructureEntity) ON (n.tenant_id);

CREATE INDEX entity_status_idx IF NOT EXISTS
    FOR (n:InfrastructureEntity) ON (n.operational_status);

CREATE INDEX entity_health_idx IF NOT EXISTS
    FOR (n:InfrastructureEntity) ON (n.health_score);

CREATE INDEX entity_criticality_idx IF NOT EXISTS
    FOR (n:InfrastructureEntity) ON (n.criticality_level);

CREATE INDEX location_type_idx IF NOT EXISTS
    FOR (n:Location) ON (n.location_type);

CREATE INDEX site_country_idx IF NOT EXISTS
    FOR (n:Site) ON (n.country_code);

// ── Full-text index for entity search ────────────────────────────────────────

CREATE FULLTEXT INDEX entity_name_fulltext IF NOT EXISTS
    FOR (n:InfrastructureEntity) ON EACH [n.canonical_name, n.canonical_type];

// =============================================================================
// Relationship type declarations (for schema documentation)
// Neo4j does not require explicit relationship type creation, but these
// comments serve as the authoritative relationship registry.
//
// (:Tenant)               -[:OWNS]->              (:Site)
// (:Tenant)               -[:OWNS]->              (:DataCenter)
// (:Tenant)               -[:PARTITIONS]->        (:InfrastructureEntity)
// (:Tenant)               -[:CONFIGURES]->        (:PlatformConfig)
// (:Site)                 -[:CONTAINS]->          (:DataCenter)
// (:Site)                 -[:DEPLOYS]->           (:CollectionAgent)
// (:DataCenter)           -[:ORGANISES]->         (:Location)
// (:Location)             -[:NESTS]->             (:Location)
// (:Location)             -[:CONTAINS]->          (:InfrastructureEntity)
// (:InfrastructureEntity) -[:IN_RACK]->           (:InfrastructureEntity)
// (:InfrastructureEntity) -[:POWERED_BY]->        (:InfrastructureEntity)
// (:InfrastructureEntity) -[:CONNECTED_TO]->      (:InfrastructureEntity)
// (:InfrastructureEntity) -[:RUNS]->              (:InfrastructureEntity)
// (:InfrastructureEntity) -[:DEPENDS_ON]->        (:InfrastructureEntity)
// (:InfrastructureEntity) -[:HAS_ATTRIBUTE]->     (:EntityAttribute)
// (:InfrastructureEntity) -[:HAS_CAPACITY]->      (:CapacitySpec)
// =============================================================================
