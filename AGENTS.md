# AGENTS.md — StoryForge

Instructions for AI coding agents (Claude Code, Cursor, Codex, etc.) and a quick orientation for humans. Read this before making changes. A subdirectory may have its own `AGENTS.md` that adds rules for that directory — `apps/web/AGENTS.md` in particular has a hard requirement about the Next.js version.

## What this is

Story Forge turns something that happened to a child today into a personalized, illustrated, read-aloud bedtime storybook: LLM story generation + character-consistent illustration + text-to-speech, behind a parent-preview safety gate. Keep the code approachable and well-tested.

## Repo layout

```
apps/
  api/          FastAPI backend — the AI pipeline lives here
    app/
      services/ story_gen.py · illustration.py · tts.py · safety.py  (swap points)
      routers/  parents · children · stories · billing  (HTTP endpoints)
      models.py schemas.py config.py db.py util.py
      tests/    pytest — mocks all providers, no network in CI
  web/          Next.js 16 frontend (App Router). See apps/web/AGENTS.md.
docs/           SPEC.md (work items / roadmap), ARCHITECTURE.md
```

## Setup & run

Backend:

```bash
cd apps/api
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp .env.example .env            # all providers default to "stub" — runs with zero keys
PYTHONPATH=. ./.venv/bin/uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd apps/web && npm install && npm run dev      # http://localhost:3000
```

Tests (run these before every commit):

```bash
cd apps/api && PYTHONPATH=. ./.venv/bin/python -m pytest app/tests -q
cd apps/web && npx tsc --noEmit && npx eslint src && npm run build
```

## Provider model — the core design

Every external AI/paid service is behind a provider switch selected by an env var, with a `stub` default so the whole app runs offline, free, and deterministically. This is the single most important pattern in the codebase.

| Service      | Env selector         | Values                       | File                           |
| ------------ | -------------------- | ---------------------------- | ------------------------------ |
| Story text   | `STORY_PROVIDER`     | `stub` · `claude` · `ollama` | `app/services/story_gen.py`    |
| Illustration | `IMAGE_GEN_PROVIDER` | `stub` (real: issue #2)      | `app/services/illustration.py` |
| TTS          | `TTS_PROVIDER`       | `stub` · `elevenlabs`        | `app/services/tts.py`          |
| Billing      | (Stripe keys set?)   | stub / real                  | `app/routers/billing.py`       |

`story_gen.py` is the reference implementation: three providers share one age-band → prompt → schema-validate → one-retry path; only the "call the model" step differs. New providers copy that shape. See `docs/ARCHITECTURE.md` for the LLM details.

## Conventions

- **Never call a paid API in a test.** Mock the client (`unittest.mock.patch`). CI must run offline. The `stub` provider exists for exactly this.
- **Structured LLM output is schema-constrained, not prompt-hoped.** Claude uses forced tool-use; Ollama uses `format`=JSON-schema with `minItems`/`maxItems`. If you add a field to the story, change `_story_schema`, not just the prompt.
- **Keep the stub honest.** If you change output shape (e.g. page count), update the stub too so dev/CI matches real behavior.
- Python: type hints, small functions, match the existing style (no framework beyond FastAPI/SQLAlchemy/pydantic).
- Web: **read `apps/web/AGENTS.md` first** — it's Next.js 16, App Router, `params` is a Promise; don't apply pre-16 patterns.
- Bilingual product (zh/en): user-facing strings and generated content support both. Don't hardcode one language into shared logic.

## Working an issue

1. Branch: `git checkout -b <type>/<short-name>` (e.g. `feat/eval-harness`, `fix/cost-tracking`).
2. Read the linked issue's acceptance criteria + the relevant `docs/SPEC.md` section — those are the Definition of Done.
3. Write/adjust tests alongside the change; keep them offline.
4. Run the full test/lint/build set above.
5. Open a PR that references the issue (`Closes #N`) and fill the PR template.

See `CONTRIBUTING.md` for the human-facing version of this.

## Gotchas

- `ELEVENLABS_*` env vars are read by `elevenlabs_client.py` via `os.environ` (ported code); `config.py` declares them and bridges `.env` → `os.environ`. Don't remove that bridge.
- Local dev DB is sqlite (`storyforge.db`, gitignored); the `language` column and other schema come from `Base.metadata.create_all` at startup — delete the file to reset.
- Generated audio goes to `apps/api/audio_cache/` (gitignored), served at `/audio/`. This is interim until R2 storage (issue #5).
