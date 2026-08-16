from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from pydantic import ValidationError

from app.config import settings
from app.schemas import StoryGenerationResult, StoryLanguage
from app.services.cost_tracking import (
    CostRecorder,
    NOOP_COST_RECORDER,
    Usage,
    record_cost_call,
)
from app.services.story_providers import (
    ClaudeStoryProvider,
    InvalidStoryProviderResponse,
    OllamaStoryProvider,
    StoryProviderRequest,
    StoryProviderRequestError,
)
from app.services.story_templates import (
    STORY_TEMPLATE_CATALOGS,
    AgeBandName,
)


@dataclass(frozen=True, slots=True)
class AgeBand:
    name: AgeBandName
    min_age: int
    max_age: int
    page_count: int


@dataclass(frozen=True, slots=True)
class StoryPrompt:
    system: str
    user: str


AGE_BANDS = (
    AgeBand(name="early", min_age=1, max_age=4, page_count=8),
    AgeBand(name="growing", min_age=5, max_age=7, page_count=10),
    AgeBand(name="independent", min_age=8, max_age=12, page_count=12),
)


_LANGUAGE_INSTRUCTIONS: dict[StoryLanguage, str] = {
    "en": "Write the story in English.",
    "fr": "Write the story in French.",
}

_VOCABULARY_GUIDANCE: dict[AgeBandName, str] = {
    "early": (
        "Use simple words and very short sentences. Favor repetition, "
        "concrete images, and one clear idea per page."
    ),
    "growing": (
        "Use simple everyday words and complete sentences. Include simple "
        "cause and effect while keeping one main idea per page."
    ),
    "independent": (
        "Use richer vocabulary and sentence structure, gentle plot turns, "
        "and age-appropriate insight into the character's feelings."
    ),
}


def build_story_prompt(
    *,
    child_name: str,
    age: int,
    age_band: AgeBand,
    interests: str,
    event_text: str,
    language: StoryLanguage,
) -> StoryPrompt:
    system = (
        "You write gentle, age-appropriate bedtime picture books for "
        "children. Warmly model good behavior around today's event without "
        "being preachy.\n\n"
        f"The child is {age} years old. "
        f"{_VOCABULARY_GUIDANCE[age_band.name]}\n\n"
        f"{_LANGUAGE_INSTRUCTIONS[language]}\n\n"
        f"Produce a title and exactly {age_band.page_count} page strings. "
        "Each page contains only 1 to 3 sentences of story narration. Do "
        "not include page numbers, labels, illustration directions, or "
        "bracketed notes."
    )
    user = (
        f"Child name: {child_name.strip()}\n"
        f"Interests: {interests.strip()}\n"
        f"Today's event: {event_text.strip()}"
    )
    return StoryPrompt(system=system, user=user)


def story_schema(page_count: int) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "pages": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": page_count,
                "maxItems": page_count,
            },
        },
        "required": ["title", "pages"],
    }


class StoryProvider(Protocol):
    def generate(
        self,
        *,
        child_name: str,
        age_band: AgeBand,
        interests: str,
        event_text: str,
        language: StoryLanguage,
    ) -> StoryGenerationResult: ...


class StubStoryProvider:
    def generate(
        self,
        *,
        child_name: str,
        age_band: AgeBand,
        interests: str,
        event_text: str,
        language: StoryLanguage,
    ) -> StoryGenerationResult:
        name = child_name.strip()
        event = event_text.strip()
        if not name:
            raise ValueError("Child name cannot be empty.")
        if not event:
            raise ValueError("Event text cannot be empty.")

        catalog = STORY_TEMPLATE_CATALOGS[language]
        template = catalog.age_bands[age_band.name]
        story_interests = interests.strip() or catalog.default_interests
        values = {
            "name": name,
            "event": event,
            "interests": story_interests,
        }
        title = template.title.format(**values)
        pages = [page.format(**values) for page in template.pages]
        return StoryGenerationResult(title=title, pages=pages)


_PROVIDERS: dict[str, StoryProvider] = {
    "stub": StubStoryProvider(),
}


def age_band_for(age: int) -> AgeBand:
    for age_band in AGE_BANDS:
        if age_band.min_age <= age <= age_band.max_age:
            return age_band
    raise ValueError("Child age must be between 1 and 12.")


def page_count_for_age(age: int) -> int:
    return age_band_for(age).page_count


def generate_story(
    *,
    child_name: str,
    age: int,
    interests: str,
    event_text: str,
    language: StoryLanguage,
    recorder: CostRecorder = NOOP_COST_RECORDER,
    before_provider_call: Callable[[], None] | None = None,
) -> StoryGenerationResult:
    if language not in STORY_TEMPLATE_CATALOGS:
        raise ValueError(f"Unsupported story language: {language}")

    provider_name = settings.story_provider.strip().lower()
    age_band = age_band_for(age)
    if provider_name == "claude":
        real_provider = ClaudeStoryProvider(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
        )
    elif provider_name == "ollama":
        real_provider = OllamaStoryProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
        )
    else:
        real_provider = None

    if real_provider is not None:
        prompt = build_story_prompt(
            child_name=child_name,
            age=age,
            age_band=age_band,
            interests=interests,
            event_text=event_text,
            language=language,
        )
        request = StoryProviderRequest(
            system=prompt.system,
            user=prompt.user,
            schema=story_schema(age_band.page_count),
        )
        for attempt in range(1, 3):
            if before_provider_call is not None:
                before_provider_call()
            try:
                response = real_provider.generate(request)
            except InvalidStoryProviderResponse as error:
                record_cost_call(
                    recorder,
                    stage="story_text",
                    provider=error.provider,
                    model=error.model,
                    attempt=attempt,
                    outcome="invalid_response",
                    usage=error.usage,
                )
                if attempt == 2:
                    raise RuntimeError(
                        "Story generation failed after retry: "
                        "invalid provider response."
                    ) from error
                continue
            except StoryProviderRequestError as error:
                record_cost_call(
                    recorder,
                    stage="story_text",
                    provider=error.provider,
                    model=error.model,
                    attempt=attempt,
                    outcome="provider_failure",
                    usage=error.usage,
                )
                if attempt == 2:
                    raise RuntimeError(
                        "Story generation failed after retry: "
                        "provider request."
                    ) from error
                continue
            try:
                result = StoryGenerationResult.model_validate(
                    response.payload
                )
                if len(result.pages) != age_band.page_count:
                    raise ValueError(
                        f"Expected {age_band.page_count} pages, "
                        f"got {len(result.pages)}."
                    )
            except (ValidationError, ValueError) as error:
                record_cost_call(
                    recorder,
                    stage="story_text",
                    provider=response.provider,
                    model=response.model,
                    attempt=attempt,
                    outcome="invalid_response",
                    usage=response.usage,
                )
                if attempt == 2:
                    raise RuntimeError(
                        "Story generation failed after retry: "
                        f"{type(error).__name__}."
                    ) from None
                continue
            record_cost_call(
                recorder,
                stage="story_text",
                provider=response.provider,
                model=response.model,
                attempt=attempt,
                outcome="succeeded",
                usage=response.usage,
            )
            return result
        raise RuntimeError("Story generation retry loop ended unexpectedly.")

    provider = _PROVIDERS.get(provider_name)
    if provider is None:
        raise ValueError(f"Unsupported story provider: {provider_name}")

    try:
        if before_provider_call is not None:
            before_provider_call()
        result = provider.generate(
            child_name=child_name,
            age_band=age_band,
            interests=interests,
            event_text=event_text,
            language=language,
        )
    except Exception:
        record_cost_call(
            recorder,
            stage="story_text",
            provider=provider_name,
            model=None,
            attempt=1,
            outcome="provider_failure",
            usage=None,
        )
        raise
    if not isinstance(result, StoryGenerationResult):
        record_cost_call(
            recorder,
            stage="story_text",
            provider=provider_name,
            model=None,
            attempt=1,
            outcome="invalid_response",
            usage=(Usage("request", 1),),
        )
        raise ValueError("Story provider returned an invalid result.")
    if len(result.pages) != age_band.page_count:
        record_cost_call(
            recorder,
            stage="story_text",
            provider=provider_name,
            model=None,
            attempt=1,
            outcome="invalid_response",
            usage=(Usage("request", 1),),
        )
        raise ValueError(
            f"Expected {age_band.page_count} pages, got {len(result.pages)}."
        )
    record_cost_call(
        recorder,
        stage="story_text",
        provider=provider_name,
        model=None,
        attempt=1,
        outcome="succeeded",
        usage=(Usage("request", 1),),
    )
    return result
