# Architecture Document

<!--
BEACON DESIGN phase deliverable. Update when a new ADR affects the architecture.
Always link to the relevant ADR rather than duplicating rationale here.
Use /design:diagram <component> to generate or regenerate any diagram below.
-->

## Overview

[High-level description of the system — what it does and how its major parts relate]

---

## C4 Context: System in its Environment

```mermaid
C4Context
    title System Context — comfyui_curu_auth
    Person(user, "Primary User", "Who uses this system and why")
    System(sys, "comfyui_curu_auth", "What this system does in one line")
    System_Ext(ado, "Azure DevOps", "Work items, pipelines, repositories")
    System_Ext(fabric, "Microsoft Fabric", "Semantic models, lakehouses")

    Rel(user, sys, "Uses", "HTTPS / CLI")
    Rel(sys, ado, "Reads/writes", "REST API")
    Rel(sys, fabric, "Queries", "REST API / DAX")
```

*What to update:* Replace external systems with the ones that actually apply. Remove
`ado`/`fabric` if not used. Add any third-party APIs, auth providers, or data sources.

---

## C4 Container: Deployable Units

```mermaid
C4Container
    title Container Diagram — comfyui_curu_auth
    Person(user, "User", "")

    System_Boundary(sys, "comfyui_curu_auth") {
        Container(app, "Application", "Python 3.12", "Core logic — update with actual container description")
        ContainerDb(db, "Storage", "TBD", "Persists state — update with actual technology")
    }

    Rel(user, app, "Uses")
    Rel(app, db, "Reads/writes")
```

*What to update:* Add containers as the architecture is decided. Link each container to
its ADR when a technology choice was made.

---

## System Components (logical view)

```mermaid
graph TB
    subgraph "comfyui_curu_auth"
        A[Component A] --> B[Component B]
        B --> C[Component C]
    end
    C --> D[(Storage)]
    C --> E[Azure DevOps]
    C --> F[Microsoft Fabric]
```

---

## Technology Stack

| Layer | Technology | Rationale | ADR |
|-------|-----------|-----------|-----|
| Language | Python 3.12 | — | — |
| Package manager | uv | Speed, lockfiles, workspace support | — |
| Linter/formatter | Ruff | Single tool, fast, replaces flake8+black+isort | — |
| Type checking | ty | Astral native type checker, replaces mypy | — |
| Azure integration | Azure CLI + MCP | See `.claude/settings.json` | — |

---

## Data Flow: Primary Path

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant CLI/API
    participant Service
    participant Storage

    User->>CLI/API: Request
    CLI/API->>Service: Process
    Service->>Storage: Persist
    Storage-->>Service: Confirm
    Service-->>CLI/API: Result
    CLI/API-->>User: Response
```

---

## Data Model (ERD)

```mermaid
erDiagram
    %% Replace with actual entities once the data model is defined
    ENTITY_A {
        uuid id PK
        string name
    }
    ENTITY_B {
        uuid id PK
        uuid entity_a_id FK
        string status
    }
    ENTITY_A ||--o{ ENTITY_B : "has"
```

---

## Deployment Topology

```mermaid
graph TB
    subgraph "Internet"
        User["👤 User"]
    end

    subgraph "Cloud — [Region TBD]"
        App["Application\n(Python 3.12)"]
        DB["Storage\n(TBD)"]
    end

    User -->|HTTPS| App
    App --> DB
```

*What to update:* Replace with actual cloud provider, region, and services once the
deployment architecture is decided (link to ADR).

---

## Interface Contracts

[API endpoints, CLI commands, or integration contracts that must remain stable once shipped]

---

## Non-Functional Requirements

- **Performance:** [targets — latency p99, throughput]
- **Security:** [requirements — auth, data sensitivity, never commit secrets, use `.env`]
- **Scalability:** [approach]
- **Observability:** [logging strategy, tracing, alerting]

---

## Tracer Bullet Decomposition

| Phase | Bullets | Outcome |
|-------|---------|---------|
| Foundation | 1–2 | Core plumbing proven end-to-end |
| Core logic | 3–5 | Business rules implemented |
| Integration | 6–7 | Azure DevOps + Fabric wired up |
| Production | 8+ | Deployment, observability, polish |

---

_Created:_ 2026-07-23
_Last updated:_ 2026-07-23 — BEACON SEED phase: project name stamped
_Status:_ Living document — update when ADRs change the architecture
