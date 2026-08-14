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
`status=generating`, and returns `201` before provider work begins. A
post-response background task opens a fresh database session and fills that
same story record, preserving the ID returned to the parent. Successful work
moves it to `pending_review`; an otherwise unhandled worker error stores the
sanitized `background_generation_failed` reason. Deterministic stubs and local
Ollama keep the synchronous request path for local development and tests.
Claude credentials and ElevenLabs credentials plus paid-call approval are
validated before the story is queued, then checked again by the worker before
any provider call so configuration drift fails without incurring new charges.

This initial background path is process-local rather than a durable job queue.
If the API process stops after returning the story, the record can remain
`generating`; restart recovery and duplicate-charge protection belong to the
separate retry and idempotency work.

Story rows persist the durable state needed for that recovery work:
`generation_claim_token` fences stale workers, `generation_claimed_at` records
claim age, `generation_attempts` counts claims, and `generation_stage` records
the next pipeline stage. New and existing rows start at `story_text` with no
claim and zero attempts. The current process-local worker does not yet acquire
or recover these claims; that behavior remains part of the retry and
idempotency work.

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
             age                  title         image_url
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
