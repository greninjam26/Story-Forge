# Story Forge

Story Forge turns something that happened to a child today into a personalized bedtime storybook with generated text, illustrations, and read-aloud narration. A parent reviews every story before it becomes child-facing.

The project supports English (`en`) by default and French (`fr`) as a second language. The interface language and generated story language are independent choices.

## Current State

- `apps/web` is a Next.js 16 frontend scaffold.
- `apps/api` has FastAPI plus SQLAlchemy session and Alembic migration setup.
- Product models, the story pipeline, parent review flow, and production integrations are still to be built.

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
