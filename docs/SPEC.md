# Story Forge Spec

This is the implementation roadmap for turning the current scaffold into a shippable English/French bedtime story product. Each numbered section is a work area; its bullet points are the acceptance criteria.

## Product Direction

Story Forge turns a parent-provided daily event into a personalized bedtime storybook. The parent reviews the result, and only approved content becomes child-facing.

- English (`en`) is the default interface and story language.
- French (`fr`) is supported for interface copy, generated stories, and narration.
- Interface locale and story language are independent choices.
- Child profiles support ages 1 through 12.
- Stories use 8 pages for ages 1–4, 10 pages for ages 5–7, and 12 pages for ages 8–12.
- Free-story limits and subscription rules must be finalized before their related features ship.

## M1: Foundation

### 1. API Foundation

Current status: scaffold complete.

- FastAPI runs from `apps/api`.
- `/health` returns `{"status": "ok"}`.
- Settings load from `.env`, with documented defaults in `.env.example`.
- API tests run with `pytest` and require no live provider calls.

### 2. Database And Models

Current status: SQLAlchemy sessions, Alembic, all four core models, and their
current migrations are complete.

- Add SQLAlchemy and database session setup. (Complete)
- Use sqlite in local development and support Postgres in production. (Complete)
- Add `Parent`, `Child`, `Story`, and `StoryPage` models. (Complete)
- Define story generation, review, rejection, and failure statuses. (Complete)
- Store interface locale separately from child and story language. (Complete)
- Store a private reference-photo identifier on child profiles. (Complete)
- Add migrations and document local reset instructions. (Complete)

### 3. Parent And Child APIs

Current status: schemas, parent/child profile routes, and private reference-photo
upload and removal are complete.

- Create and retrieve a parent profile. (Complete)
- Create, read, update, and delete child profiles. (Complete)
- Validate child name, supported age, interests, and story language. (Complete)
- Upload, replace, and remove one parent-scoped reference photo per child. (Complete)
- Normalize JPEG, PNG, and WebP uploads into bounded, metadata-free WebP files. (Complete)
- Keep reference-photo identifiers out of public child responses. (Complete)
- Define Pydantic request and response schemas for every endpoint. (Complete)
- Add router tests for successful and invalid requests. (Complete)

## M2: Story Pipeline

### 4. Stub Story Generation

Current status: schemas, deterministic stub generation, persistence, and core story routes are complete.

- Add deterministic story generation behind `STORY_PROVIDER=stub`. (Complete)
- Return a validated title and exact number of page strings. (Complete)
- Adjust page count and language complexity by age group. (Complete)
- Support English and French output. (Complete)
- Test page count, schema validation, age handling, and language selection. (Complete)
- Persist generated stories and pages and expose create, list, and retrieve routes. (Complete)

### 5. Real Story Provider

Current status: production Claude, hosted Groq, and local Ollama providers,
shared structured-output validation, retry accounting, and offline provider
tests are complete.

- Add Claude, Groq, and local Ollama providers behind `STORY_PROVIDER`. (Complete)
- Keep the stub as the local and test default. (Complete)
- Use forced tool output for Claude and schema-constrained JSON for Groq and Ollama. (Complete)
- Validate output in Python, fail immediately when malformed, and retry transient provider failures. (Complete)
- Record Claude and Groq token usage, zero-cost Ollama requests, and estimated generation cost. (Complete)
- Mock the provider clients in tests. (Complete)

### 6. Safety And Parent Review

Current status: local English/French keyword screening, optional OpenAI
moderation for generated titles and pages, privacy-limited moderation audits,
generation failure recording, parent review actions, and approved-only child
access are complete. Production startup fails closed unless OpenAI moderation
is configured.

- Apply local keyword safety checks to the parent's event before generation. (Complete)
- Apply the keyword prefilter and configured moderation provider to generated titles and pages before image or audio generation. (Complete)
- Keep local development and tests offline while requiring OpenAI moderation in production. (Complete)
- Fail closed when configured moderation is unavailable or returns invalid data. (Complete)
- Store a stable parent-facing reason when content is rejected. (Complete)
- Atomically store one privacy-limited audit record for each generated-content rejection. (Complete)
- Expose event recovery fields only through the parent-review story detail response. (Complete)
- Provide a private database CLI for moderation review. (Complete)
- Store a clear reason when generation fails. (Complete)
- Allow the parent to approve, reject, edit, or regenerate a story. (Complete)
- Make only approved stories available in the child reader. (Complete)

### 7. Illustration And Narration

Current status: deterministic illustration and narration placeholders, paid
ElevenLabs narration, direct-BFL FLUX generation, and Cloudflare Workers AI
FLUX generation are complete.
Private child reference-photo ingestion, generated-image persistence, provider
usage accounting, retry and cleanup handling, and offline provider tests are
complete for local and private Cloudflare R2 storage.

- Add deterministic image and audio placeholders for local development. (Complete)
- Accept and privately persist normalized child reference photos. (Complete)
- Select ElevenLabs as the production text-to-speech provider. (Complete)
- Select FLUX as the production illustration provider. (Complete)
- Support Cloudflare Workers AI FLUX with a free-plan hard quota. (Complete)
- Generate one image and one narration asset per page. (Complete for stub, direct FLUX, Cloudflare, and ElevenLabs providers)
- Generate one narration asset per page with ElevenLabs. (Complete)
- Support narration in both English and French. (Complete for stub and ElevenLabs providers)
- Store narration usage and estimated cost. (Complete)
- Store illustration usage and estimated cost. (Complete)
- Mock the ElevenLabs client boundary in tests. (Complete)
- Mock the FLUX client boundary in tests. (Complete)
- Mock the Cloudflare Workers AI client boundary in tests. (Complete)

### 8. Pipeline Reliability And Evaluation

Current status: story rows store durable generation claim, attempt, and stage
state. Atomic claim acquisition, stale-claim recovery, bounded attempts, and
the periodic recovery worker are complete. The worker persists progress at
each pipeline stage and resumes from the persisted stage after a crash,
skipping provider work that already finished, so no stage is re-run and no
charges are duplicated across crash recovery. An optional parent-scoped
`Idempotency-Key` header on `POST /stories` replays a duplicate request with
the existing story instead of creating a second one, so retries can no longer
duplicate stories or charges.

- Run slow generation work outside the request cycle when production providers are enabled. (Complete with an application-owned worker and restart recovery)
- Make retries idempotent so duplicate stories and charges are avoided. (Complete: resumable stages, request-level `Idempotency-Key` dedup, and provider-error retries with exponential backoff)
- Clean up or clearly mark partially generated stories and their assets. (Complete)
- Track each generation stage and expose useful progress or failure states. (Complete: stages persisted and exposed on the parent story API)
- Add offline evaluations for page-count accuracy, language correctness, structure, and safety. (Complete)
- Keep all automated tests and evaluations free of paid API calls by default.

## M3: Product Experience

### 9. Parent Experience

Current status: Next.js 16 scaffold with Story Forge branding, JWT auth API
client, proxy via next.config.ts rewrites, and root layout. Landing page,
login, and registration forms are complete. EN/FR locale provider and language
switcher are complete. Error classifier for story-creation failures is complete.
Children list with add/edit/delete, child dashboard with event entry and story
generation, and story review page with approve/reject/reader are complete.
Shared hooks extracted: `useRequireAuth`, `useAsyncAction`, `useBilling`.
Native TypeScript error classifier (`.mjs` → `.ts`). a11y: sr-only labels,
role=alert on errors, aria-busy on loading buttons, descriptive link text.

- Replace the default Next.js screen with the Story Forge application. (Complete: landing page, login, registration, root layout with branding)
- Add parent onboarding and child profile management. (Complete: children list page with add, edit, delete, reference photo upload)
- Add event entry, generation progress, preview, and review flows. (Complete: child dashboard with generate button, story review with approve/reject, inline reader)
- Include clear loading, empty, validation, and failure states. (Complete: loading states, empty states, error messages, quota/upgrade prompts)

### 10. English And French Interface

Current status: i18n approach using Next.js 16 App Router with `LocaleProvider`,
`useLocale()`, `useT()` hooks, and `en`/`fr` message catalogs. Language
switcher and root layout with locale detection are complete. The browser stores
the active locale locally and restores the account locale after authentication.

- Add an internationalization approach compatible with Next.js 16 App Router. (Complete: `lib/i18n.tsx` with LocaleProvider and useT hook)
- Move user-facing strings into `en` and `fr` catalogs. (Complete: `lib/messages.ts` with ~80 keys)
- Default to English and persist the parent's locale. (Complete: localStorage persistence, authenticated account updates, account-locale restoration after authentication, `DEFAULT_LOCALE` fallback)
- Keep interface locale independent from story language. (Complete)
- Test important flows in both languages. (Complete: `tests/i18n.test.mjs`)

### 11. Child Reader

Current status: Public child reader at `/reader/{childId}` and
`/reader/{childId}/stories/{storyId}`. Story list shows approved stories as a
responsive grid with thumbnails. Immersive reader with full-width images, large
text, audio auto-play, swipe/keyboard navigation, and page indicator. All
pages use Suspense boundaries, role=alert on errors, aria-live on loading. The
nested detail API verifies that the approved story belongs to the requested
child.

- Show only parent-approved stories. (Complete: reader API returns only approved stories)
- Add stable page navigation with image, text, and audio controls. (Complete: prev/next buttons, swipe gestures, keyboard arrows, audio auto-play)
- Support play, pause, replay, and missing-audio states. (Complete: `<audio>` controls, handles missing audio_url gracefully)
- Make the reader responsive and comfortable on phones. (Complete: max-w-lg layout, large touch targets, responsive text)
- Meet basic keyboard, focus, contrast, and screen-reader accessibility needs. (Complete: aria-labels, role=alert, aria-live, keyboard navigation)

## M4: Production Readiness

### 12. Authentication And Authorization

- Select and document a parent authentication approach. (Complete: JWT bearer tokens via `passlib[bcrypt]` + `python-jose[cryptography]`)
- Use secure sessions and protect private API routes. (Complete: password registration uses `/auth/register`, login uses `/auth/login`, and all parent/child/story routes require `Authorization: Bearer <token>`)
- Confirm that a parent can access only their own children and stories. (Complete: `require_parent_owner`, `require_child_owner`, `require_story_owner` dependencies)
- Test unauthorized and cross-account access attempts. (Complete: authentication and resource-router suites cover unauthorized and cross-account access)

### 13. Billing And Usage Limits

- Select and document a billing provider and subscription model. (Complete)
- Implement checkout, billing status updates, and cancellation handling. (Complete)
- Enforce free-story and subscription limits on the API. (Complete)
- Show remaining usage and billing failures clearly in the interface. (Complete: usage displayed on child dashboard, billing success/cancel confirmation pages)
- Handle duplicate billing events safely. (Complete)

### 14. Privacy And Data Lifecycle

- Document what parent and child data is collected and why. (Complete)
- Define retention rules for profiles, event text, stories, images, and audio. (Complete)
- Add parent-initiated deletion for a child and all related assets. (Complete)
- Remove managed reference photos, illustrations, and narration when they are replaced, no longer owned by a story, removed, or their child is deleted. (Complete)
- Avoid storing unnecessary sensitive data in logs or provider requests. (Complete)
- Publish the required privacy and terms pages before launch. (Complete: `/privacy` and `/terms` pages with en/fr i18n)

### 15. Storage And Operations

- Store relational data in managed Postgres. (Complete)
- Store generated images and audio in object storage. (Complete with Cloudflare R2)
- Store child reference photos in object storage for production. (Complete with Cloudflare R2)
- Use stable private identifiers for managed assets. (Complete)
- Resolve private object references into expiring signed client URLs. (Complete)
- Define durable deletion, automatic retry, and operator recovery behavior. (Complete)
- Add rate limiting, structured logging, error reporting, and health monitoring. (Complete)
- Document environment variables, secrets, backups, and recovery steps. (Complete)

### 16. Deployment And CI

CI, platform deployment configuration, and the production runbook are
implemented. Provisioning the hosted services and verifying the deployed
application remain before launch.

- Document API and web deployment procedures. (Complete: `docs/DEPLOY-PRODUCTION.md`)
- Run API, frontend, and Playwright end-to-end checks on pull requests. (Complete)
- Keep CI offline except for dependency installation. (Complete)
- Configure hosted production HTTPS, CORS, and environment settings. (Pending)
- Verify the main English and French flows in a production-like environment. (Pending)

## Out Of Scope For Now

- Languages beyond English and French.
- Native mobile applications.
- Social sharing and public story galleries.
- Voice cloning.
- Growth analytics and marketing experiments.
