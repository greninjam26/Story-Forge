from dataclasses import dataclass
from typing import Literal, Protocol

from app.config import settings
from app.schemas import StoryGenerationResult, StoryLanguage


AgeBandName = Literal["early", "growing", "independent"]


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


_TITLES: dict[StoryLanguage, dict[AgeBandName, str]] = {
    "en": {
        "early": "{name}'s Brave Little Day",
        "growing": "{name} and the Gentle Star",
        "independent": "{name} and the Courage to Try",
    },
    "fr": {
        "early": "La petite journée courageuse de {name}",
        "growing": "{name} et la douce étoile",
        "independent": "{name} et le courage d'essayer",
    },
}


_PAGES: dict[StoryLanguage, dict[AgeBandName, tuple[str, ...]]] = {
    "en": {
        "early": (
            "Today, something happened to {name}: {event}",
            "{name} had a big feeling.",
            "{name} took one slow breath.",
            "A little star stayed nearby.",
            '"Try again," whispered the star.',
            "{name} tried one small step.",
            "The hard feeling became smaller.",
            "{name} felt safe, proud, and ready for sleep.",
        ),
        "growing": (
            "Today, {name} had an important moment: {event}",
            "At first, {name} was not sure what to do.",
            "A friendly guide who loved {interests} appeared beside {name}.",
            "The guide reminded {name} that every feeling was allowed.",
            "{name} paused, breathed slowly, and chose a kind next step.",
            "The first try was difficult, but {name} noticed what helped.",
            "With a little patience, {name} tried again.",
            "This time, the moment began to feel easier.",
            "{name} felt proud of choosing courage and kindness.",
            "Under the quiet stars, {name} carried that lesson into a peaceful dream.",
        ),
        "independent": (
            "Today brought {name} an unexpected challenge: {event}",
            "For a moment, {name} wondered whether the feeling would ever pass.",
            "Then a thoughtful guide who shared {name}'s love of {interests} arrived.",
            "The guide listened carefully without trying to make the feeling disappear.",
            "Together, they considered several choices and what each one might change.",
            "{name} chose the kindest next step, even though it required courage.",
            "The first attempt was imperfect, and that turned out to be useful.",
            "By noticing what went wrong, {name} discovered a better way forward.",
            "A second attempt brought a small success and a much larger sense of hope.",
            "{name} understood that courage can grow through patient, thoughtful practice.",
            "The challenge had not vanished, but it no longer seemed impossible.",
            "That night, {name} rested peacefully, proud of the wisdom gained along the way.",
        ),
    },
    "fr": {
        "early": (
            "Aujourd'hui, quelque chose est arrivé à {name} : {event}",
            "{name} a ressenti une grande émotion.",
            "{name} a respiré tout doucement.",
            "Une petite étoile est restée près de {name}.",
            '« Essaie encore », a murmuré l\'étoile.',
            "{name} a fait un petit pas.",
            "L'émotion difficile est devenue plus petite.",
            "{name} s'est senti en sécurité, fier et prêt à dormir.",
        ),
        "growing": (
            "Aujourd'hui, {name} a vécu un moment important : {event}",
            "Au début, {name} ne savait pas vraiment quoi faire.",
            "Un guide qui aimait {interests} est apparu près de {name}.",
            "Le guide a rappelé à {name} que chaque émotion avait sa place.",
            "{name} s'est arrêté, a respiré lentement et a choisi une action gentille.",
            "Le premier essai était difficile, mais {name} a remarqué ce qui aidait.",
            "Avec un peu de patience, {name} a essayé une nouvelle fois.",
            "Cette fois, le moment a commencé à devenir plus facile.",
            "{name} était fier d'avoir choisi le courage et la gentillesse.",
            "Sous les étoiles tranquilles, {name} a emporté cette leçon dans un rêve paisible.",
        ),
        "independent": (
            "Aujourd'hui a présenté un défi inattendu à {name} : {event}",
            "Pendant un instant, {name} s'est demandé si cette émotion finirait par passer.",
            "Puis un guide attentionné qui partageait l'intérêt de {name} pour {interests} est arrivé.",
            "Le guide a écouté avec soin, sans chercher à faire disparaître l'émotion.",
            "Ensemble, ils ont imaginé plusieurs choix et les changements que chacun pouvait apporter.",
            "{name} a choisi l'étape la plus bienveillante, même si elle demandait du courage.",
            "Le premier essai était imparfait, et cela s'est révélé très utile.",
            "En observant ce qui avait mal fonctionné, {name} a découvert une meilleure approche.",
            "Un deuxième essai a apporté un petit succès et un espoir beaucoup plus grand.",
            "{name} a compris que le courage grandit grâce à une pratique patiente et réfléchie.",
            "Le défi n'avait pas disparu, mais il ne semblait désormais plus impossible.",
            "Ce soir-là, {name} s'est reposé paisiblement, fier de la sagesse acquise en chemin.",
        ),
    },
}


_DEFAULT_INTERESTS: dict[StoryLanguage, str] = {
    "en": "the stars",
    "fr": "les étoiles",
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

        story_interests = interests.strip() or _DEFAULT_INTERESTS[language]
        values = {
            "name": name,
            "event": event,
            "interests": story_interests,
        }
        title = _TITLES[language][age_band.name].format(**values)
        pages = [
            page.format(**values) for page in _PAGES[language][age_band.name]
        ]
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
) -> StoryGenerationResult:
    if language not in _TITLES:
        raise ValueError(f"Unsupported story language: {language}")

    provider_name = settings.story_provider.strip().lower()
    provider = _PROVIDERS.get(provider_name)
    if provider is None:
        raise ValueError(f"Unsupported story provider: {provider_name}")

    age_band = age_band_for(age)
    result = provider.generate(
        child_name=child_name,
        age_band=age_band,
        interests=interests,
        event_text=event_text,
        language=language,
    )
    if len(result.pages) != age_band.page_count:
        raise ValueError(
            f"Expected {age_band.page_count} pages, got {len(result.pages)}."
        )
    return result
