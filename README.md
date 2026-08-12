# Story Forge

Story Forge turns something that happened to a child today into a personalized bedtime storybook with generated text, illustrations, and read-aloud narration. A parent reviews every story before it becomes child-facing.

The project supports English (`en`) by default and French (`fr`) as a second language. The interface language and generated story language are independent choices.

## Current State

- `apps/web` is a Next.js 16 frontend scaffold.
- `apps/api` has FastAPI, SQLAlchemy models, Alembic migrations, and parent/child and story APIs.
- Story generation supports deterministic stubs, Claude, and local Ollama with validated English/French structured output.
- Narration supports deterministic WAV placeholders and paid ElevenLabs MP3 generation with offline-tested provider boundaries.
- Private reference photos, FLUX illustrations, and ElevenLabs narration support local storage and private Cloudflare R2 object storage with signed reads and durable deletion retries.
- Generated stories and pages can be created, listed, retrieved, edited, reviewed, and regenerated.
- Deterministic English/French safety checks moderate parent events and generated story text before parent review.
- Approved stories can be listed and retrieved through the child-reader API.
- The child-reader interface and remaining authentication and billing integrations are still to be built.

## Project Structure

```text
apps/
  api/    FastAPI backend
  web/    Next.js frontend
docs/
  ARCHITECTURE.md    intended finished system
  SPEC.md            implementation roadmap
```

## API Setup

```bash
cd apps/api
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
PYTHONPATH=. ./.venv/bin/uvicorn app.main:app --reload --port 8000
```

The API runs at `http://localhost:8000`. FastAPI documentation is available at `http://localhost:8000/docs`.

Story generation defaults to `STORY_PROVIDER=stub`. Set it to `claude` with an
`ANTHROPIC_API_KEY`, or to `ollama` with a locally available model. The complete
provider and pricing settings are documented in `apps/api/.env.example`.

Narration defaults to `TTS_PROVIDER=stub`. ElevenLabs requires the provider
selector, API key, voice ID, and `PAID_TTS_ENABLED=true`; credentials alone do
not authorize a paid call. With local storage, generated MP3 files use opaque
URLs backed by `NARRATION_CACHE_DIR`. With R2, narration is stored alongside
the other private story assets.

Apply database migrations from `apps/api` with:

```bash
./.venv/bin/alembic upgrade head
```

After changing SQLAlchemy models, generate a migration and review it before applying it:

```bash
./.venv/bin/alembic revision --autogenerate -m "describe schema change"
```

To reset local development data, stop the API, remove the ignored `apps/api/storyforge.db` file, and run `alembic upgrade head` again. Removing that file permanently deletes the local data; it does not affect production databases.

Local development uses sqlite by default. Production can use a `postgresql+psycopg://` URL through `DATABASE_URL`.

## Private Asset Storage

`STORAGE_PROVIDER=local` is the development default. Reference photos and FLUX
illustrations are stored beneath `ASSET_CACHE_DIR`; generated ElevenLabs audio
uses `NARRATION_CACHE_DIR`.

For Cloudflare R2, set `STORAGE_PROVIDER=r2` and provide `R2_ACCOUNT_ID`,
`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, and `R2_BUCKET`. The database keeps
stable private `r2://` references instead of expiring URLs. Story responses
resolve those references into signed read URLs using `R2_PRESIGN_TTL_SECONDS`.

Managed assets that are replaced, deleted, or abandoned by a failed generation
are queued for durable deletion. The API processes due work at startup and every
`ASSET_CLEANUP_WORKER_INTERVAL_SECONDS` when
`ASSET_CLEANUP_WORKER_ENABLED=true`. From `apps/api`, an operator can process
the queue manually:

```bash
PYTHONPATH=. ./.venv/bin/python scripts/cleanup_assets.py
```

Use `--limit 100` to cap one run. After fixing a persistent storage problem,
use `--retry-terminal` to return deletions that exhausted automatic retries to
the queue. The command reports deleted, failed, pending, and terminal counts;
it exits nonzero while any backlog remains.

Run the API tests with:

```bash
cd apps/api
PYTHONPATH=. ./.venv/bin/python -m pytest app/tests -q
```

## Web Setup

```bash
cd apps/web
npm install
npm run dev
```

The web app runs at `http://localhost:3000`.

Run the frontend checks with:

```bash
cd apps/web
npm run lint
npx tsc --noEmit
npm run build
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) describes how the finished system should fit together.
- [Product spec](docs/SPEC.md) lists the work required to build and launch it.
