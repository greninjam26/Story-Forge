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

Current status: SQLAlchemy sessions, Alembic, all four core models, and the initial migration are complete.

- Add SQLAlchemy and database session setup. (Complete)
- Use sqlite in local development and support Postgres in production. (Complete)
- Add `Parent`, `Child`, `Story`, and `StoryPage` models. (Complete)
- Define story generation, review, rejection, and failure statuses. (Complete)
- Store interface locale separately from child and story language. (Complete)
- Add migrations and document local reset instructions. (Complete)

### 3. Parent And Child APIs

Current status: schemas and parent/child profile routes are complete.

- Create and retrieve a parent profile. (Complete)
- Create, read, update, and delete child profiles. (Complete)
- Validate child name, supported age, interests, and story language. (Complete)
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

Current status: production Claude and local Ollama providers, shared structured-output validation, retry accounting, and offline provider tests are complete.

- Add Claude and local Ollama providers behind `STORY_PROVIDER`. (Complete)
- Keep the stub as the local and test default. (Complete)
- Use forced tool output for Claude and schema-constrained JSON for Ollama. (Complete)
- Validate output in Python and retry once when malformed. (Complete)
- Record Claude token usage, zero-cost Ollama requests, and estimated generation cost. (Complete)
- Mock the provider clients in tests. (Complete)

### 6. Safety And Parent Review

Current status: deterministic safety moderation, generation failure recording,
parent review actions, and approved-only child access are complete.

- Validate and moderate the parent's event before story generation. (Complete)
- Moderate generated story text before image or audio generation. (Complete)
- Store a clear reason when content is rejected. (Complete)
- Store a clear reason when generation fails. (Complete)
- Allow the parent to approve, reject, edit, or regenerate a story. (Complete)
- Make only approved stories available in the child reader. (Complete)

### 7. Illustration And Narration

Current status: deterministic illustration and playable narration placeholders,
provider selection, per-page persistence, and media failure handling are
complete. Production providers, usage, and cost tracking remain.

- Add deterministic image and audio placeholders for local development. (Complete)
- Select real illustration and text-to-speech providers for production.
- Generate one image and one narration asset per page. (Complete for stub providers)
- Support narration in both English and French. (Complete for the stub provider)
- Store provider usage and estimated cost.
- Mock provider clients in tests.

### 8. Pipeline Reliability And Evaluation

- Run slow generation work outside the request cycle when production providers are enabled.
- Make retries idempotent so duplicate stories and charges are avoided.
- Clean up or clearly mark partially generated stories.
- Track each generation stage and expose useful progress or failure states.
- Add offline evaluations for page-count accuracy, language correctness, structure, and safety.
- Keep all automated tests and evaluations free of paid API calls by default.

## M3: Product Experience

### 9. Parent Experience

- Replace the default Next.js screen with the Story Forge application.
- Add parent onboarding and child profile management.
- Add event entry, generation progress, preview, and review flows.
- Include clear loading, empty, validation, and failure states.

### 10. English And French Interface

- Add an internationalization approach compatible with Next.js 16 App Router.
- Move user-facing strings into `en` and `fr` catalogs.
- Default to English and persist the parent's locale.
- Keep interface locale independent from story language.
- Test important flows in both languages.

### 11. Child Reader

- Show only parent-approved stories.
- Add stable page navigation with image, text, and audio controls.
- Support play, pause, replay, and missing-audio states.
- Make the reader responsive and comfortable on phones.
- Meet basic keyboard, focus, contrast, and screen-reader accessibility needs.

## M4: Production Readiness

### 12. Authentication And Authorization

- Select and document a parent authentication approach.
- Use secure sessions and protect private API routes.
- Confirm that a parent can access only their own children and stories.
- Test unauthorized and cross-account access attempts.

### 13. Billing And Usage Limits

- Select and document a billing provider and subscription model.
- Implement checkout, billing status updates, and cancellation handling.
- Enforce free-story and subscription limits on the API.
- Show remaining usage and billing failures clearly in the interface.
- Handle duplicate billing events safely.

### 14. Privacy And Data Lifecycle

- Document what parent and child data is collected and why.
- Define retention rules for profiles, event text, stories, images, and audio.
- Add parent-initiated deletion for a child and all related assets.
- Avoid storing unnecessary sensitive data in logs or provider requests.
- Publish the required privacy and terms pages before launch.

### 15. Storage And Operations

- Store relational data in managed Postgres.
- Store generated images and audio in object storage.
- Define stable asset URLs and deletion behavior.
- Add rate limiting, structured logging, error reporting, and health monitoring.
- Document environment variables, secrets, backups, and recovery steps.

### 16. Deployment And CI

- Document API and web deployment procedures.
- Run API tests and frontend lint, type, and build checks on pull requests.
- Keep CI offline except for dependency installation.
- Configure production HTTPS, CORS, and environment settings.
- Verify the main English and French flows in a production-like environment.

## Out Of Scope For Now

- Languages beyond English and French.
- Native mobile applications.
- Social sharing and public story galleries.
- Voice cloning.
- Growth analytics and marketing experiments.
