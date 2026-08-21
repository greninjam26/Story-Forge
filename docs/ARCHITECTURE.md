# Architecture

This document describes the intended architecture of Story Forge when the product is complete.

Story Forge turns a parent-provided daily event into an illustrated, narrated bedtime story that must be reviewed by the parent before a child can read it.

## System Overview

```text
Browser (Next.js 16 App Router)                    apps/web
  Parent onboarding, child profiles,
  story review, and child reader
                     |
                     | JSON over HTTPS
                     v
FastAPI backend                                    apps/api/app
  routers/          HTTP endpoints
  services/         story, safety, image, TTS, billing
  schemas.py        API request and response contracts
  models.py         persistent data models
  db.py             database sessions
  config.py         environment settings
                     |
                     v
Database           sqlite in development, Postgres in production
Asset storage      private child photos, generated images, and audio
External services  AI, image, TTS, authentication, and billing providers
```

Routers handle HTTP concerns and call services. Services contain product behavior and provider integrations. Models handle persistence, while schemas define validated API contracts.

## Authentication And Authorization

Parents authenticate with email and password. Passwords are hashed with
`passlib[bcrypt]` (bcrypt 4.0.1) and stored as `hashed_password` on the
`Parent` model. JWT bearer tokens are issued by `POST /auth/register` and
`POST /auth/login` using `python-jose[cryptography]` with HS256. The token
payload contains the parent ID and an expiration timestamp controlled by
`JWT_EXPIRE_MINUTES` (default 1440). Registration requires a password,
creates the parent, and returns a token for the web client.

Protected routes require an `Authorization: Bearer <token>` header. The
`get_current_parent` dependency decodes the token, loads the parent from the
database, and raises 401 if the token is missing, invalid, or the parent does
not exist. Ownership dependencies (`require_parent_owner`,
`require_child_owner`, `require_story_owner`) verify that the authenticated
parent owns the requested resource, raising 403 for cross-account access.

`GET /parents/{parent_id}` and all child and story routes are protected.
Reader and media routes remain public.

## Story Generation Flow

`POST /stories` starts the main workflow:

1. Authenticate the parent and load the child profile.
2. Check the parent's free-story or subscription limits.
3. Apply the local keyword safety policy to the submitted event.
4. Generate story text in the child's selected language.
5. Validate the generated title and pages against a schema.
6. Moderate the generated title and pages.
7. Generate an illustration and narration for each page.
8. Save the story as `pending_review`.
9. Allow the parent to approve, reject, or regenerate it.
10. Show only approved stories in the child reader.

Provider failures should produce a clear failed status and reason instead of leaving an incomplete story marked as successful.

When Claude, OpenAI moderation, FLUX, or ElevenLabs is selected,
`POST /stories` validates the request, persists an empty story with
`status=generating`, notifies an application-owned worker, and returns `201`
before provider work begins. The worker opens a fresh database session and
fills that same story record, preserving the ID returned to the parent.
Successful work
moves it to `pending_review`; an otherwise unhandled worker error retains the
claim so the stale window paces recovery. Deterministic stubs and local Ollama
keep the synchronous request path for local development and tests.
Claude credentials and ElevenLabs credentials plus paid-call approval are
validated before the story is queued, then checked again by the worker before
any provider call so configuration drift fails without incurring new charges.

An optional parent-scoped `Idempotency-Key` header makes retries safe: the
queue path records the key in the same transaction that persists the empty
`generating` story, so a duplicate request under that key replays the original
`201` response as a `200` with the same story ID and never notifies or charges
a second time. The synchronous stub path records the key after the story is
persisted and deletes its just-created story if a concurrent request won the
race, which is safe because stubs never incur paid work. Keys are scoped per
parent and unique under that scope, validated to be non-blank and at most 200
characters, and expired lazily after a configurable 24-hour TTL.

The story row itself is the durable generation queue:
`generation_claim_token` fences stale workers, `generation_claimed_at` records
claim age, `generation_attempts` counts claims, and `generation_stage` records
resumable pipeline progress. New and existing rows start at `story_text` with
no claim and zero attempts. The worker advances the stage to `illustrations`
after moderated text is persisted, to `narration` after every page has an
image, and to `complete` when the story is ready for review. The notification
carries the new story ID, which the worker claims
before provider work. The same API lifespan worker separately scans
oldest-first on startup and every configured interval, leaving fresh claims
alone and reclaiming claims older than 15 minutes. PostgreSQL workers use
`FOR UPDATE SKIP LOCKED`; SQLite
uses a conditional update. A claim increments the attempt count, and a stale
fifth attempt becomes `generation_failed` with a sanitized exhaustion reason.
Recovery handles one story at a time and checks queued IDs before taking the
next oldest recovery candidate. Its interval uses an absolute deadline, so
continuous new-story notifications cannot starve stale recovery.
An independent heartbeat session renews the lease while a provider operation
is in flight, and story-provider retries also verify ownership before each
attempt. The application owns the worker, so shutdown signals it before waiting
for its current provider call; no later stage starts after that call returns.
Successful and terminal work clears the claim in the same transaction that
stores the outcome; successful work advances the stage to `complete`.

Recovery resumes from the persisted stage: the worker persists moderated text
and stage progress, so a crash repeats only the provider work that had not
finished when it stopped. `story_text` restarts the pipeline, `illustrations`
generates only pages without an image, and `narration` generates only pages
without audio, avoiding repeat FLUX and ElevenLabs charges. Terminal failures
keep the already-persisted pages and the moderated title; each recovered
attempt starts a fresh generation run so only new provider calls are costed.
Request-level idempotency is implemented via the parent-scoped
`Idempotency-Key`. Transient provider errors (429, 5xx, network) are retried
with exponential backoff across story generation, illustration, narration, and
moderation; non-transient errors propagate immediately and rely on the worker
re-queue.

## Provider Pattern

External and paid capabilities sit behind environment-selected providers:

| Capability       | Selector                  |
| ---------------- | ------------------------- |
| Story generation | `STORY_PROVIDER`          |
| Illustration     | `IMAGE_GEN_PROVIDER`      |
| Text-to-speech   | `TTS_PROVIDER`            |
| Asset storage    | `STORAGE_PROVIDER`        |
| Safety moderation | `SAFETY_PROVIDER`         |
| Billing          | Billing provider settings |

Each capability defaults to a deterministic `stub` so the backend and tests
can run without live provider calls or paid keys. The rest of the application
calls one stable service interface and does not depend on a particular
provider.

Story text supports `stub`, `claude`, and `ollama`. Claude requires an explicit
`ANTHROPIC_API_KEY`; selecting it without a key fails configuration instead of
silently returning a stub story. Ollama uses its local HTTP API and requires no
paid credential. Both real providers share the same English/French, age-aware
prompt, Python validation, and one-retry policy.

Generated-story safety uses an English/French keyword prefilter for every
provider. With `SAFETY_PROVIDER=stub`, that deterministic policy is the complete
offline check. With `SAFETY_PROVIDER=openai`, the generated title followed by
all pages is sent in one OpenAI Moderation request after the prefilter passes.
The parent-provided event receives only the local keyword check and is never
sent to OpenAI Moderation. Provider errors and malformed responses fail closed
with a sanitized application error. When `APP_ENVIRONMENT=production`, startup
requires the OpenAI provider and a nonblank key before any background worker or
request handling begins.

The illustration stub returns a stable placeholder URL keyed by child and page.
Production illustration generation uses Black Forest Labs FLUX with the
child's private reference photo and a consistent watercolor storybook style.
FLUX requires `IMAGE_GEN_API_KEY`; story creation and regeneration fail before
provider work begins when the key or reference photo is missing. Accepted jobs
are polled asynchronously at the provider boundary, transient failures receive
one retry, and generated images are normalized to WebP before the configured
private asset storage receives them.

The narration stub creates a content-addressed URL from the page language and
text; `GET /media/placeholders/narration/{language}/{token}.wav` serves a short,
deterministic WAV tone so clients can exercise audio playback without a TTS
service. Parent page edits refresh the edited pages' narration references.
Provider failures are stored as sanitized generation failures instead of
leaving partially generated pages marked as ready for review.

Narration also supports ElevenLabs with the multilingual `eleven_v3` model.
Selecting it requires an API key, voice ID, and the separate
`PAID_TTS_ENABLED` operator approval; credentials and provider selection alone
cannot authorize a paid request. The child's story language is sent separately
as ElevenLabs' `language_code`. Each response records the provider-reported
`character-cost` before its MP3 is stored, so a later storage failure does not
erase a billed attempt. Local MP3 files remain behind the private narration
route; R2 MP3 files use stable private references and signed reads. Provider
failures expose sanitized application errors.

## Structured Story Output

Story generation returns structured data:

```text
{
  title: string,
  pages: string[]
}
```

The child's age determines page count and language complexity. Claude receives
the schema through a forced `submit_story` tool, while Ollama receives it in the
chat endpoint's structured `format` field. Provider output is validated again
in Python and retried once after malformed output or a provider failure. Final
errors expose only a sanitized failure category rather than prompts, child
content, raw responses, provider URLs, or credentials.

## Offline Story Evaluation

The evaluation harness is kept outside the production application package at
apps/api/evals/story_eval.py. It runs six fixed cases across ages 3, 6, and 10
in both English and French, and supports repeated runs with --runs.

From apps/api, the deterministic offline path is:

    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ./.venv/bin/python \
      -m evals.story_eval --provider stub --runs 1

The CLI also accepts --provider ollama, which is the default for local-model
evaluation. Paid Claude execution is intentionally unavailable through the
harness. Each run checks exact page count, requested-language evidence,
structural-label leakage, generated-story safety, and overall status. A
generation failure continues through later cases and reports only its
exception class. The command exits 0 only when every run passes every metric.

The language check follows the deterministic word-marker approach used by the
reference harness. It requires requested-language evidence across the story and
on at least half of its pages, and rejects multiple competing-language markers
within any page. It is not a general language detector. Automated tests always
inject deterministic or fake generators, and the harness's default generator
rejects providers other than `stub` and `ollama` before provider access.

## Languages

Story Forge supports English (`en`) by default and French (`fr`) as a second language.

UI locale and story language remain independent. A parent may use the English interface while generating a French story, or use the French interface while generating an English story.

## Data And Storage

```text
Parent --< Child --< Story --< StoryPage
  locale     language             language      page_number
  plan       name                 event_text    text
  hashed_password age              title         image_url
              interests            status        audio_url
              reference_photo_ref

Story 0..1 <-- GenerationRun --< GenerationCostEvent
                status          stage/provider/model
                known_cost      attempt/unit/rate/cost
                complete        outcome/cost_known

Story 1 -- 0..1 ModerationRecord
  safety_reason   provider/model/request ID
                  first flagged item/categories/scores
                  review status and timestamps

PendingAssetDeletion
  reference, attempts, next_attempt_at, terminal_at
```

Relational data lives in sqlite locally and Postgres in production. During
local development, stub media uses deterministic placeholder URLs. With
`STORAGE_PROVIDER=local`, private child reference photos and FLUX illustrations
use opaque `local://<category>/<uuid>.<suffix>` identifiers backed by
`ASSET_CACHE_DIR`. ElevenLabs MP3 files use random opaque identifiers under
`NARRATION_CACHE_DIR` and are served with private browser caching. Their own
`/media/narration/<uuid>.mp3` URLs are recognized as managed references so the
same lifecycle cleanup removes the underlying local files.

With `STORAGE_PROVIDER=r2`, normalized reference photos, FLUX illustrations,
and ElevenLabs MP3 files are written to a private Cloudflare R2 bucket. The
database stores stable `r2://<category>/<uuid>.<suffix>` references on `Child`
and `StoryPage`, never expiring URLs. Story response schemas resolve managed R2
page assets into signed GET URLs whose lifetime is controlled by
`R2_PRESIGN_TTL_SECONDS`. Provider code reads a child's private reference photo
through the same storage service without exposing its identifier in child
profile responses.

## Production Database Setup

Use Postgres 16 or later for production. The connection string uses the
`postgresql+psycopg` driver (psycopg3):

```
DATABASE_URL=postgresql+psycopg://user:password@host:5432/storyforge
```

Connection pooling is configured via environment variables and ignored for
SQLite. Defaults: `DB_POOL_SIZE=5`, `DB_MAX_OVERFLOW=10`,
`DB_POOL_TIMEOUT=30`, `DB_POOL_RECYCLE_SECONDS=1800`. Pool recycling
restarts idle connections before Postgres's `idle_in_transaction_session_timeout`
or cloud provider load balancers drop them.

Enable `pool_pre_ping=True` (always on for Postgres) so stale connections are
detected and re-established before use.

### SSL/TLS

Cloud-managed Postgres (AWS RDS, Supabase, Neon, Fly Postgres) enforces SSL by
default. When self-hosting, set `sslmode=verify-full` or `sslmode=require` in
the connection string. Never use `sslmode=disable` in production.

### Migrations

Run Alembic migrations before starting the API process:

```bash
alembic upgrade head
```

In containerized deployments, run this as an init step or entrypoint script
before the main `uvicorn` process. Migrations are designed to be idempotent
and safe to run multiple times.

### Backups

Cloud-managed Postgres provides automated backups (point-in-time recovery on
AWS RDS, daily snapshots on Supabase/Neon). For self-hosted Postgres:

```bash
pg_dump -Fc storyforge > storyforge_$(date +%Y%m%d).dump
pg_restore -d storyforge storyforge_20250101.dump
```

Store backups off-site and test restores regularly. The `stripe_events` and
`generation_cost_events` tables contain audit data that cannot be reconstructed
from other sources.

### Production Verification

Before first launch, verify these flows work end-to-end:

1. Register a parent, log in, receive a token
2. Create a child profile, upload a reference photo
3. Create a story (stub provider for smoke test, then real provider)
4. Review the story (approve, reject)
5. Access the story via child reader
6. Test billing checkout and webhook
7. Test account deletion
8. Verify rate limiting returns 429 under load
9. Check `/health` returns `{"status": "ok"}`
10. Confirm Sentry receives a test error

## Child Reference Photos

`PUT /parents/{parent_id}/children/{child_id}/reference-photo` uploads or
replaces one reference photo, and `DELETE` on the same path removes it. Both
routes require the child to belong to the parent identified by the route. The
stored identifier remains an internal field and is not returned by the child
profile schemas. FLUX reads it through the configured private storage provider.

Uploads are limited to 10 MB and accept static JPEG, PNG, or WebP images. The
image service applies EXIF orientation, constrains the longest dimension to
2048 pixels, rejects excessive source dimensions and animation, and writes a
metadata-free WebP file. Storage references use validated categories and
random UUID keys so callers cannot choose filesystem paths.

Replacement stores the new object before committing its database reference. A
failed commit removes the unpersisted object and retains the prior reference.
After a successful replacement, explicit removal, or child deletion, obsolete
managed references are committed to the durable deletion queue in the same
transaction as the owning data change. Regeneration, page editing, safety
rejection that discards pages, and failed partial media generation follow the
same ownership rule. A parent review rejection retains its pages and assets as
review history, so those assets remain owned until the story or child is
deleted.

## Asset Cleanup Operations

Queued deletions are attempted without undoing the user operation that made an
asset obsolete. The API runs a bounded cleanup pass in a background thread at
startup and every `ASSET_CLEANUP_WORKER_INTERVAL_SECONDS` when
`ASSET_CLEANUP_WORKER_ENABLED` is enabled. Failures record only their exception
type and retry with exponential backoff from one minute to 24 hours. After 12
failed attempts, a record becomes terminal and stops automatic retries.

From `apps/api`, operators can process every currently due deletion with:

```bash
PYTHONPATH=. ./.venv/bin/python scripts/cleanup_assets.py
```

`--limit` caps a manual pass. `--retry-terminal` clears the failure state of
terminal records before processing them again. The command prints deleted,
failed, pending, and terminal counts and exits nonzero whenever cleanup work
remains, making it suitable for monitoring and recovery procedures.

## Generation Cost Tracking

Every story creation, regeneration, or narration-producing edit starts a
`GenerationRun` before provider work begins. Provider calls append
`GenerationCostEvent` rows for story text, illustration, and narration, so
failed attempts and safety-rejected generations remain part of the cost record.
Successful and safety-rejected runs link to their resulting story; failed runs
remain storyless so they cannot replace a prior successful cost projection.
Story data, accumulated events, their run link, and the terminal run status are
committed together. FLUX is the exception because accepting a provider job can
incur a charge before polling finishes: its accepted cost event and current run
total are committed immediately, then the event outcome is updated after the
job succeeds or fails. A process interruption can therefore leave an
`in_progress` run with an accepted FLUX charge instead of losing that cost.

Known charges accumulate on the run, and `Story.cost_usd` mirrors the known
total of the latest successful or safety-rejected workflow affecting that
story. Missing usage or pricing marks the run incomplete instead of treating
an unknown charge as zero. The deterministic stub providers record their usage
at zero cost so local development and automated tests remain auditable and free.
Claude records input and output tokens for every returned attempt, including
malformed responses. Ollama records each local request at an explicit zero
rate. Failures without trustworthy usage remain unknown rather than being
reported as free.
ElevenLabs records billable character units from the `character-cost` response
header for successful and malformed responses. Missing or invalid usage remains
unknown. Its per-character rate is optional configuration; omitting it marks cost
reports incomplete instead of treating a paid request as free.

`STORY_COST_CEILING_USD` defaults to `0.25`. It is a runaway-cost alarm rather
than a circuit breaker: crossing the known-cost ceiling logs one warning and
flags the run, but generation continues. Unknown costs do not prove that the
ceiling was exceeded; the report exposes them as incomplete instead.

The operator report covers terminal runs created after the ledger was deployed;
historical `Story.cost_usd` values are not backfilled into cost events. From
`apps/api`, run:

```bash
PYTHONPATH=. ./.venv/bin/python scripts/cost_report.py --last 100
```

The CLI reports known spend, average cost per generation request, effective
cost per successful story, status and ceiling counts, active runs, and a
stage/provider/model breakdown. Totals and averages are labeled as lower bounds
when any selected run contains an unknown charge.

## Billing And Subscription

Stripe manages subscriptions. Webhooks are the source of truth for
subscription state — the browser redirect after Checkout proves nothing.

### Checkout

`POST /billing/checkout` creates a Stripe Checkout Session in
`mode="subscription"`. The parent is identified by `client_reference_id`
so the webhook can find them. When Stripe keys are not configured, a stub
mode subscribes the parent directly in development; in production, missing
keys return 503.

### Webhook Handling

`POST /billing/webhook` receives signed events from Stripe. Signature
verification uses the dedicated webhook secret (`whsec_...`), not the API
key. Every handler is idempotent: the `StripeEvent.id` primary key catches
redelivered events via `IntegrityError`, and they are acked without
re-running side effects.

Event routing:
- `checkout.session.completed` — subscribes the parent if payment is settled
- `checkout.session.async_payment_succeeded` — completes delayed bank-debit payments
- `customer.subscription.deleted` — unsubscribes the parent
- `customer.subscription.updated` — handles unpaid/paused status changes
- `invoice.payment_failed` — reports to observability but does not unsubscribe

Out-of-order delivery is handled by querying whether a later
`subscription.deleted` event already exists before honoring a checkout
completion.

### Free Story Limit

New story creation is gated by `FREE_STORIES_LIMIT` (default 5). Subscribed
parents bypass the limit. The counter increments only after a story is
successfully generated, not on creation attempts.

### Account Deletion

`DELETE /auth/me` cancels the Stripe subscription (best-effort), queues
child asset cleanup, and deletes the parent row. If the Stripe cancel call
fails, the failure is reported for manual operator action but deletion
proceeds — the legal right to delete is never blocked by a vendor.

## Privacy And Data Lifecycle

### Data Collection

| Data | Where stored | Purpose | Retention |
|------|-------------|---------|-----------|
| Parent email | `parents.email` | Account identification, login | Until account deletion |
| Parent password | `parents.hashed_password` | Authentication (bcrypt) | Until account deletion |
| Parent locale | `parents.locale` | Interface language preference | Until account deletion |
| Parent billing | `parents.stripe_*`, `free_stories_used`, `is_subscribed` | Subscription management | Until account deletion |
| Child name | `children.name` | Story personalization | Until account or child deletion |
| Child age | `children.age` | Page count and language complexity | Until account or child deletion |
| Child interests | `children.interests` | Story theme guidance | Until account or child deletion |
| Child language | `children.language` | Story language selection | Until account or child deletion |
| Reference photo ref | `children.reference_photo_ref` | Illustration style guidance | Until replaced or child deletion |
| Event text | `stories.event_text` | Story generation input | Until story or account deletion |
| Story title | `stories.title` | Generated story title | Until story or account deletion |
| Story pages | `story_pages.text` | Generated story text | Until story or account deletion |
| Illustrations | `story_pages.image_url` | Generated story images | Until story or account deletion |
| Narration | `story_pages.audio_url` | Generated story audio | Until story or account deletion |
| Safety reason | `stories.safety_reason` | Parent-facing rejection reason | Until story or account deletion |
| Moderation audit | `moderation_records.*` | Internal safety audit trail | Until story or account deletion |
| Generation runs | `generation_runs.*` | Cost tracking and pipeline state | Until story or account deletion |
| Cost events | `generation_cost_events.*` | Provider usage and billing audit | Until story or account deletion |
| Stripe events | `stripe_events.*` | Webhook idempotency and audit | Until parent deletion |
| Asset cleanup queue | `pending_asset_deletions.*` | Durable deletion retry | Until deletion succeeds or becomes terminal |

### Third-Party Data Sharing

| Provider | Data sent | Purpose |
|----------|-----------|---------|
| Anthropic (Claude) | Story prompt: child age, language, interests, page count, event text | Story text generation |
| OpenAI Moderation | Generated titles and pages (not event text) | Content safety screening |
| Black Forest Labs (FLUX) | Child reference photo, watercolor style prompt | Illustration generation |
| ElevenLabs | Page text, language code | Text-to-speech narration |
| Stripe | Parent email, subscription ID | Payment processing |
| Cloudflare R2 | Encrypted asset storage (reference photos, illustrations, audio) | Private object storage |
| Sentry | Identifiers only (story ID, run ID, provider name) — no PII, no child content | Error reporting |

### Sensitive Data Controls

**Never logged or reported to Sentry:**
- Child names, event text, story text, photos, audio
- API keys, passwords, JWT tokens, Stripe keys
- Raw provider request/response bodies
- Reference photo identifiers

**Never exposed via HTTP API:**
- `reference_photo_ref` — omitted from child profile responses
- `hashed_password` — never returned
- `flagged_text` — accessible only via database moderation CLI
- `safety_reason` and `event_text` — exposed only in parent-review story detail response
- Provider metadata — not returned in any API response

**Provider request discipline:**
- OpenAI Moderation receives only generated titles and pages, never the parent event
- FLUX receives only the child reference photo and style prompt, never event text
- ElevenLabs receives only page text and language code, never event text or photos
- Provider errors raise outside `except` blocks to prevent retaining request data as exception context

### Account Deletion

`DELETE /auth/me` triggers cascading deletion:
1. Cancel Stripe subscription (best-effort, failure reported for manual action)
2. Queue all child assets for cleanup (reference photos, illustrations, audio)
3. Delete parent row (cascades to children, stories, pages, moderation records, generation runs, cost events, Stripe events)

Asset cleanup uses exponential backoff (1 minute to 24 hours) across 12 retries. Terminal failures are logged for manual operator action.

### Data Export

A parent can request their data by contacting support. The API stores no data
that cannot be extracted from the database: profile information, stories, and
billing history are all queryable.

## Safety And Testing

Parent input is screened by the local English/French keyword policy. Generated
titles and pages pass through the same prefilter and then the configured
moderation provider. A provider failure cannot silently fall back to approval.

A generated-content rejection creates no story pages or media. The rejected
story, stable safety reason, cost-run result, and one private moderation record
are committed atomically. That record retains only the first flagged title or
page and its associated provider metadata. It cascades with the story and is
available only through the direct-database moderation review CLI; no HTTP API
returns flagged text, provider scores, or raw responses.

The parent-review story detail response exposes the original event and stable
safety reason for recovery, while create, list, update, approval, regeneration,
and child-reader responses omit those fields. Regeneration replaces an
unreviewed draft in place. A failed attempt preserves the draft, while an unsafe
replacement atomically rejects it, removes its pages, and queues obsolete media
for deletion. Rejected or flagged stories remain parent-visible only, and
parent approval is required before a story becomes child-facing.

Tests remain fast, offline, and deterministic. Pipeline tests use stub providers, real provider clients are mocked, and paid APIs are never called during tests.

## Observability

The app has three observability layers: health monitoring, rate limiting, and
error reporting. All three are disabled or no-op by default so local dev, CI,
and tests never require external services or make network calls.

### Health Monitoring

`GET /health` executes `SELECT 1` against the database and returns a component
status breakdown. A healthy response is `{"status": "ok", "components":
{"database": "ok"}}` with HTTP 200. When the database is unreachable the
endpoint returns `{"status": "degraded", "components":
{"database": "unreachable"}}` with HTTP 503, letting load balancers and
orchestrators detect a broken process that would otherwise appear healthy.

### Rate Limiting

An in-memory sliding-window rate limiter protects `POST /auth/register`,
`POST /auth/login`, and `POST /stories` from abuse. Each operation uses a
separate bucket keyed by the client address validated by the ASGI server; the
application never trusts raw forwarding headers. Over-limit requests receive
HTTP 429. The limiter is gated by `RATE_LIMIT_ENABLED` and defaults to off so
CI and local dev are unaffected. The window size and request cap are
configurable via environment variables.

### Error Reporting (Sentry)

`app/observability.py` provides `report()` and `report_message()` for
explicit error reporting of handled failures. It initializes the Sentry SDK
once at startup when `SENTRY_DSN` is set; without a DSN every function is a
pure no-op and the SDK is never imported.

Privacy controls strip login tokens from event URLs, query strings, Referer
headers, and breadcrumb messages before they leave the process. The SDK is
configured with `include_local_variables=False`, `max_request_body_size="never"`,
and `send_default_pii=False` so child names, event text, photos, and audio
never reach the third-party service. Log integration is configured with
`event_level=None` so `logger.error` calls do not mint Sentry issues; only
explicit `report()` / `report_message()` calls create events.

### Logging

Application logging uses Python's `logging.basicConfig()` with a structured
format (`%(asctime)s %(levelname)s %(name)s: %(message)s`). The root logger
is set to INFO. Sentry's logging integration captures INFO-and-up as
breadcrumbs for context without promoting log records to Sentry events.

## Deployment

### Environment Variables

**Required in production:**

| Variable | Value |
|----------|-------|
| `APP_ENVIRONMENT` | `production` |
| `DATABASE_URL` | `postgresql+psycopg://user:password@host:5432/storyforge` |
| `JWT_SECRET_KEY` | Random string, ≥32 characters |
| `WEB_ORIGIN` | `https://yourdomain.com` |
| `API_BASE_URL` | `https://api.yourdomain.com` |
| `TRUSTED_HOSTS` | `["api.yourdomain.com"]` |
| `SAFETY_PROVIDER` | `openai` |
| `OPENAI_API_KEY` | Valid OpenAI API key |

**Required for billing (when Stripe is enabled):**

| Variable | Value |
|----------|-------|
| `STRIPE_SECRET_KEY` | `sk_live_...` |
| `STRIPE_PRICE_ID` | `price_...` |
| `STRIPE_WEBHOOK_SECRET` | `whsec_...` |

**Optional but recommended:**

| Variable | Default | Purpose |
|----------|---------|---------|
| `SENTRY_DSN` | `None` | Error reporting |
| `SENTRY_ENVIRONMENT` | `production` | Sentry environment tag |
| `RATE_LIMIT_ENABLED` | `false` | Enable rate limiting |
| `STORAGE_PROVIDER` | `local` | Use `r2` for production assets |
| `STORY_PROVIDER` | `stub` | Use `claude` for production stories |
| `IMAGE_GEN_PROVIDER` | `stub` | Use `flux` for production illustrations |
| `TTS_PROVIDER` | `stub` | Use `elevenlabs` for production narration |

### Secrets Management

Never commit secrets to version control. Use a secrets manager or environment
injection:

- **Cloud providers:** AWS Secrets Manager, GCP Secret Manager, Azure Key Vault
- **Container orchestration:** Kubernetes Secrets, Docker secrets
- **Platform-as-a-service:** Railway, Fly.io, Render environment variables
- **Local development:** `.env` file (gitignored)

Rotate secrets periodically. The app validates critical secrets at startup and
refuses to start with unsafe defaults.

### HTTPS

The API does not terminate TLS. Place a reverse proxy or load balancer in front:

- **nginx/Caddy:** Terminate TLS, proxy to uvicorn on localhost:8000
- **Cloud load balancer:** AWS ALB, Cloudflare, Cloud Run — terminate at the edge
- **Platform PaaS:** Railway, Fly.io, Render handle TLS automatically

Set `WEB_ORIGIN` to the full `https://` origin so CORS works correctly.
Configure Uvicorn's `FORWARDED_ALLOW_IPS` with only the addresses or networks
of trusted proxies. This allows Uvicorn to validate `X-Forwarded-For` before
placing the client address in the ASGI request scope. Do not use `*` unless
the API is unreachable except through that proxy.

### Process Management

The API runs as a single process with in-process background workers:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Use `--workers 1` because background workers run in the same process. Running
multiple workers would duplicate worker execution. For horizontal scaling, run
multiple API replicas behind a load balancer — each replica runs its own
workers, and the database handles concurrency via `FOR UPDATE SKIP LOCKED`.

### Health Checks

Wire `GET /health` to your orchestrator's liveness probe:

```yaml
# Kubernetes example
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 30
```

The endpoint checks database connectivity and returns `503` when degraded.

### CI Pipeline

GitHub Actions runs on every push and PR to `main`:

- **API:** Python 3.11, pytest against SQLite + Postgres 16 service container
- **Web:** Node 20, lint, TypeScript type-check, build

CI never makes paid API calls. All tests run with stub providers and mocked
HTTP clients.

### Production Verification

Before first launch, verify these flows:

1. `POST /auth/register` — create parent, receive token
2. `POST /auth/login` — authenticate, receive token
3. `POST /parents/{id}/children` — create child profile
4. `PUT /parents/{id}/children/{id}/reference-photo` — upload photo
5. `POST /stories` — create story with real provider
6. `GET /stories/{id}` — review story (approve/reject)
7. `GET /reader/children/{id}/stories` — child sees approved stories only
8. `POST /billing/checkout` — Stripe checkout flow
9. `POST /billing/webhook` — Stripe webhook delivery
10. `DELETE /auth/me` — account deletion with Stripe cancel
11. `GET /health` — returns `{"status": "ok"}`
12. Trigger a Sentry test error — confirm it appears in dashboard
13. Send 61 rapid requests to `/auth/login` — confirm 429 under rate limit
