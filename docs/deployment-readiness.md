# Deployment readiness checklist

This document is a pre-deployment handoff for Triphony Phase 5. It is not an approval to provision AWS, call paid providers, or deploy. The verified local target is Docker Compose with `PROVIDER_MODE=fake` and local artifact storage.

## Runtime contract

Required services are `web`, `api`, `worker`, `migrate`, PostgreSQL, and Redis. Run migrations deliberately before dependent traffic:

```bash
docker compose --project-name triphony-codex-20260927 build
docker compose --project-name triphony-codex-20260927 run --rm migrate
docker compose --project-name triphony-codex-20260927 up -d
```

The API exposes `/health` for process health and `/ready` for database, Redis, storage, and provider-configuration readiness. The worker must use the same image, source revision, database URL, Redis URL, artifact root, and provider mode as the API. The migration image must contain the complete `services/api/alembic/versions/` directory; it must not rely on a hand-selected migration filename.

## Configuration and secret ownership

Keep non-secret defaults in `.env.example`. Inject secrets only at runtime through the deployment secret manager or workload identity:

- Google Vertex: project/location, ADC or workload identity, and a permitted Veo output bucket. Do not ship service-account JSON in images or source control.
- ElevenLabs: `ELEVENLABS_API_KEY` and voice configuration, owned by the worker task boundary.
- Runway: `RUNWAY_API_SECRET`, owned by the worker task boundary; fallback is disabled unless explicitly enabled.
- S3: bucket, region, prefix, encryption mode, and optional KMS key. Prefer task-role credentials from the AWS credential chain instead of static keys.
- Application authentication: a strong JWT secret and secure cookie settings. Real mode must not use the development secret or insecure cookies.

No provider secret may enter browser variables, database payloads, SSE data, logs, audit metadata, or signed URLs.

## AWS and IAM handoff

The future AWS deployment should use separate least-privilege roles for web/API, worker, and migration tasks. The worker role needs only the selected S3 object prefix and KMS permissions; the API role needs only presigned delivery or an authorized application stream; migration needs database connectivity and schema rights during the migration window. Confirm bucket block-public-access, encryption, lifecycle rules for temporary/failed artifacts, and CloudTrail/audit retention before enabling S3.

The application is intentionally not coupled to a local filesystem after S3 migration: call sites use `ArtifactStore`, and delivery remains ownership-gated. Before switching the default, perform a controlled copy, checksum comparison, read-after-write verification, rollback test, and cleanup policy review.

## Scaling and resilience

Scale web/API independently from workers. Keep at least one worker capable of FFmpeg CPU and temporary-disk demand for the configured media limits. Monitor queue age, task duration, retry/fallback counts, circuit state, dead-letter count, provider latency, QA rejection, render success, artifact size, and per-scene usage. Redis rate limits and circuit state require a shared durable Redis/Valkey service in a multi-instance deployment.

The outbox dispatcher must run as an operator-controlled or scheduled worker process. Monitor pending age and failed publish attempts. Dead-letter replay is an authenticated operator action through the CLI or deployment runbook, never an end-user HTTP endpoint. Cancellation is best-effort at the provider boundary and must leave a persisted terminal state.

## Migration, backup, and rollback

1. Take a PostgreSQL backup and record the application image revision.
2. Run `alembic check` and the forward migration in a maintenance or controlled startup step.
3. Verify `/ready`, worker startup, outbox dispatch, and a fake-mode-compatible smoke path.
4. Roll back application images only when the schema remains backward compatible. Use the Alembic downgrade only under an approved database recovery procedure after confirming data impact.
5. Preserve immutable asset versions and final renders during rollback; never overwrite the only artifact copy.

Backups must cover PostgreSQL and private artifacts, with restore drills that verify ownership rows, checksums, media decodability, and signed delivery. Redis state is operational state and must be recreated from configuration/database records where possible.

## Live smoke sequence before production claims

In a separately authorized environment, verify registration/login, CSRF and origin policy, prompt safety rejection, quota behavior, authenticated SSE, a provider plan, primary visual failure followed by policy-approved fallback, cancellation, retry/dead-letter handling, QA rejection and selective regeneration, S3 upload/head/presigned delivery, restart persistence, and final MP4 playback. Record provider request IDs, cost, latency, and artifact checksums without retaining secrets or raw private payloads.

This repository's Phase 5 verification is offline and fake-mode only. No cloud resources, live provider calls, or production deployment are claimed.
