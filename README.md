# Triphony AI Art Studio 🎬
![Triphony Demo](docs/triphony-demo.gif)
![Triphony Demo](docs/Realistic_Video_Generation_Complete1.gif)

**An Event-Driven Generative AI Platform** designed to orchestrate multi-modal asset generation (Video, Audio, Narrative) from a single conceptual prompt.

This project demonstrates a production-grade architecture for handling long-running inference tasks. It decouples the user interface from the generation pipeline using an asynchronous worker pattern, ensuring a responsive experience even when orchestrating complex generative models.

## Architectural Highlights

*   **Asynchronous Task Orchestration:** Utilizes **Celery** and **Redis** to manage heavy inference workloads off the main thread, allowing the system to scale worker nodes independently of the API layer.
*   **Real-Time State Synchronization:** Implements **Server-Sent Events (SSE)** to stream granular progress updates and state changes to the frontend immediately as workers complete tasks.
*   **Provider-Agnostic Design:** The worker layer is designed with an adapter pattern, allowing easy swapping between mock generators (for zero-cost development) and real production APIs (Hugging Face, OpenAI, Stability AI) via configuration.
*   **Immutable Asset Versioning:** Generative iterations are version-controlled, preserving history and preventing data loss during creative exploration.

## Architecture

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

## System Components

```text
apps/web/                 Next.js dashboard (React + TypeScript)
                          - Studio UI (Home / Studio / Library)
                          - SSE consumption for live progress updates
                          - Responsive playback (image/audio) + editor actions

services/api/             FastAPI service (Python)
                          - REST API for scenes/assets (create, fetch, regenerate)
                          - SSE event stream for pipeline status
                          - Artifact serving (returns signed/served URLs)

services/worker/          Celery worker (Python)
                          - Consumes jobs from Redis
                          - Runs generation pipeline (mock or real providers)
                          - Writes artifacts + updates DB status

src/shared/               Shared library (Python)
                          - Celery app definition + task contracts
                          - Shared types/config helpers used by API + worker


## Quick Start (Local Development)

This guide assumes a standard macOS/Linux environment with Docker installed.

### 1. Infrastructure Setup
Spin up the persistence layer (PostgreSQL) and message broker (Redis):
```bash
docker compose up -d
```

### 2. Backend Services
Initialize the Python environment and install dependencies:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r services/api/requirements.txt services/worker/requirements.txt
```

**Terminal 1: API Service**
```bash
export PYTHONPATH="$(pwd)/services/api/src:$(pwd)/services/worker/src:$(pwd)/src"
uvicorn api.main:app --reload --port 8000
```

**Terminal 2: Worker Node**
```bash
export PYTHONPATH="$(pwd)/services/api/src:$(pwd)/services/worker/src:$(pwd)/src"
celery -A worker.tasks worker --loglevel=INFO
```

### 3. Frontend Application
Launch the Next.js dashboard:
```bash
cd apps/web
npm install
npm run dev
```

**Access Points:**
*   **Dashboard:** [http://localhost:3000](http://localhost:3000)
*   **API Documentation:** [http://localhost:8000/docs](http://localhost:8000/docs)

## Configuration & Providers

The system supports a `PROVIDER_MODE` configuration in `.env`:

*   `mock`: (Default) Generates high-fidelity placeholder assets locally. Ideal for UI development and integration testing without API costs.
*   `real`: Integrates with external inference APIs (currently configured for Hugging Face Video Inference).

## License
All rights reserved.