from dataclasses import dataclass
from typing import Protocol

from app.config import settings
from app.schemas import StoryGenerationResult, StoryLanguage
from app.services.cost_tracking import (
    CostRecorder,
    NOOP_COST_RECORDER,
    Usage,
    record_cost_call,
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


AGE_BANDS = (
    AgeBand(name="early", min_age=1, max_age=4, page_count=8),
    AgeBand(name="growing", min_age=5, max_age=7, page_count=10),
    AgeBand(name="independent", min_age=8, max_age=12, page_count=12),
)


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
) -> StoryGenerationResult:
    if language not in STORY_TEMPLATE_CATALOGS:
        raise ValueError(f"Unsupported story language: {language}")

    provider_name = settings.story_provider.strip().lower()
    provider = _PROVIDERS.get(provider_name)
    if provider is None:
        raise ValueError(f"Unsupported story provider: {provider_name}")

    age_band = age_band_for(age)
    try:
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
