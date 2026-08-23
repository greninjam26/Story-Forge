# Production Deployment And Recovery

This runbook describes the intended hosted deployment for Story Forge. It does
not mean that the services have been created or that the hosted flows have been
verified.

Never commit credentials, database URLs, provider keys, or generated backup
files. Store them in the platform secret stores and an account-owner password
manager.

## Topology

```text
Browser -> Vercel (Next.js)
              |
              | /api/* server-side rewrite
              v
           Fly.io (FastAPI container)
              |-- Neon Postgres
              |-- Cloudflare R2 private bucket
              |-- Anthropic and OpenAI
              |-- Black Forest Labs (optional FLUX)
              |-- ElevenLabs (optional paid narration)
              |-- Stripe (optional billing)
              `-- Sentry (optional monitoring)
```

The browser uses the Vercel origin and calls `/api`. Next.js proxies those
requests to Fly through the rewrite in `apps/web/next.config.ts`. JWT bearer
authentication does not require a same-origin cookie, but the proxy avoids an
unnecessary cross-origin API configuration and gives placeholder media a
stable public base URL.

The committed platform files are:

- `apps/api/Dockerfile` and `apps/api/.dockerignore`
- `apps/api/fly.toml`
- `apps/web/vercel.json`
- `docker-compose.yml` for local Postgres only

## Deployment Values

Record the final values before setting any environment variables:

| Name | Example |
|---|---|
| Fly app | `greninjam26-story-forge-api` |
| API origin | `https://greninjam26-story-forge-api.fly.dev` |
| Web origin | `https://<vercel-project>.vercel.app` or a custom domain |
| API public base | `<web-origin>/api` |
| Neon direct URL | `postgresql+psycopg://...?...sslmode=require` |
| R2 bucket | A private production-assets bucket |

Fly app names are globally unique. If the committed name is unavailable,
change `app` in `apps/api/fly.toml` before creating the app and use the new
hostname everywhere below.

## Preconditions

1. The branch intended for production has passed API, web, and Playwright CI.
2. Create the Fly.io, Vercel, Neon, and Cloudflare accounts.
3. Install `flyctl`. Install the Vercel CLI only if deploying outside the
   dashboard.
4. Keep the production services in nearby regions. The committed Fly region
   is `iad`; use a Neon AWS US East region unless there is a reason to change
   both.
5. Decide who owns billing, provider, monitoring, backup, and domain accounts.
   Do not tie production recovery to an account nobody else can access.

Run the local checks immediately before a release:

```bash
cd apps/api
PYTHONPATH=. ./.venv/bin/python -m pytest app/tests -q

cd ../web
npm test
npm run lint
npx tsc --noEmit
npm run build
```

## Optional Local Postgres Check

SQLite remains the default for everyday development. To verify the application
against PostgreSQL before using Neon:

```bash
docker compose up -d postgres

cd apps/api
DATABASE_URL='postgresql+psycopg://storyforge:storyforge@localhost:5432/storyforge' \
  ./.venv/bin/alembic upgrade head
DATABASE_URL='postgresql+psycopg://storyforge:storyforge@localhost:5432/storyforge' \
  ./.venv/bin/alembic check
```

`docker compose down` stops the database but retains its named volume. Adding
`--volumes` permanently deletes that local database.

## One-Time Platform Setup

### 1. Provision Neon Postgres

Create a Neon project near `iad`. In the connection dialog, disable connection
pooling and copy the direct URL. Neon recommends direct connections for schema
migrations and `pg_dump`; this project uses the same `DATABASE_URL` for the
release migration and the running API.

Change only the URL scheme from `postgresql://` to
`postgresql+psycopg://` so SQLAlchemy selects the installed Psycopg 3 driver.
Preserve the generated host, credentials, database name, and query parameters.

For a new empty database, do not stamp an Alembic revision. The Fly release
command will run `alembic upgrade head` and create the complete schema. Before
pointing production at an existing database, inspect it explicitly:

```bash
cd apps/api
DATABASE_URL='<neon-direct-url>' ./.venv/bin/alembic current
DATABASE_URL='<neon-direct-url>' ./.venv/bin/alembic upgrade head
DATABASE_URL='<neon-direct-url>' ./.venv/bin/alembic check
```

Do not copy revision identifiers or stamp instructions from another project.
If an existing schema is not migration-managed, stop and reconcile it against
this repository's own migration history before deployment.

### 2. Provision Cloudflare R2

Create a private bucket. A public bucket or R2 custom domain is not required;
the API stores stable `r2://` references and returns short-lived signed URLs.

Create an R2 S3 API token with Object Read & Write access restricted to this
bucket. Save the following values once:

- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET`

Do not apply a retention lock to the live bucket. Parent-initiated deletion
must be able to remove reference photos, illustrations, and narration. Use a
separate backup bucket with an appropriate retention policy instead.

### 3. Create The Fly And Vercel Projects

Create the empty Fly app from the directory containing `fly.toml`:

```bash
cd apps/api
fly auth login
fly apps create greninjam26-story-forge-api
```

Import the GitHub repository into Vercel and configure:

- Root Directory: `apps/web`
- Framework: Next.js
- Production branch: `main`
- Production environment variable `BACKEND_ORIGIN`: the Fly API origin
- `NEXT_PUBLIC_API_URL`: leave unset so browser calls remain on `/api`

The first web deployment can occur before the API is available. Record the
stable Vercel production origin; Fly needs it before the API can start.

### 4. Configure Required Fly Secrets

Generate a random JWT signing secret of at least 32 bytes and store it in the
password manager:

```bash
openssl rand -hex 32
```

Stage the required values from `apps/api`. Replace every placeholder first:

```bash
fly secrets set --stage \
  DATABASE_URL='<neon-direct-url>' \
  JWT_SECRET_KEY='<random-secret>' \
  WEB_ORIGIN='<web-origin>' \
  API_BASE_URL='<web-origin>/api' \
  TRUSTED_HOSTS='["<fly-app>.fly.dev","<web-host>"]' \
  ANTHROPIC_API_KEY='<anthropic-key>' \
  OPENAI_API_KEY='<openai-key>' \
  R2_ACCOUNT_ID='<r2-account-id>' \
  R2_ACCESS_KEY_ID='<r2-access-key-id>' \
  R2_SECRET_ACCESS_KEY='<r2-secret-access-key>' \
  R2_BUCKET='<r2-bucket>'
```

`apps/api/fly.toml` supplies these non-secret production choices:

- `APP_ENVIRONMENT=production`
- `STORY_PROVIDER=claude`
- `SAFETY_PROVIDER=openai`
- `STORAGE_PROVIDER=r2`
- rate limiting enabled
- image generation and narration kept on stubs initially

Claude story generation and OpenAI moderation make real network calls when a
story is requested. Confirm both accounts' billing, quotas, and spend alerts
before exposing registration publicly.

Production startup deliberately fails when OpenAI moderation, the JWT secret,
the HTTPS web origin, or restricted trusted hosts are missing. Confirm secret
names without revealing values:

```bash
fly secrets list
fly config show --local
```

### 5. Deploy The API

From `apps/api`:

```bash
fly deploy
fly scale count 1
fly status
fly logs
```

The `[deploy]` release command runs `alembic upgrade head` in a temporary
machine before replacing the API machines. A failed migration stops the
deployment. Do not remove that ordering or run schema creation at API startup.

The first Fly deployment can create redundant machines by default. One machine
is enough for the initial solo deployment; each machine still runs one Uvicorn
process and its application-owned background workers. Increase the machine
count later for availability, not the Uvicorn worker count.

Verify Fly directly:

```bash
curl https://<fly-app>.fly.dev/health
```

The expected response has `status: "ok"` and `components.database: "ok"`.

### 6. Deploy The Web App

Confirm `BACKEND_ORIGIN` is set for the Vercel Production environment, then
redeploy the current `main` commit. Environment-variable changes do not alter
already-built Vercel deployments.

Verify the API through the web proxy:

```bash
curl https://<web-host>/api/health
```

If using a custom domain, add it through Vercel and follow the DNS records
Vercel provides. After it resolves, stage the final origins and deploy again:

```bash
cd apps/api
fly secrets set --stage \
  WEB_ORIGIN='https://<custom-domain>' \
  API_BASE_URL='https://<custom-domain>/api' \
  TRUSTED_HOSTS='["<fly-app>.fly.dev","<custom-domain>"]'
fly deploy
```

The committed Vercel configuration sends HSTS with `includeSubDomains`. Use a
custom domain only when every affected subdomain supports HTTPS, or revise
that header before launch.

## Optional Production Integrations

Enable optional paid integrations one at a time, verify one story, and inspect
the cost report before enabling the next integration.

### FLUX Illustrations

1. Create a Black Forest Labs key.
2. Stage `IMAGE_GEN_API_KEY` on Fly.
3. Change `IMAGE_GEN_PROVIDER` in `fly.toml` from `stub` to `flux` in a reviewed
   commit.
4. Deploy and generate one test story.

FLUX calls cost money. `STORY_COST_CEILING_USD` is an alarm recorded on the
generation run; it does not stop calls when the ceiling is exceeded.

### ElevenLabs Narration

1. Select a voice that handles both English and French acceptably.
2. Stage `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` on Fly.
3. Set an accurate `ELEVENLABS_COST_PER_CHARACTER_USD` for the account plan.
4. In a reviewed `fly.toml` change, set `TTS_PROVIDER=elevenlabs` and
   `PAID_TTS_ENABLED=true`.
5. Deploy and verify generated MP3 playback in both languages.

Credentials alone never authorize paid narration; the explicit paid flag is
required.

### Stripe Billing

Start in Stripe test mode:

1. Create the subscription product and recurring price.
2. Configure the Stripe customer portal.
3. Stage `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, and
   `STRIPE_WEBHOOK_SECRET` on Fly.
4. Add the direct API webhook endpoint:
   `https://<fly-app>.fly.dev/billing/webhook`.
5. Subscribe it to:
   - `checkout.session.completed`
   - `checkout.session.async_payment_succeeded`
   - `checkout.session.async_payment_failed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_failed`
6. Deploy, complete a test checkout, open the billing portal, cancel the test
   subscription, and confirm `/auth/me` reflects each transition.

The webhook signing secret begins with `whsec_` and is not the Stripe API key.
The webhook is the source of truth; the success redirect alone does not grant
a subscription.

### Sentry And Uptime

The API supports Sentry when `SENTRY_DSN` is set. Create a Python/FastAPI
project, stage its DSN, deploy, and confirm a deliberately generated test event
without including child or story content. The web app does not yet include a
Sentry SDK.

Create external uptime monitors for:

- `https://<web-host>/`
- `https://<web-host>/api/health`

Alert an email address that is checked. The API health endpoint returns 503
when the database is unreachable; provider failures appear in API logs and
configured Sentry events instead.

## Production Verification

Do not mark hosted verification complete until all applicable checks pass.

### Platform

- Direct Fly health and proxied web health both return 200.
- Fly logs contain no startup, migration, or background-worker failures.
- Vercel responses contain the configured security headers.
- A production deploy survives closing the development laptop.
- Neon, R2, Fly, and provider dashboards show the expected region and usage.

### Parent And Reader Flows

Run the browser flow once with an English child and once with a French child:

1. Register, log out, and log back in with a password.
2. Change the interface language and confirm it remains independent from the
   child's story language.
3. Create a child and upload a reference photo.
4. Generate a story and wait for `pending_review`.
5. Edit a page, approve the story, and open the public reader without a parent
   token.
6. Confirm illustrations and narration load, navigation works, and the story
   belongs to the child in the URL.
7. Reject a separate story and confirm it never appears in the reader.
8. Delete a test child and confirm managed assets leave R2 after cleanup.
9. With Stripe configured, complete and cancel a test subscription.
10. With a disposable account, verify full account deletion.

Use controlled test accounts when checking rate limits so a real parent is not
locked out.

### Operations And Cost

From a Fly console:

```bash
fly ssh console -C "python scripts/cost_report.py --last 100"
fly ssh console -C "python scripts/cleanup_assets.py --limit 100"
```

The cleanup command exits nonzero while pending or terminal work remains. After
fixing a persistent R2 problem, add `--retry-terminal` to return terminal work
to the retry queue.

## Normal Deployment Order

1. Merge only after CI is green.
2. For a model change, include and review its Alembic migration. Confirm a
   current database recovery point before deploying.
3. Deploy the API from `apps/api`. Fly runs the migration release command
   before replacing application machines.
4. Promote or deploy the Vercel build.
5. Run direct and proxied health checks and the affected browser smoke flow.
6. Review Fly logs, Vercel logs, Sentry, and the cost report.

Use backward-compatible expand-and-contract migrations when a web and API
change cannot be deployed atomically. Vercel may deploy automatically from
`main`, while the Fly deploy is currently manual.

## Backups

### Postgres

- Configure Neon's history-retention window and understand the account plan's
  point-in-time restore limit.
- Before risky schema or data changes, create a Neon branch or verified restore
  point.
- Periodically run `pg_dump` using the direct, non-pooled connection. Run it
  from a secure directory outside the repository, encrypt the resulting file,
  and store it separately from Neon.
- Test a restore into a non-production database on a schedule. A backup that
  has never been restored is not a verified backup.

Example from a secure backup directory:

```bash
pg_dump --format=custom --no-owner \
  --file=story-forge-YYYY-MM-DD.dump '<neon-direct-url>'
```

Database dumps contain parent and child data. Apply the documented retention
and deletion policy to every backup copy.

### R2

- Keep the live bucket private and unlocked so application deletion works.
- Use `rclone copy`, not `sync`, on a schedule to copy objects to a separate
  private backup bucket or account. `copy` does not delete destination objects
  that have disappeared from the live bucket.
- A time-limited bucket-lock rule can protect the backup bucket from accidental
  deletion. Do not use an indefinite rule without confirming that it complies
  with parent deletion and retention obligations.
- Test restoring selected objects with their original keys.

Database rows and R2 keys form one logical backup. Restore them to compatible
points in time; blindly restoring old objects can resurrect assets a parent
already deleted.

### Secrets

- Keep an inventory of the owner and rotation procedure for every secret.
- Rotate a provider credential immediately after suspected exposure.
- Stage replacement Fly secrets, deploy, verify, and then revoke the old
  credential at the provider.

## Rollback And Recovery

### Web Rollback

Use Vercel's Instant Rollback to point the production domain at a previously
served deployment. Environment-variable changes are not rebuilt by an instant
rollback, so restore incompatible values separately.

### API Rollback

List release images and redeploy the last known-good image:

```bash
cd apps/api
fly releases --image
fly deploy --image '<previous-image-reference>'
```

An image rollback does not roll back the database, Fly secrets, or the current
`fly.toml`. Prefer forward-compatible migrations. If a migration changed data
destructively, restore the database deliberately instead of assuming an older
container repairs it.

### Database Recovery

1. Record the incident time and preserve logs.
2. Stop writes before restoring if consistency is at risk.
3. Use Neon Time Travel to inspect the target point before restoring it to a
   recovery branch.
4. Test the recovered branch with a compatible API image.
5. Stage the recovered direct URL as `DATABASE_URL`, deploy, and verify health
   plus critical reads before reopening traffic.
6. Retain the damaged branch until the recovery is confirmed.

If the database is restored to an earlier time, restore only the R2 objects
needed by that database state. Preserve original object keys so stored
`r2://` references remain valid.

## Incident Checks

1. Call both health URLs. A degraded database component points to Neon or its
   credentials; a healthy direct API with a failed proxy points to Vercel or
   `BACKEND_ORIGIN`.
2. Inspect `fly logs`, Vercel deployment logs, and Neon status and metrics.
3. Check provider status before retrying a generation incident.
4. Run the cost and cleanup reports for spend or asset incidents.
5. Roll back only the affected layer and re-run the corresponding smoke test.

## Platform References

- [Fly deployment and release commands](https://fly.io/docs/launch/deploy/)
- [Fly secrets](https://fly.io/docs/apps/secrets/)
- [Fly rollback guide](https://fly.io/docs/blueprints/rollback-guide/)
- [Vercel monorepo root directories](https://vercel.com/docs/monorepos)
- [Vercel environment variables](https://vercel.com/docs/environment-variables)
- [Vercel deployment promotion and rollback](https://vercel.com/docs/deployments/promoting-a-deployment)
- [Neon connection pooling guidance](https://neon.com/docs/connect/connection-pooling)
- [Cloudflare R2 S3 setup](https://developers.cloudflare.com/r2/get-started/s3/)
- [Cloudflare R2 with rclone](https://developers.cloudflare.com/r2/examples/rclone/)
- [Cloudflare R2 bucket locks](https://developers.cloudflare.com/r2/buckets/bucket-locks/)

## Still Requires Account-Owner Work

- Create every hosted service and confirm its final name and region.
- Configure the real domain, secrets, paid-provider approvals, and Stripe.
- Set up backup jobs, restore drills, Sentry, and external uptime alerts.
- Run the complete hosted English and French verification checklist.
