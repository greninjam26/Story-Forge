"""Offline story-generation evaluation harness.

The language check is a small regression heuristic, not a general-purpose
language detector. It catches empty, wrong-language, and obvious code-switched
responses without adding a paid or heavyweight language-detection dependency.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.schemas import StoryGenerationResult, StoryLanguage
from app.services import story_generation
from app.services.story_generation import page_count_for_age

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_LABEL_RE = re.compile(
    r"^\s*(?:page(?:\s+\d+|\s+de\s+titre)\s*:|"
    r"title(?:\s+page)?\s*:|titre\s*:|text(?:e)?\s*:|"
    r"illustration\s*:|\[[^\]]+\])",
    re.IGNORECASE,
)
_ENGLISH_MARKERS = frozenset(
    {
        "a", "and", "brave", "felt", "happy", "her", "he", "in", "is",
        "it", "little", "night", "of", "said", "star", "the", "to", "was",
        "with", "under",
    }
)
_FRENCH_MARKERS = frozenset(
    {
        "à", "a", "au", "avec", "dans", "de", "des", "du", "elle", "en",
        "est", "et", "étoile", "étoiles", "la", "le", "les", "petite",
        "pour", "sous", "une", "un", "était",
    }
)


@dataclass(frozen=True, slots=True)
class EvalCase:
    case_id: str
    child_name: str
    age: int
    interests: str
    event_text: str
    language: StoryLanguage


@dataclass(frozen=True, slots=True)
class MetricResult:
    page_count: bool
    language: bool
    labels: bool
    safety: bool = True

    @property
    def overall(self) -> bool:
        return self.page_count and self.language and self.labels and self.safety


@dataclass(frozen=True, slots=True)
class EvalRunResult:
    case_id: str
    language: StoryLanguage
    age: int
    run_number: int
    metrics: MetricResult | None
    error_type: str | None

    @property
    def overall(self) -> bool:
        return self.metrics is not None and self.metrics.overall


@dataclass(frozen=True, slots=True)
class EvalReport:
    runs: tuple[EvalRunResult, ...]

    @property
    def total(self) -> int:
        return len(self.runs)

    @property
    def overall(self) -> bool:
        return self.total > 0 and self.passed("overall") == self.total

    def passed(self, metric: str) -> int:
        if metric not in {"page_count", "language", "labels", "safety", "overall"}:
            raise ValueError(f"unknown metric: {metric}")
        return sum(
            int(
                run.overall
                if metric == "overall"
                else run.metrics is not None and getattr(run.metrics, metric)
            )
            for run in self.runs
        )


class StoryGenerator(Protocol):
    def __call__(
        self,
        *,
        child_name: str,
        age: int,
        interests: str,
        event_text: str,
        language: StoryLanguage,
    ) -> StoryGenerationResult: ...


DEFAULT_CASES: tuple[EvalCase, ...] = (
    EvalCase("en-young", "Mia", 3, "stars", "felt happy after playtime", "en"),
    EvalCase("en-middle", "Leo", 6, "dinosaurs", "learned a new game", "en"),
    EvalCase("en-older", "Nina", 10, "space", "helped a friend", "en"),
    EvalCase("fr-young", "Mia", 3, "étoiles", "a joué avec ses amis", "fr"),
    EvalCase("fr-middle", "Léo", 6, "dinosaures", "a appris un nouveau jeu", "fr"),
    EvalCase("fr-older", "Nina", 10, "espace", "a aidé une amie", "fr"),
)


def _default_generator(
    *,
    child_name: str,
    age: int,
    interests: str,
    event_text: str,
    language: StoryLanguage,
) -> StoryGenerationResult:
    return story_generation.generate_story(
        child_name=child_name,
        age=age,
        interests=interests,
        event_text=event_text,
        language=language,
    )


def check_page_count(
    story: StoryGenerationResult,
    *,
    age: int,
) -> bool:
    return len(story.pages) == page_count_for_age(age)


def _language_score(text: str, markers: frozenset[str]) -> int:
    words = _WORD_RE.findall(text.lower())
    return sum(word in markers for word in words)


def check_language(
    story: StoryGenerationResult,
    *,
    language: StoryLanguage,
) -> bool:
    text = " ".join((story.title, *story.pages))
    requested_markers = (
        _ENGLISH_MARKERS if language == "en" else _FRENCH_MARKERS
    )
    other_markers = (
        _FRENCH_MARKERS if language == "en" else _ENGLISH_MARKERS
    )
    requested = _language_score(text, requested_markers)
    other = _language_score(text, other_markers)
    return requested > 0 and requested > other


def check_no_label_leaks(story: StoryGenerationResult) -> bool:
    return not any(
        _LABEL_RE.search(text)
        for text in (story.title, *story.pages)
    )


def evaluate_story(
    story: StoryGenerationResult,
    *,
    age: int,
    language: StoryLanguage,
) -> MetricResult:
    from app.services.story_safety import check_generated_story

    safety_result = check_generated_story(
        title=story.title,
        page_texts=story.pages,
    )
    return MetricResult(
        page_count=check_page_count(story, age=age),
        language=check_language(story, language=language),
        labels=check_no_label_leaks(story),
        safety=safety_result.is_safe,
    )


def run_evaluation(
    cases: Sequence[EvalCase],
    *,
    runs: int,
    generator: StoryGenerator = _default_generator,
) -> EvalReport:
    if runs < 1:
        raise ValueError("runs must be at least 1")

    results: list[EvalRunResult] = []
    for case in cases:
        for run_number in range(1, runs + 1):
            try:
                story = generator(
                    child_name=case.child_name,
                    age=case.age,
                    interests=case.interests,
                    event_text=case.event_text,
                    language=case.language,
                )
                metrics = evaluate_story(
                    story,
                    age=case.age,
                    language=case.language,
                )
                error_type = None
            except Exception as error:
                metrics = None
                error_type = type(error).__name__
            results.append(
                EvalRunResult(
                    case_id=case.case_id,
                    language=case.language,
                    age=case.age,
                    run_number=run_number,
                    metrics=metrics,
                    error_type=error_type,
                )
            )
    return EvalReport(runs=tuple(results))


def format_report(report: EvalReport) -> str:
    lines = [
        "case_id language age run page_count language labels safety overall "
        "error"
    ]
    for run in report.runs:
        if run.metrics is None:
            lines.append(
                f"{run.case_id} {run.language} {run.age} {run.run_number} "
                f"FAIL FAIL FAIL FAIL FAIL {run.error_type}"
            )
            continue
        metrics = run.metrics
        values = (
            metrics.page_count,
            metrics.language,
            metrics.labels,
            metrics.safety,
            metrics.overall,
        )
        lines.append(
            f"{run.case_id} {run.language} {run.age} {run.run_number} "
            + " ".join("PASS" if value else "FAIL" for value in values)
            + " -"
        )

    lines.append("")
    for metric in ("page_count", "language", "labels", "safety", "overall"):
        passed = report.passed(metric)
        percentage = passed / report.total * 100 if report.total else 0
        lines.append(f"{metric}: {passed}/{report.total} ({percentage:.1f}%)")
    return "\n".join(lines)


def _positive_runs(value: str) -> int:
    try:
        runs = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("runs must be an integer") from error
    if runs < 1:
        raise argparse.ArgumentTypeError("runs must be at least 1")
    return runs


def main(
    argv: Sequence[str] | None = None,
    *,
    generator: StoryGenerator = _default_generator,
) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate story generation quality"
    )
    parser.add_argument(
        "--runs",
        type=_positive_runs,
        default=3,
        help="number of runs per fixed case (default: 3)",
    )
    parser.add_argument(
        "--provider",
        choices=("ollama", "stub"),
        default="ollama",
        help="story provider to use (default: ollama)",
    )
    args = parser.parse_args(argv)

    previous_provider = story_generation.settings.story_provider
    try:
        story_generation.settings.story_provider = args.provider
        report = run_evaluation(
            DEFAULT_CASES,
            runs=args.runs,
            generator=generator,
        )
        print(format_report(report))
        return 0 if report.overall else 1
    finally:
        story_generation.settings.story_provider = previous_provider


if __name__ == "__main__":
    raise SystemExit(main())
