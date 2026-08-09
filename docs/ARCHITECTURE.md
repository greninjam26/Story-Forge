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
3. Validate and moderate the submitted event.
4. Generate story text in the child's selected language.
5. Validate the generated title and pages against a schema.
6. Moderate the generated story.
7. Generate an illustration and narration for each page.
8. Save the story as `pending_review`.
9. Allow the parent to approve, reject, or regenerate it.
10. Show only approved stories in the child reader.

Provider failures should produce a clear failed status and reason instead of leaving an incomplete story marked as successful.

## Provider Pattern

External and paid capabilities sit behind environment-selected providers:

| Capability       | Selector                  |
| ---------------- | ------------------------- |
| Story generation | `STORY_PROVIDER`          |
| Illustration     | `IMAGE_GEN_PROVIDER`      |
| Text-to-speech   | `TTS_PROVIDER`            |
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

The illustration stub returns a stable placeholder URL keyed by child and page.
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
erase a billed attempt. Provider failures expose sanitized application errors.

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
```

Relational data lives in sqlite locally and Postgres in production. During
local development, stub media uses deterministic placeholder URLs. Private
child reference photos use opaque `local://references/<uuid>.webp` identifiers
and are stored under `ASSET_CACHE_DIR`. Production reference photos, images,
and narration will live in object storage, with stable private references stored
on `Child` and `StoryPage`. Until that storage milestone, ElevenLabs MP3 files
use random opaque identifiers under `NARRATION_CACHE_DIR` and are served with
private browser caching.

## Child Reference Photos

`PUT /parents/{parent_id}/children/{child_id}/reference-photo` uploads or
replaces one reference photo, and `DELETE` on the same path removes it. Both
routes require the child to belong to the parent identified by the route. The
stored identifier remains an internal field and is not returned by the child
profile schemas; a future authenticated asset route or signed object-storage
URL will provide controlled reads.

Uploads are limited to 10 MB and accept static JPEG, PNG, or WebP images. The
image service applies EXIF orientation, constrains the longest dimension to
2048 pixels, rejects excessive source dimensions and animation, and writes a
metadata-free WebP file. Storage references use validated categories and
random UUID keys so callers cannot choose filesystem paths.

Replacement stores the new file before committing its database reference. A
failed commit removes the new file and retains the prior reference; after a
successful commit, the prior file is removed on a best-effort basis. Explicit
photo removal and child deletion commit the database change before attempting
the same best-effort file cleanup, so a cleanup failure cannot undo a successful
API operation. Cleanup failures are logged. Production object storage should
add durable retry handling for orphaned assets.

## Generation Cost Tracking

Every story creation, regeneration, or narration-producing edit starts a
`GenerationRun` before provider work begins. Provider calls append
`GenerationCostEvent` rows for story text, illustration, and narration, so
failed attempts and safety-rejected generations remain part of the cost record.
Successful and safety-rejected runs link to their resulting story; failed runs
remain storyless so they cannot replace a prior successful cost projection.
Story data, accumulated events, their run link, and the terminal run status are
committed together. A process interruption before finalization may therefore
leave only the precommitted `in_progress` run.

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

Safety checks apply to both parent input and generated story text. Rejected or flagged stories remain parent-visible only, and parent approval is required before a story becomes child-facing.

Tests remain fast, offline, and deterministic. Pipeline tests use stub providers, real provider clients are mocked, and paid APIs are never called during tests.
