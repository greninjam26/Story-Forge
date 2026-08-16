# AGENTS.md - Story Forge

Instructions for AI coding agents working in this repository. Read this file before making changes. Subdirectories may add their own instructions; `apps/web/AGENTS.md` applies to all frontend work.

## Product

Story Forge creates personalized, illustrated, narrated bedtime stories from a parent-provided daily event. A parent must review each story before it becomes child-facing.

The product supports English (`en`) by default and French (`fr`) as a second language. Keep interface locale (`Parent.locale`) separate from generated story language (`Child.language`, `Story.language`).

## Repository Layout

```text
apps/
  api/
    app/
      main.py                 FastAPI app, CORS, lifespan workers, /health
      config.py               environment settings (pydantic-settings)
      db.py                   engine, sessions, model base
      models.py               Parent, Child, Story, StoryPage, ModerationRecord,
                              GenerationRun, GenerationCostEvent, PendingAssetDeletion
      request_limits.py       reference-photo upload limit middleware
      moderation_review.py    operator CLI: list/show/review audit records
      routers/                parents, children, stories, reader, media
      schemas.py              Pydantic API and generated-story contracts
      services/               generation workflow, providers, safety, storage
      tests/                  pytest suite (offline)
    evals/story_eval.py       offline story-generation evaluation harness
    scripts/                  operator CLIs: cleanup_assets.py, cost_report.py
    migrations/               Alembic env, versions, script templates
    requirements.txt, alembic.ini, .env.example
  web/                        Next.js 16 App Router frontend (early scaffold)
docs/
  ARCHITECTURE.md             target system architecture (not all implemented)
  SPEC.md                     implementation roadmap with completion status
```

`docs/ARCHITECTURE.md` describes the finished system. Do not assume a listed endpoint, model, service, provider, or database field already exists; check the code first. `docs/SPEC.md` marks each work area as complete or not.

## Setup And Checks

Backend:

```bash
cd apps/api
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
PYTHONPATH=. ./.venv/bin/uvicorn app.main:app --reload --port 8000
```

```bash
cd apps/api
PYTHONPATH=. ./.venv/bin/python -m pytest app/tests -q
```

Frontend:

```bash
cd apps/web
npm install
npm run dev
```

```bash
cd apps/web
npm run lint
npx tsc --noEmit
npm run build
```

## Architecture Notes

- Provider selection is env-driven and defaults to deterministic stubs: `STORY_PROVIDER`, `SAFETY_PROVIDER`, `IMAGE_GEN_PROVIDER`, `TTS_PROVIDER`, `STORAGE_PROVIDER`. The complete settings and pricing live in `apps/api/.env.example` and `README.md`.
- Story generation is synchronous for `stub` and `ollama`. Selecting `claude`, `flux`, or `elevenlabs` (paid TTS) makes `POST /stories` persist an empty `generating` story, return `201`, and queue it for an application-owned background worker that fills the same record. Tests disable this worker.
- ElevenLabs requires `TTS_PROVIDER=elevenlabs`, credentials, a voice ID, and `PAID_TTS_ENABLED=true`; credentials alone never authorize a paid call.
- `APP_ENVIRONMENT=production` refuses to start unless `SAFETY_PROVIDER=openai` and a nonblank `OPENAI_API_KEY` are set (validated at app startup in `safety_config.validate_production_configuration`).
- Tests are always offline: an autouse fixture in `apps/api/app/tests/conftest.py` forces stub providers, clears paid credentials, and makes paid HTTP clients raise. Do not add tests that hit real network or providers.
- Migration tests run against both sqlite and Postgres. The Postgres leg uses `POSTGRES_TEST_URL` (set in CI against a local throwaway `*_test` DB) and is skipped locally unless you export it. `alembic check` in that suite fails if migrations drift from the models.
- After changing a SQLAlchemy model, generate and review a migration before applying: `./.venv/bin/alembic revision --autogenerate -m "..."`, then `./.venv/bin/alembic upgrade head`. Models use UUID primary keys and `native_enum=False` enum columns backed by check constraints.
- The frontend is a bare scaffold (layout + landing page); the parent and child-reader interfaces are not built yet. Read `apps/web/AGENTS.md` before frontend work: this Next.js 16 version has breaking conventions, and `node_modules/next/dist/docs/` holds the version-specific guides.
- Operator tooling (asset cleanup, moderation review, cost report) and the offline eval harness (`python -m evals.story_eval --provider stub`) are documented in `README.md` and `docs/ARCHITECTURE.md`.

## Engineering Rules

- Keep API routers focused on HTTP behavior and services focused on product behavior.
- Use Pydantic schemas for API and generated-story contracts; validate structured AI output in code, not just via prompts.
- Use SQLAlchemy 2 typed declarative models and Alembic migrations for schema changes; use type hints and small, focused Python functions.
- Keep user-facing strings out of shared logic, and never treat interface locale and story language as the same setting.
- Keep secrets in environment variables and update `.env.example` when settings change.
- Never call a paid API in tests; mock provider clients and keep tests offline.
- Preserve deterministic `stub` providers for local development and end-to-end tests.
- Update `docs/SPEC.md` or `docs/ARCHITECTURE.md` when an implementation changes an agreed contract.

## Working On A Feature

1. Read the relevant section of `docs/SPEC.md` and the target design in `docs/ARCHITECTURE.md`.
2. Inspect the current code before deciding which files need to change.
3. Add or update focused tests with the implementation.
4. Run the relevant API or frontend checks.
5. Keep unrelated refactors out of the change.
