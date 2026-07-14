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
Object storage     generated images and audio
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

Each capability defaults to a deterministic `stub` so local development and tests can run without network access or paid keys. The rest of the application calls one stable service interface and does not depend on a particular provider.

## Structured Story Output

Story generation returns structured data:

```text
{
  title: string,
  pages: string[]
}
```

The child's age determines page count and language complexity. Provider output is validated in Python and retried once when malformed.

## Languages

Story Forge supports English (`en`) by default and French (`fr`) as a second language.

UI locale and story language remain independent. A parent may use the English interface while generating a French story, or use the French interface while generating an English story.

## Data And Storage

```text
Parent --< Child --< Story --< StoryPage
  locale     language    language      page_number
  plan       name        event_text    text
             age         title         image_url
             interests   status        audio_url
```

Relational data lives in sqlite locally and Postgres in production. Generated images and narration live in object storage, with stable URLs stored on each `StoryPage`.

## Safety And Testing

Safety checks apply to both parent input and generated story text. Rejected or flagged stories remain parent-visible only, and parent approval is required before a story becomes child-facing.

Tests remain fast, offline, and deterministic. Pipeline tests use stub providers, real provider clients are mocked, and paid APIs are never called during tests.
