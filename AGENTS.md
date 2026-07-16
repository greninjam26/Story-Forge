# AGENTS.md - Story Forge

Instructions for AI coding agents working in this repository. Read this file before making changes. Subdirectories may add their own instructions; `apps/web/AGENTS.md` applies to all frontend work.

## Product

Story Forge creates personalized, illustrated, narrated bedtime stories from a parent-provided daily event. A parent must review each story before it becomes child-facing.

The product supports English (`en`) by default and French (`fr`) as a second language. Keep interface locale separate from generated story language.

## Current Repository

```text
apps/
  api/
    app/
      main.py                 FastAPI app, CORS, and /health
      config.py               environment settings
      db.py                   SQLAlchemy engine, sessions, and model base
      models.py               Parent model; remaining core models are planned
      routers/                router package; endpoints are still planned
      services/               service package; pipeline is still planned
      tests/                   health, database, and model tests
    migrations/               Alembic migration environment
    alembic.ini
    requirements.txt
    .env.example
  web/                        Next.js 16 App Router frontend
docs/
  ARCHITECTURE.md             target system architecture
  SPEC.md                     implementation roadmap
```

Do not assume that files shown in the target architecture have already been implemented. Check the repository before referring to an endpoint, model, service, provider, or database field as existing.

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

## Engineering Rules

- Read `apps/web/AGENTS.md` before frontend changes. This project uses Next.js 16 and the App Router.
- Keep API routers focused on HTTP behavior and services focused on product behavior.
- Use Pydantic schemas for API and generated-story contracts.
- Use SQLAlchemy 2 typed declarative models and Alembic migrations for schema changes.
- Use type hints and small, focused functions in Python.
- Keep user-facing strings out of shared logic so both English and French remain supported.
- Do not hardcode interface locale and story language as the same setting.
- Keep secrets in environment variables and update `.env.example` when settings change.
- Never call a paid API in tests. Mock provider clients and keep tests offline.
- Preserve deterministic `stub` providers for local development and end-to-end tests.
- Validate structured AI output in code; do not rely only on prompt instructions.
- Update the spec or architecture when an implementation changes an agreed contract.

## Working On A Feature

1. Read the relevant section of `docs/SPEC.md` and the target design in `docs/ARCHITECTURE.md`.
2. Inspect the current code before deciding which files need to change.
3. Add or update focused tests with the implementation.
4. Run the relevant API or frontend checks.
5. Keep unrelated refactors out of the change.
