# Triphony Phase 3 report

Phase 3 provider adapters and offline verification are implemented. The Phase 1/2 vertical slice remains the local default, and no live paid provider request was made.

## Files changed

Phase 3 implementation and contract changes:

- `services/worker/requirements.txt`: pinned official `google-genai==2.25.0` and `elevenlabs==2.68.0` dependencies.
- `services/api/requirements.txt`: aligned Pydantic with the current Google SDK requirement.
- `services/api/src/api/settings.py`, `.env.example`, `services/api/.env.example`, `docker-compose.yml`: validated provider configuration, fake default, model/timeout/limit settings, and safe placeholders.
- `services/worker/src/providers/`: configuration, lazy SDK factories, error normalization, Gemini Narrative Director, Gemini QA, Veo Visual Agent, ElevenLabs Audio Agent, provider factory, and readiness command.
- `services/api/tests/test_phase3_providers.py`: deterministic SDK-boundary tests for Gemini, Veo, ElevenLabs, factory, configuration, and redaction behavior.
- `services/api/tests/test_mock_pipeline.py`, `services/api/pytest.ini`: updated the real-mode assertion and made the async fixture scope explicit.
- `src/triphony_lib/contracts.py`, `src/triphony_lib/pipeline.py`: fake-mode default and compatibility with the existing `mock` alias.
- `README.md`, `docs/architecture.md`, `AGENTS.md`: provider boundaries, credentials, verification limits, and Phase 3/Phase 4 delivery gates.

The working tree already contained the Phase 1/2 changes and other user-owned modifications; they were preserved.

## Provider adapters

- Gemini narrative planning requests structured JSON and validates `ScenePlan`, timing, scene identity, and output specifications.
- Veo submits an asynchronous operation, preserves its external operation ID in `ProviderJob.provider_job_id`, polls with a finite deadline, maps pending/succeeded/failed/cancelled states, and returns a validated `gs://` output URI.
- Gemini QA validates structured `QAEvaluation` output, asset identity, shot references, findings, score, and recommendation.
- ElevenLabs keeps narration, music, ambience, and sound effects as separate logical asset versions and validates non-empty binary audio, content type, size, and configured duration metadata.

Provider SDK objects and provider exceptions do not enter `src/triphony_lib/`. Client creation is lazy, fake mode has no SDK client creation or network path, and real mode fails closed on incomplete configuration.

## Configuration contract

`PROVIDER_MODE=fake` is the default. `mock` is accepted as a compatibility alias. Real mode requires Vertex project/location, Vertex mode, Veo output `gs://` URI, ElevenLabs API key, and ElevenLabs voice ID. Vertex authentication uses Google Application Default Credentials and IAM; ElevenLabs credentials are backend-worker configuration only.

The readiness command is:

```bash
PYTHONPATH="$(pwd)/services/api/src:$(pwd)/services/worker/src:$(pwd)/src" python -m providers.readiness
```

It reports presence and capability configuration without secret values and explicitly reports that live verification has not been executed.

## Tests and exact results

- `python3 -m compileall -q services/worker/src/providers services/api/tests/test_phase3_providers.py src/triphony_lib`: passed.
- `docker compose -p triphony-codex-20260927 build migrate api worker`: passed.
- Focused Phase 3 suite: `16 passed`.
- Full backend suite: `32 passed, 2 warnings`.
- `npm run typecheck`: passed.
- `npm run build`: passed.
- `npm audit --audit-level=high`: `found 0 vulnerabilities`.
- `docker compose -p triphony-codex-20260927 config -q`: passed.
- Alembic upgrade, downgrade one revision, upgrade, and `alembic check`: passed; no new migration was required for Phase 3.
- Isolated Compose stack: PostgreSQL, Redis, API, worker, and web all healthy in fake mode.
- `npm run test:e2e`: Phase 1 browser acceptance passed.
- Service-restart persistence check: passed.
- `git diff --check`: passed.
- Credential-value scan: no real provider credentials found.

The remaining two pytest warnings are upstream deprecations: Starlette's deprecated `anyio.BlockingPortal` alias and Python's deprecated `crypt` module used by Passlib. The previously observed unset `pytest-asyncio` fixture-scope warning was fixed in `pytest.ini`; read-only mounted test-cache warnings were avoided with `-p no:cacheprovider` during container verification.

## Security and verification limitations

No provider key, ADC credential, signed URL, raw provider response, or binary media is persisted or exposed by the new adapters. No frontend provider secret path was added. The adapters are implemented and tested against deterministic injected client substitutes, but provider connectivity, permissions, quota, live media quality, and cost have not been verified.

Phase 4 remains: narrative-first orchestration, persisted state transitions, QA decisioning, selective retry, and deterministic FFmpeg assembly. Phase 5 remains: fallback policy, S3, observability, circuit breakers, and production security controls.

Official documentation consulted:

- Google Gen AI Python SDK: https://googleapis.github.io/python-genai/
- Vertex AI structured output: https://cloud.google.com/vertex-ai/generative-ai/docs/samples/generativeaionvertexai-gemini-controlled-generation-response-schema-2
- Vertex AI Veo generation: https://cloud.google.com/vertex-ai/generative-ai/docs/video/generate-videos-from-text
- ElevenLabs Python SDK: https://github.com/elevenlabs/elevenlabs-python
- ElevenLabs API overview: https://elevenlabs.io/docs/api-reference/introduction
- ElevenLabs music: https://elevenlabs.io/docs/api-reference/music/compose
- ElevenLabs sound effects: https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert

No paid provider calls occurred. Nothing was committed, pushed, or deployed.

PHASE 3 COMPLETE — provider implementation and offline verification passed; live paid smoke tests were intentionally not executed.

## Triphony Phase 4 report

Phase 4 is implemented and verified in deterministic fake mode. The existing Phase 1–3 changes and all other user-owned working-tree changes were preserved. No provider credentials were added, no paid provider call was made, and nothing was committed, pushed, or deployed.

### Durable workflow

- `services/worker/src/workflow/orchestrator.py` implements narrative-first planning, persisted workflow states, Celery group/chord fan-out, technical QA, agent QA through the Phase 3 factory, bounded selective regeneration, FFmpeg assembly, final QA, and recovery scheduling.
- `services/worker/src/workflow/media.py` implements path-safe FFmpeg/FFprobe execution, deterministic fake video/audio materialization, stream validation, temporary assembly, atomic publication, checksums, and reproducibility manifests.
- `services/api/src/api/models.py` and `services/api/alembic/versions/20260927_phase4_orchestration.py` persist workflow state/error/attempt data, asset-version parent/checksum/metadata lineage, and the Phase 4 indexes and constraints.
- Draft replacements remain draft through technical and agent QA. Final QA promotes the candidate set and supersedes the previous approved versions; failed final QA marks the attempted render failed and preserves the last accepted render.
- `services/api/src/api/routes.py` exposes workflow state/final-render metadata in the existing scene contract, keeps SSE authenticated and PostgreSQL-backed, and protects final-render delivery with scene ownership.
- `apps/web/src/lib/types.ts` and `apps/web/e2e/phase1.mjs` cover the final render contract, authenticated delivery, cross-user denial, refresh/library reopening, and media playback.

### Verification results

- Full backend suite: `35 passed, 2 warnings` using the isolated Compose worker image and `-p no:cacheprovider`.
- Phase 4 focused suite: `3 passed` with real FFmpeg/FFprobe media assembly, path traversal rejection, lineage, supersession, and idempotency coverage.
- Frontend `npm run typecheck`: passed.
- Frontend `npm run build`: passed.
- Full Playwright browser acceptance: passed, including final-render delivery, authenticated SSE, byte-range delivery, refresh/library persistence, cross-user scene/SSE/artifact/final-render denial, and logout.
- Service-restart persistence: passed; a completed scene retained the same final-render ID and remained deliverable after API/worker restart.
- Compose configuration validation: passed; isolated PostgreSQL, Redis, API, worker, and web services healthy in fake mode.
- Migration verification: `alembic check` passed; Phase 4 downgrade to `20260927phase2` and upgrade to head passed.
- `git diff --check`: passed.
- Precise credential-value scan: no real provider credential values found. The only `xi-api-key` matches are redaction tests and safe sanitizer constants.

Two remaining pytest warnings are documented upstream deprecations: Starlette's deprecated AnyIO `BlockingPortal` alias and Python's deprecated `crypt` module imported by Passlib. They are outside this Phase 4 scope and do not indicate workflow failures.

Official documentation consulted for Phase 4:

- Celery Canvas: https://docs.celeryq.dev/en/stable/userguide/canvas.html
- FFmpeg filters: https://ffmpeg.org/ffmpeg-filters.html
- FFmpeg concatenation guidance: https://www.ffmpeg.org/faq.html
- SQLAlchemy session transactions: https://docs.sqlalchemy.org/en/20/orm/session_basics.html
- SQLAlchemy `with_for_update`: https://docs.sqlalchemy.org/en/20/core/selectable.html

PHASE 4 COMPLETE — orchestration, QA, selective regeneration, assembly, and regression verification passed in deterministic fake mode.

## Triphony Phase 5 report

Phase 5 implementation is present and the focused controls suite passes offline. The work adds provider-neutral fallback, storage, resilience, security-governance, audit, and deployment-readiness boundaries while preserving fake mode as the default. No AWS resource was provisioned, no live provider or paid API call was made, and nothing was committed, pushed, or deployed.

### Implemented boundaries

- `services/worker/src/providers/runway.py` lazily uses the official Runway Python SDK and translates asynchronous task lifecycle results into the existing provider-neutral contracts. `fallback.py` applies active-passive policy, records fallback provenance, and refuses fallback for non-eligible failures.
- `src/triphony_lib/storage.py` defines local and S3 artifact stores with deterministic safe keys, atomic local publication, private S3 upload metadata, checksum verification, encryption configuration, and short-lived presigned delivery. API ownership checks precede delivery.
- `services/worker/src/resilience/` contains Redis circuit state and bounded retry policy. `workflow/outbox.py` and the Phase 5 migration provide transactional outbox, dead-letter, and replay records. Scene cancellation persists terminal intent and attempts best-effort task/provider cancellation.
- API governance adds CSRF/origin and trusted-host policy, body-size limits, safety rejection, Redis-backed quotas, correlation/audit data, redacted logging, and readiness checks. OpenTelemetry is optional and no-op by default.
- `docs/deployment-readiness.md` documents future secret ownership, IAM/workload identity, probes, scaling, migrations, backups, restore/rollback, storage migration, operator replay, and the authorized live-smoke sequence.

### Phase 4 closure corrections

The Phase 4 matrix was expanded to ten focused tests covering plan revision and dependent-asset invalidation after global narrative rejection, selective target mapping, approved-only selection, multi-shot ordering, missing/corrupt/timeout media, repeated assembly, and the no-synchronous-Celery-wait rule. The migration image now copies the complete Alembic versions directory rather than naming a single active revision. Both corrections are covered by focused verification.

### Offline verification

- Rebuilt all Compose images with the new dependencies; the migration image reports `20260927phase5` as head.
- `docker compose config --quiet`: passed.
- `git diff --check`: passed.
- Focused Phase 4 suite: `10 passed, 2 warnings`.
- Focused Phase 5 controls suite: `8 passed`.
- Full backend suite after Phase 5 code: `50 passed, 2 warnings`.
- Frontend typecheck, production build, and high-severity npm audit: passed before the final container rebuild; they require one final post-doc verification run if this report is used as a release gate.

The two pytest warnings are upstream deprecations: Starlette's AnyIO `BlockingPortal` alias and Python's deprecated `crypt` module imported by Passlib. They are documented rather than suppressed.

### Remaining gate

The application is not live-provider, AWS, or production-deployment verified. The real Runway/Veo/ElevenLabs path still requires an explicitly authorized smoke test, and the S3 path still requires an authorized AWS integration test. The deployment-readiness document is an operational checklist, not evidence of deployment. Until the final Compose startup, browser acceptance, and post-change frontend checks are rerun, the correct gate status is incomplete.

Official documentation consulted for Phase 5:

- Runway API and SDKs: https://docs.dev.runwayml.com/ and https://docs.dev.runwayml.com/api-details/sdks/
- Boto3 S3 uploads: https://docs.aws.amazon.com/boto3/latest/guide/s3-uploading-files.html
- S3 presigned URLs: https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html
- OpenTelemetry Python: https://opentelemetry.io/docs/languages/python/
- OWASP CSRF: https://owasp.org/www-community/attacks/csrf
