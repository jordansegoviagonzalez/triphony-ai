🔥 CODEX PROMPT

## Mission

First close the remaining Phase 4 verification gaps. Then implement and verify **Phase 5: Runway fallback, private S3 storage, security, resilience, observability, and deployment readiness**.

Phases 1–3 are accepted. The Phase 4 core works end to end, but its full acceptance matrix must be demonstrated before Phase 5 can be declared complete.

Repository:

`/Users/jordan/Projects/triphony-ai-art-studio`

## Mandatory preservation rules

Preserve every existing Phase 1–4 change.

Do not run:

- `git reset`
- `git clean`
- `git restore`
- `git checkout` against modified files
- `git stash`
- `git rebase`
- `git commit`
- `git push`

Do not deploy anything.

Do not create or modify AWS, Google Cloud, Azure, Cloudflare, Runway, ElevenLabs, or other external resources.

Do not make paid provider calls.

Do not delete existing Docker volumes or unrelated containers.

All automated tests must use deterministic injected provider and storage substitutes.

## Required preflight

Before editing:

1. Read `AGENTS.md` completely.
2. Read `codexmessage.md` completely.
3. Read `projectreportforjordan.md`.
4. Inspect the complete Git status and diff.
5. Confirm Docker availability.
6. Confirm the current migration head.
7. Run the current full backend suite.
8. Run the current Playwright acceptance flow.
9. Confirm the final fake-mode MP4 is generated and persisted.
10. Inspect the Phase 4 migration-specific Dockerfile addition.

Follow only official documentation:

- Runway API and official SDK
- AWS S3, IAM, STS, and Boto3
- OpenTelemetry
- OWASP
- Celery
- Redis
- PostgreSQL
- SQLAlchemy
- Alembic
- FastAPI and Starlette
- Python
- Docker
- FFmpeg
- Next.js and Playwright
- Google Vertex AI
- ElevenLabs

Do not use tutorials, blogs, forums, Stack Overflow, or generated examples as technical authority.

---

# Part 1 — Close the Phase 4 gate

The transcript reports only three dedicated Phase 4 tests. That is insufficient evidence for the complete required matrix.

Expand the Phase 4 tests before beginning Phase 5.

## Required workflow cases

Prove:

- Narrative planning happens before dependent generation.
- Visual and audio branches fan out only after plan approval.
- The join runs only after required branches finish.
- Duplicate orchestration requests do not duplicate work.
- Duplicate Celery delivery is idempotent.
- A task resumes from persisted state after interruption.
- Invalid workflow transitions are rejected.
- A terminal generation failure prevents assembly.
- No Celery task synchronously waits on another task.
- Final assembly runs only with approved versions.

## Required selective-regeneration cases

Inject deterministic failures and independently prove:

- One visual shot is regenerated while other shots remain unchanged.
- Narration-only rejection regenerates narration only.
- Music-only rejection regenerates music only.
- Ambience-only rejection regenerates ambience only.
- Sound-effect-only rejection regenerates the affected effect only.
- A rejected version remains stored.
- A replacement receives a new immutable version.
- A failed replacement never displaces the accepted version.
- Final assembly uses only accepted versions.
- Maximum regeneration attempts terminate the workflow.
- Global narrative rejection creates a new plan version and invalidates dependent assets.

## Required FFmpeg failure cases

Prove:

- Multiple visual shots are assembled in order.
- Narration, music, ambience, and effects are mixed.
- Missing input fails safely.
- Corrupt media fails safely.
- Path traversal is rejected.
- FFmpeg timeout fails safely.
- Identical repeated assembly is idempotent.
- A failed final QA result does not replace the accepted final render.
- The persisted media manifest matches ffprobe output.

## Required authorization cases

Prove a second user cannot access the first user’s:

- Scene plan
- Provider jobs
- Provider attempts
- QA results
- QA findings
- Asset-version history
- Final-render records
- Final-render artifacts
- SSE updates

Do not weaken existing ownership behavior to make tests pass.

## Correct the delivery gate

After the expanded Phase 4 suite passes, update `AGENTS.md` so **Phase 5** is the active delivery gate.

## Correct the migration build behavior

Inspect the Phase 4 migration-specific `COPY` line added to the API Dockerfile.

The Docker image must include all Alembic revisions through a generic, durable directory copy. It must not require a new Dockerfile line for every migration.

Determine why the existing Alembic directory copy omitted the uncommitted revision.

Correct the actual build-context or Dockerfile problem.

Verify with a no-cache build that:

- Every migration revision is present.
- Alembic identifies the expected head.
- A new empty PostgreSQL database upgrades to head.
- `alembic check` reports no pending operations.

Do not remove the workaround until the durable replacement is verified.

If any Phase 4 requirement remains failing, stop and report:

`PHASE 4 NOT COMPLETE — required verification remains incomplete.`

Only continue into Phase 5 after all Phase 4 closure tests pass.

---

# Part 2 — Phase 5 implementation

## Phase 5 objective

Implement:

1. Runway active-passive visual fallback
2. Provider-neutral artifact storage
3. Private Amazon S3 adapter
4. Secure artifact delivery
5. Distributed circuit breakers
6. Bounded retry policies
7. Durable outbox and recovery
8. Dead-letter handling
9. Job cancellation
10. Rate limits and quotas
11. Prompt and content safety gates
12. Audit logging
13. Structured observability
14. Production container and configuration readiness

This phase prepares the application for deployment. It does not deploy it.

---

# Runway fallback

Implement a Runway Visual Agent adapter behind the existing Phase 2 `VisualAgent` interface.

Use the official Runway API or official supported SDK.

Requirements:

- Lazy client construction
- Server-side secret handling
- Asynchronous task submission
- External task identifier persistence
- Status polling
- Success, failed, and cancelled state mapping
- Provider-neutral results
- Retryable and terminal error classification
- Resumability after worker restart
- Idempotency protection
- Sanitized readiness reporting
- No SDK objects crossing the provider boundary

Configuration must support values equivalent to:

- `RUNWAY_API_SECRET`
- Configurable model identifier
- Poll interval
- Poll deadline
- Request timeout
- Maximum output duration
- Fallback enabled flag

Never expose the Runway secret to:

- Frontend variables
- API responses
- SSE
- Logs
- PostgreSQL
- Artifact metadata

Do not make a real Runway request.

## Fallback policy

Implement an explicit active-passive policy:

- Veo remains primary.
- Runway is fallback.
- Fallback is capability-specific.
- Fallback occurs only for policy-approved failures.
- Every fallback decision is persisted and observable.
- The same internal job remains traceable across provider attempts.
- Provider attempts remain immutable.

Default fallback eligibility may include:

- Provider unavailable
- Retryable internal provider failure
- Provider timeout after bounded retries
- Open Veo circuit breaker

Do not automatically fallback for:

- Safety or moderation rejection
- Invalid user input
- Invalid provider configuration
- Authentication or authorization failure
- Unsupported capability
- Corrupt source input

Quota-based fallback must be an explicit configurable policy because it can change cost behavior.

---

# Distributed circuit breaker

Implement provider-and-capability circuit-breaker state shared across workers through Redis.

States:

- `closed`
- `open`
- `half_open`

Requirements:

- Configurable failure threshold
- Configurable rolling or bounded evaluation window
- Configurable open-state cooldown
- Bounded half-open probes
- Success closes the breaker
- Repeated failure reopens it
- Safety, validation, and user errors do not count as infrastructure failures
- State changes emit audit and observability events
- No in-memory-only breaker state

Test the breaker using injected time and deterministic Redis substitutes or an isolated Redis instance.

---

# Artifact storage abstraction

Create a provider-neutral `ArtifactStore` boundary.

Required implementations:

1. Local private artifact store
2. Amazon S3 private artifact store

The orchestration, QA, and assembly layers must depend on the abstraction—not directly on local paths or Boto3.

The existing local fake-mode flow must continue working.

## S3 adapter

Use Boto3 and the standard AWS credential provider chain.

Production AWS authentication must support IAM roles and temporary credentials. Do not require hardcoded AWS access keys.

Configuration must support values equivalent to:

- `ARTIFACT_STORAGE_BACKEND=local|s3`
- `AWS_REGION`
- S3 bucket name
- Optional key prefix
- Server-side encryption mode
- Optional KMS key identifier
- Presigned URL expiration
- Multipart threshold
- Maximum object size

Requirements:

- Private objects only
- No public ACLs
- S3 Block Public Access documented as mandatory
- Server-side encryption
- Deterministic application-controlled object keys
- Object keys must not contain raw prompts, email addresses, secrets, or uncontrolled filenames
- Content type
- Content length
- Checksum
- Asset/version metadata
- Safe multipart uploads
- Bounded timeouts
- Retry classification
- Idempotent upload behavior
- Head-object verification after upload
- No large media blobs in PostgreSQL

Do not create an S3 bucket.

Do not contact AWS during automated tests.

Use Boto3/botocore’s official test/stub boundary or injected clients.

## Secure downloads

Before producing artifact access:

1. Authenticate the user.
2. Verify ownership through PostgreSQL.
3. Resolve the authorized object key.
4. Generate a short-lived presigned GET URL or use the authenticated local-file route.
5. Return no bucket credentials.

Requirements:

- Configurable short expiration
- No permanent public URLs
- Byte-range playback remains supported
- Signed URLs are not persisted as asset identity
- Refreshing access creates a new signed URL
- Cross-user access remains denied
- Logs do not record full signed URLs
- SSE does not expose signed URLs unnecessarily

---

# Resilience

## Retry policy

Implement explicit retry policies by failure category.

Requirements:

- Bounded attempts
- Exponential backoff
- Jitter
- Honor provider `Retry-After` where available
- No retries for terminal errors
- No duplicate provider submission after a persisted external task ID
- Retry decisions persisted with reason
- Celery retry behavior coordinated with internal idempotency

## Transactional outbox

Prevent the database-write/message-publish gap.

Implement an outbox or an equally durable documented pattern:

- Scene/workflow state and outbox event committed in one transaction
- Dispatcher publishes undispatched events
- Successful publication is recorded
- Duplicate dispatch remains safe
- Failed dispatch is retried
- Stale undispatched events are observable
- Reconciliation can recover orphaned workflows

Do not hold a database transaction open while publishing to Redis.

## Dead-letter handling

Persist terminal background failures with:

- Scene/job identity
- Task type
- Sanitized failure code
- Attempt count
- First and last failure timestamps
- Correlation identifier
- Safe replay eligibility
- Resolution status

Provide a secure operator CLI or internal administrative command for inspection and controlled replay.

Do not expose replay publicly without an authorization model.

## Cancellation

Implement user-owned workflow cancellation.

Requirements:

- Ownership verification
- Idempotent cancellation
- Persisted cancelled state
- Prevent new downstream tasks
- Revoke queued Celery work where safe
- Request provider cancellation when officially supported
- Preserve completed artifacts and audit history
- Never convert completed work back to cancelled
- SSE reports cancellation truthfully

---

# Usage governance

Implement Redis-backed distributed controls:

- Per-user prompt submission rate limit
- Per-user concurrent workflow limit
- Configurable daily generation quota
- Maximum prompt length
- Maximum requested duration
- Maximum shot count
- Maximum regeneration count
- Maximum artifact size

Use atomic Redis operations or scripts where concurrency correctness requires them.

Return appropriate HTTP status codes and safe retry information.

Do not use process-local counters.

---

# Security hardening

Review the complete application using official framework and OWASP guidance.

Verify and implement as applicable:

- Secure HttpOnly cookies
- Environment-aware `Secure`
- Appropriate `SameSite`
- CSRF protection for cookie-authenticated state-changing endpoints
- Exact CORS allowlist
- Trusted-host protection
- Security response headers
- Request-body limits
- Prompt length and schema validation
- No stack traces in production responses
- Secret redaction
- Artifact ownership
- S3 key safety
- Provider-response sanitization
- SSRF protection
- Path traversal protection
- Dependency audit
- Database least-privilege documentation
- Redis authentication/TLS configuration support
- PostgreSQL TLS configuration support

Do not claim a penetration test was performed.

## Safety gate

Add a provider-neutral content-safety policy gate before paid generation.

Requirements:

- Structured allow/reject decision
- Sanitized reason category
- Audit record
- No raw sensitive prompt logging by default
- Fake implementation for deterministic testing
- Provider safety rejections remain terminal and do not trigger fallback

Do not invent unsupported claims about provider moderation.

---

# Audit logging

Add append-oriented audit events for security and workflow operations.

Include:

- Actor/user ID
- Event type
- Resource type and ID
- Timestamp
- Correlation ID
- Safe structured metadata
- Outcome

Audit at minimum:

- Login success/failure
- Scene submission
- Rate/quota rejection
- Workflow cancellation
- Provider fallback
- Circuit state change
- QA rejection
- Selective regeneration
- Final-render acceptance
- Artifact access authorization failure
- Dead-letter creation/replay

Do not store secrets, full signed URLs, authorization headers, or raw sensitive prompts.

---

# Observability

Implement vendor-neutral OpenTelemetry instrumentation.

Provide:

- Request correlation IDs
- Trace propagation from API to Celery tasks
- Scene/workflow/job identifiers on spans
- Provider submission and polling spans
- Storage-operation spans
- FFmpeg assembly spans
- QA spans
- Retry and fallback events
- Structured JSON logs
- Metrics for counts, failures, and latency

Track safe operational metrics such as:

- Workflow success/failure/cancellation count
- Workflow latency
- Queue latency
- Provider latency by provider/capability
- Retry count
- Fallback count
- Circuit state
- QA rejection count
- Regeneration count
- Assembly latency
- Artifact bytes
- Rate/quota rejections
- Outbox backlog
- Dead-letter count
- Raw provider usage units where available

Do not hardcode provider pricing as authoritative.

Telemetry export must be disabled or no-op by default.

No telemetry may be transmitted during automated testing.

Do not log prompt contents or credentials by default.

Add or preserve:

- Liveness endpoint
- Readiness endpoint
- Dependency readiness details without secrets

Readiness must distinguish:

- Process alive
- Database available
- Redis available
- Storage configured
- Provider configuration present
- Live provider verification not performed

---

# Deployment readiness

Prepare the application for deployment without deploying it.

Verify:

- Production Docker images run as non-root where practical.
- Images do not contain `.env` files or credentials.
- API uses a production command, not a development reloader.
- Web uses a production Next.js server/build.
- Celery concurrency and time limits are configurable.
- Health checks are present.
- Graceful shutdown works.
- Temporary FFmpeg paths are configurable and bounded.
- Services are stateless except through PostgreSQL, Redis, and artifact storage.
- Environment configuration fails closed.
- AWS credentials can come from an ECS task role.
- Google credentials can use Application Default Credentials and Workload Identity Federation configuration.
- Provider secrets can be injected by a secret manager.
- Local Compose remains a development/test environment.

Create or update deployment-readiness documentation covering:

- Required external services
- Required environment variables
- Secret ownership
- Health probes
- Resource sizing assumptions
- Scaling boundaries
- Migration command
- Worker startup
- Storage migration considerations
- Backup and recovery expectations
- Controlled live-smoke-test sequence
- Rollback strategy

Do not create:

- Terraform
- CloudFormation
- ECS services
- RDS
- ElastiCache
- S3 buckets
- IAM roles
- CloudWatch resources
- GitHub Actions deployment
- A staging deployment

Those require separate deployment authorization.

---

# Required tests

## Phase 4 closure tests

All cases from Part 1 must pass.

## Runway/fallback tests

Test:

- Submission and polling
- Success/failure/cancellation
- Retryable versus terminal mapping
- Veo primary success without fallback
- Eligible Veo failure triggers Runway
- Safety rejection never triggers fallback
- Authentication failure never triggers fallback
- Open circuit routes according to policy
- Fallback attempt lineage
- Duplicate fallback prevention
- No network calls

## Storage tests

Test:

- Local storage compatibility
- S3 upload request construction
- Encryption settings
- Safe object keys
- Checksum verification
- Head-object validation
- Presigned URL creation
- Expiration bounds
- Ownership before signing
- Cross-user denial
- Range-playback compatibility
- S3 error normalization
- No AWS network calls

## Resilience tests

Test:

- Retry backoff and jitter with injected time
- Retry-After handling
- Maximum attempts
- Transactional outbox creation
- Duplicate outbox dispatch
- Broker publication failure and later recovery
- Orphaned workflow reconciliation
- Dead-letter creation
- Controlled replay
- Cancellation before generation
- Cancellation during generation
- Repeated cancellation
- Completed-work cancellation rejection
- Circuit-breaker transitions

## Security tests

Test:

- CSRF rejection
- Allowed CSRF request
- CORS behavior
- Secure-cookie configuration
- Rate limiting
- Daily quota
- Concurrent-job quota
- Oversized prompt
- Excess duration
- Excess shot count
- Artifact ownership
- Signed URL leakage prevention
- Secret/log redaction
- Production error sanitization

## Observability tests

Test:

- Correlation ID creation and propagation
- Structured log fields
- Sensitive field redaction
- Required spans
- Required metric increments
- No exporter/network in tests
- Health/readiness distinction

## Full regression

Rerun:

- Complete backend suite
- Phase 2 domain tests
- Phase 3 provider tests
- Expanded Phase 4 tests
- Phase 5 tests
- Frontend typecheck
- Frontend production build
- Frontend audit
- Docker Compose validation
- No-cache Docker image build
- Full Compose startup
- Empty PostgreSQL migration to head
- Safe downgrade/upgrade
- `alembic check`
- Full Playwright workflow
- Final MP4 playback
- Cross-user authorization
- Media byte ranges
- Service-restart persistence
- Cancellation browser flow if exposed in UI
- `git diff --check`
- Credential scan

Identify and either fix or precisely document the two remaining pytest warnings.

Do not delete or weaken tests to obtain passing results.

---

# Documentation and report

Update:

- `AGENTS.md`
- `README.md`
- `docs/architecture.md`
- Deployment-readiness documentation
- `.env.example`
- `projectreportforjordan.md`

Document:

- Phase 4 closure evidence
- Runway fallback policy
- S3 security model
- Storage abstraction
- Circuit-breaker model
- Retry rules
- Outbox
- Dead-letter handling
- Cancellation
- Rate limits and quotas
- Safety gate
- Audit logging
- Trace and metric model
- Production runtime requirements
- Official references consulted
- Live verification limitations

Product claims must remain accurate:

- Real provider adapters exist.
- Automated tests use deterministic substitutes.
- Live paid-provider smoke tests have not run.
- AWS infrastructure has not been provisioned.
- The system is deployment-prepared—not deployed or production-proven.

---

# Completion gate

Phase 5 is complete only when:

- The expanded Phase 4 acceptance matrix passes.
- Runway fallback is implemented and policy-controlled.
- S3 storage is private and ownership-gated.
- Circuit breakers are distributed.
- Retries are bounded and idempotent.
- Outbox recovery works.
- Dead-letter handling works.
- Cancellation works.
- Rate limits and quotas work.
- Security controls pass.
- Audit records are produced.
- Observability is implemented without data leakage.
- Production containers and configuration are deployment-ready.
- All Phase 1–5 regression tests pass.
- No real provider or AWS calls occur.
- Nothing is committed, pushed, or deployed.

End with exactly one honest status:

`PHASE 5 COMPLETE — Phase 4 closure and Phase 5 security, resilience, storage, fallback, observability, and deployment-readiness verification passed without external deployment or paid-provider calls.`

or

`PHASE 5 NOT COMPLETE — implementation or required verification remains incomplete.`

Do not commit or push after Phase 5. Stop and provide the report. The lead engineer will review the complete result and separately authorize the final commit and push.