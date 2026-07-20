from dataclasses import dataclass
from typing import Literal, Mapping

from app.schemas import StoryLanguage


AgeBandName = Literal["early", "growing", "independent"]


@dataclass(frozen=True, slots=True)
class StoryTemplate:
    title: str
    pages: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StoryTemplateCatalog:
    default_interests: str
    age_bands: Mapping[AgeBandName, StoryTemplate]


STORY_TEMPLATE_CATALOGS: Mapping[StoryLanguage, StoryTemplateCatalog] = {
    "en": StoryTemplateCatalog(
        default_interests="the stars",
        age_bands={
            "early": StoryTemplate(
                title="{name}'s Brave Little Day",
                pages=(
                    "Today, something happened to {name}: {event}",
                    "{name} had a big feeling.",
                    "{name} took one slow breath.",
                    "A little star stayed nearby.",
                    '"Try again," whispered the star.',
                    "{name} tried one small step.",
                    "The hard feeling became smaller.",
                    "{name} felt safe, proud, and ready for sleep.",
                ),
            ),
            "growing": StoryTemplate(
                title="{name} and the Gentle Star",
                pages=(
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
            ),
            "independent": StoryTemplate(
                title="{name} and the Courage to Try",
                pages=(
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
                    "That night, {name} rested peacefully, proud of the wisdom "
                    "gained along the way.",
                ),
            ),
        },
    ),
    "fr": StoryTemplateCatalog(
        default_interests="les étoiles",
        age_bands={
            "early": StoryTemplate(
                title="La petite journée courageuse de {name}",
                pages=(
                    "Aujourd'hui, quelque chose est arrivé à {name} : {event}",
                    "{name} a ressenti une grande émotion.",
                    "{name} a respiré tout doucement.",
                    "Une petite étoile est restée près de {name}.",
                    "« Essaie encore », a murmuré l'étoile.",
                    "{name} a fait un petit pas.",
                    "L'émotion difficile est devenue plus petite.",
                    "{name} a retrouvé la sécurité, la fierté et le calme avant de dormir.",
                ),
            ),
            "growing": StoryTemplate(
                title="{name} et la douce étoile",
                pages=(
                    "Aujourd'hui, {name} a vécu un moment important : {event}",
                    "Au début, {name} ne savait pas vraiment quoi faire.",
                    "Un guide qui aimait {interests} est apparu près de {name}.",
                    "Le guide a rappelé à {name} que chaque émotion avait sa place.",
                    "{name} a fait une pause, a respiré lentement et a choisi "
                    "une action gentille.",
                    "Le premier essai était difficile, mais {name} a remarqué ce qui aidait.",
                    "Avec un peu de patience, {name} a essayé une nouvelle fois.",
                    "Cette fois, le moment a commencé à devenir plus facile.",
                    "La fierté de {name} a grandi après ce choix courageux et bienveillant.",
                    "Sous les étoiles tranquilles, {name} a emporté cette leçon "
                    "dans un rêve paisible.",
                ),
            ),
            "independent": StoryTemplate(
                title="{name} et le courage d'essayer",
                pages=(
                    "Aujourd'hui a présenté un défi inattendu à {name} : {event}",
                    "Pendant un instant, {name} s'est demandé si cette émotion "
                    "finirait par passer.",
                    "Puis un guide attentionné qui partageait l'intérêt de {name} "
                    "pour {interests} est arrivé.",
                    "Le guide a écouté avec soin, sans chercher à faire "
                    "disparaître l'émotion.",
                    "Ensemble, ils ont imaginé plusieurs choix et les changements "
                    "que chacun pouvait apporter.",
                    "{name} a choisi l'étape la plus bienveillante, même si elle "
                    "demandait du courage.",
                    "Le premier essai était imparfait, et cela s'est révélé très utile.",
                    "En observant ce qui avait mal fonctionné, {name} a découvert "
                    "une meilleure approche.",
                    "Un deuxième essai a apporté un petit succès et un espoir "
                    "beaucoup plus grand.",
                    "{name} a compris que le courage grandit grâce à une pratique "
                    "patiente et réfléchie.",
                    "Le défi n'avait pas disparu, mais il ne semblait désormais plus impossible.",
                    "Ce soir-là, le sommeil est venu paisiblement, avec la fierté "
                    "du chemin parcouru.",
                ),
            ),
        },
    ),
}
