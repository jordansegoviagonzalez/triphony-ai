# Architecture (Portfolio Edition)

This repo is shaped like a real workflow product:

- **Next.js UI**: dashboard + editor UX (fast, responsive)
- **FastAPI API**: creates jobs, serves artifacts, streams status to the UI (SSE)
- **Celery worker**: runs long tasks (narrative/visual/soundtrack) without blocking HTTP
- **Postgres**: persistence (scenes + assets + versions)
- **Redis**: broker + results backend for Celery

## System Diagram

```mermaid
graph TD
    subgraph "Client Side"
        Browser[User / Browser]
        NextJS[Next.js UI / Auth]
    end

    subgraph "Control Plane (FastAPI)"
        API[API Service]
        DB[(PostgreSQL)]
    end

    subgraph "Message Bus"
        Redis[(Redis Queue)]
    end

    subgraph "Compute Plane (Worker)"
        Worker[Celery Worker]
        Lib[src/triphony_lib]
    end

    subgraph "Storage"
        FS[Artifact Storage]
    end

    %% Flows
    Browser -- "1. Login / Manage Account" --> NextJS
    NextJS -- "2. Create Scene (JWT)" --> API
    API -- "3. Persist State + User Context" --> DB
    API -- "4. Enqueue Job" --> Redis
    
    Redis -- "5. Consume Task" --> Worker
    Worker -- "6. Run Pipeline" --> Lib
    Lib -- "7. Generate" --> FS
    
    Worker -- "8. Update Status" --> DB
    
    API -- "9. Stream Updates (SSE)" --> NextJS
    NextJS -- "10. Fetch Artifacts" --> API
    API -- "11. Read File" --> FS

    classDef plane fill:#e1f5fe,stroke:#01579b,stroke-width:2px;
    classDef storage fill:#fff3e0,stroke:#ff6f00,stroke-width:2px;
    
    class API,Worker,Lib plane;
    class DB,Redis,FS storage;
```

## Workflow Sequence

```mermaid
sequenceDiagram
    participant U as User (UI)
    participant A as API
    participant D as Database
    participant R as Redis
    participant W as Worker (ML)
    
    U->>A: POST /api/v1/auth/login (Credentials)
    A-->>U: Return Auth Token (JWT)
    
    U->>A: POST /api/v1/scenes (Prompt + JWT)
    A->>D: Verify User + Create Scene + Assets (Pending)
    A->>R: Enqueue generate_asset (x3)
    A-->>U: Return scene_id
    
    par Async Processing
        loop SSE Stream
            U->>A: GET /api/v1/scenes/:id/events (JWT)
            A->>D: Poll Status
            A-->>U: scene.update (JSON)
        end
    and Worker Execution
        W->>R: Pop Task
        W->>W: Run triphony_lib.Pipeline
        W->>D: Update Asset (Running)
        W->>W: Inference (Mock/Real)
        W->>D: Update Asset (Done)
    end
```

## Workflow

1) User authenticates via Next.js and receives a JWT token.
2) UI calls `POST /api/v1/scenes` with a prompt and JWT.
3) API verifies user, writes `Scene` + placeholder `Asset` rows.
4) API enqueues 3 worker tasks (fan-out).
5) Worker generates mock artifacts and updates DB.
6) UI subscribes to `GET /api/v1/scenes/{id}/events` (SSE polling) and refreshes cards.

Mock mode is the default so reviewers can run this with **zero keys**.
