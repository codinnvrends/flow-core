# FlowCore Project Analysis

## Overview
FlowCore is a comprehensive Data Center Infrastructure Management (DCIM) and AIOps data pipeline. It features an end-to-end architecture tailored for persisting, querying, and analyzing rich synthetic data related to infrastructure entities (like data centers, racks, and devices). The system relies heavily on multiple purpose-built data stores to organize data based on its relational, topological, and time-series logic.

## Architecture & Data Stores
The project is built on the concept of **"Layers"**, defining data responsibilities across three major data stores:

1. **Layer 1: Topology & Graph (Neo4j)**
   - Responsible for tracking infrastructure topologies: tenants, sites, data centers, collections, and relationship graphs.
   - Models things like power chains (Device -> PDU -> Feed) and logical physical topologies (Site -> DC -> Rack).
   - Neo4j provides strong traversals (e.g., blast radius of a failed power feed).

2. **Layer 2 & Layer 4: Relational & AI Outcomes (PostgreSQL)**
   - Traditional metadata tracking and configuration storage.
   - Stores schema definitions, entity resolution rules, machine learning classifications, anomaly flags, and drift event logging.
   
3. **Layer 3: Time Series Data (TimescaleDB)**
   - Built on top of PostgreSQL, specialized for high-volume operational metrics.
   - Analyzes raw metric datapoints like CPU utilizations, temperatures, and power draw, rolling them up and logging alert history.

## Microservices Ecosystem (`/services`)
The backend is structured as a collection of Python-based microservices, typically utilizing the FastAPI framework with integration frameworks tailored for async database access (`asyncpg`, `neo4j` async driver).

Key Backend Services:
- **`graph-api`**: Exposes a GraphQL API (via Strawberry) and WebSocket subscriptions. It merges data from Neo4j (topology) and TimescaleDB (time-series) to serve rich UI queries like Rack Health Cards and Blast Radius analyses.
- **`telemetry-gateway` & `timeseries-writer`**: Handle ingestion of sensor and device logs directly into TimescaleDB.
- **`dcim-ingestion` & `topology-agent`**: Handle the translation of physical setups into Layer 1 and Layer 2 models.
- **`active-discovery`**: Finds newly provisioned network entities.
- **`classification-agent` & `insights-api`**: Consume and run AI models over Layer 2/4 data.

## Frontend (`/noc-frontend`)
The presentation layer is implemented as a React Single Page Application (SPA).
- **Core Technology**: React 18 / Vite 5 / TypeScript.
- **UI Framework**: Material-UI (MUI).
- **Data Querying**: Apollo Client (GraphQL hooks) coupled with WebSocket transport for live data feeds (`graphql-ws`).
- **Visualizations**: Incorporates heavily into Cytoscape for rendering topological maps / graphs, and D3.js for complex data-driven layouts.

## Synthetic Data Bootstrapping (`/generators`, `/scripts`)
The application natively bundles highly tailored data generators written in base Python 3.
- `generate_all.py` constructs large-scale realistic environments (e.g., specific tenant clouds, data clusters in specific regions).
- `run_all.sh` strings together code generation with multi-container Docker spins, inserting millions of time-series constraints automatically to provide an "instant on" demonstration of the platform's robustness.

## Conclusion
FlowCore is an advanced blueprint for creating realistic, full-stack observability layers mapped directly to the complexities of real-world physical and digital data center infrastructure. It balances multiple bespoke databases seamlessly behind unified GraphQL endpoints to simulate industrial resilience and performance monitoring networks.
