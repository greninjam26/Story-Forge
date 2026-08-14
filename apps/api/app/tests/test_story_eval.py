import pytest

from app.schemas import StoryGenerationResult, StoryLanguage
from app.services import story_generation

from evals.story_eval import (
    DEFAULT_CASES,
    EvalCase,
    EvalReport,
    EvalRunResult,
    MetricResult,
    check_language,
    check_no_label_leaks,
    check_page_count,
    evaluate_story,
    format_report,
    main,
    run_evaluation,
)


@pytest.fixture(autouse=True)
def use_stub_story_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(story_generation.settings, "story_provider", "stub")


def _story(title: str, pages: list[str]) -> StoryGenerationResult:
    return StoryGenerationResult(
        title=title,
        pages=pages,
    )


def _passing_story(
    *,
    age: int,
    language: StoryLanguage,
) -> StoryGenerationResult:
    page_count = {3: 8, 6: 10, 10: 12}[age]
    if language == "fr":
        return _story(
            "La nuit de Mia",
            ["Mia était heureuse sous les étoiles."] * page_count,
        )
    return _story(
        "Mia's Night",
        ["Mia felt happy under the stars."] * page_count,
    )


@pytest.mark.parametrize(
    ("age", "page_count"),
    [(3, 8), (6, 10), (10, 12)],
)
def test_page_count_matches_age_band(age: int, page_count: int) -> None:
    assert check_page_count(_story("A title", ["page"] * page_count), age=age)
    assert not check_page_count(
        _story("A title", ["page"] * (page_count - 1)),
        age=age,
    )


@pytest.mark.parametrize(
    ("language", "title", "pages"),
    [
        ("en", "Mia's Night", ["Mia felt happy under the stars."] * 8),
        ("fr", "La nuit de Mia", ["Mia était heureuse sous les étoiles."] * 8),
    ],
)
def test_language_matches_requested_language(
    language: str,
    title: str,
    pages: list[str],
) -> None:
    assert check_language(_story(title, pages), language=language)


def test_language_rejects_code_switching_and_empty_evidence() -> None:
    assert not check_language(
        _story(
            "Mia's nuit",
            ["Mia et Leo played together dans le jardin."] * 8,
        ),
        language="en",
    )
    assert not check_language(_story("Mia", ["Mia"] * 8), language="fr")


def test_language_rejects_mostly_english_story_requested_as_french() -> None:
    assert not check_language(
        _story("Mia et Leo", ["Mia can run fast."] * 8),
        language="fr",
    )


def test_language_accepts_marker_light_french_story() -> None:
    assert check_language(
        _story("Bonjour maman", ["Mia court rapidement."] * 8),
        language="fr",
    )


def test_language_rejects_sparse_wrong_language_page() -> None:
    french_pages = ["Mia était heureuse sous les étoiles."] * 7
    story = _story(
        "La nuit de Mia",
        [*french_pages, "Mia loves dogs and cats."],
    )

    assert not check_language(story, language="fr")


@pytest.mark.parametrize(
    ("language", "title", "pages"),
    [
        ("fr", "Bonjour maman", ["Mia smiled."] * 8),
        ("en", "The night", ["Mia sourit."] * 8),
    ],
)
def test_language_rejects_body_without_requested_language_evidence(
    language: str,
    title: str,
    pages: list[str],
) -> None:
    assert not check_language(_story(title, pages), language=language)


def test_language_rejects_page_with_multiple_competing_markers() -> None:
    pages = [
        "Mia est très heureuse dans la nuit avec sa maman et une petite "
        "étoile, and she was happy."
    ] * 8

    assert not check_language(_story("La nuit de Mia", pages), language="fr")


@pytest.mark.parametrize(
    ("language", "title", "pages"),
    [
        (
            "en",
            "The night",
            ["The little star was happy."] * 7
            + ["Mia saw a beautiful rainbow."],
        ),
        (
            "fr",
            "La nuit",
            ["Mia était heureuse sous les étoiles."] * 7
            + ["Mia fait du shopping."],
        ),
    ],
)
def test_language_ignores_cross_language_character_fragments(
    language: str,
    title: str,
    pages: list[str],
) -> None:
    assert check_language(_story(title, pages), language=language)


@pytest.mark.parametrize(
    "text",
    [
        "Page 1: story",
        "Title: story",
        "Title Page: story",
        "Text: story",
        "Illustration: a moon",
        "[whisper softly]",
        "Titre : une histoire",
        "Page de titre : une histoire",
        "Texte : une histoire",
        "A gentle story. Page: The moon appeared.",
        "A gentle story. Page 2: The moon appeared.",
        "A gentle story. [Illustration: a moon]",
    ],
)
def test_structural_labels_are_rejected(text: str) -> None:
    assert not check_no_label_leaks(_story(text, ["A gentle story."]))
    assert not check_no_label_leaks(_story("A gentle story.", [text]))


@pytest.mark.parametrize(
    "text",
    [
        "A page of stars",
        "The page turned softly.",
        "Her subtitle: Moonlight",
    ],
)
def test_structural_words_without_label_syntax_are_allowed(text: str) -> None:
    assert check_no_label_leaks(_story(text, [text]))


@pytest.mark.parametrize(
    ("language", "child_name", "event_text"),
    [
        ("en", "Mia", "felt happy after playtime"),
        ("fr", "Mia", "a joué avec ses amis"),
    ],
)
def test_actual_stub_stories_match_expected_metrics(
    language: str,
    child_name: str,
    event_text: str,
) -> None:
    story: StoryGenerationResult = story_generation.generate_story(
        child_name=child_name,
        age=6,
        interests="stars",
        event_text=event_text,
        language=language,
    )
    assert check_page_count(story, age=6)
    assert check_language(story, language=language)


@pytest.mark.parametrize(
    ("title", "pages", "safe"),
    [
        ("A weapon story", ["A gentle page."] * 8, False),
        ("A gentle story", ["Une histoire avec du sang."] * 8, False),
        ("A gentle story", ["A kind bedtime adventure."] * 8, True),
    ],
)
def test_evaluate_story_includes_existing_safety_policy(
    title: str,
    pages: list[str],
    safe: bool,
) -> None:
    result = evaluate_story(
        _story(title, pages),
        age=3,
        language="en",
    )
    assert result.safety is safe


def test_default_cases_cover_all_age_bands_and_languages() -> None:
    assert {(case.age, case.language) for case in DEFAULT_CASES} == {
        (3, "en"), (6, "en"), (10, "en"),
        (3, "fr"), (6, "fr"), (10, "fr"),
    }


def test_runner_passes_case_fields_and_repeats_each_case() -> None:
    calls: list[dict[str, object]] = []

    def generator(**kwargs: object) -> StoryGenerationResult:
        calls.append(kwargs)
        return _story("A gentle night", ["The little star said hello."] * 8)

    cases = (
        EvalCase("case-a", "Mia", 3, "stars", "felt happy", "en"),
    )
    report = run_evaluation(cases, runs=3, generator=generator)

    assert report.total == 3
    assert calls == [
        {
            "child_name": "Mia",
            "age": 3,
            "interests": "stars",
            "event_text": "felt happy",
            "language": "en",
        }
    ] * 3


def test_report_aggregates_each_metric_independently() -> None:
    report = EvalReport(
        runs=(
            EvalRunResult(
                "one", "en", 3, 1, MetricResult(True, True, False, True), None
            ),
            EvalRunResult(
                "two", "en", 3, 1, MetricResult(True, False, True, True), None
            ),
            EvalRunResult("three", "en", 3, 1, None, "RuntimeError"),
        )
    )
    assert report.total == 3
    assert report.passed("page_count") == 2
    assert report.passed("language") == 1
    assert report.passed("labels") == 1
    assert report.passed("safety") == 2
    assert report.passed("overall") == 0


def test_generation_failures_are_sanitized_and_do_not_stop_later_cases() -> None:
    calls = 0

    def generator(**_: object) -> StoryGenerationResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("private child story content")
        return _story("A gentle night", ["The little star said hello."] * 8)

    cases = (
        EvalCase("broken", "Mia", 3, "stars", "felt happy", "en"),
        EvalCase("healthy", "Leo", 3, "stars", "felt happy", "en"),
    )
    report = run_evaluation(cases, runs=1, generator=generator)

    assert report.runs[0].metrics is None
    assert report.runs[0].error_type == "ValueError"
    assert "private" not in repr(report.runs[0])
    assert report.runs[1].overall


def test_runner_rejects_non_positive_runs_before_generation() -> None:
    def generator(**_: object) -> StoryGenerationResult:
        raise AssertionError("generator should not run")

    with pytest.raises(ValueError, match="runs must be at least 1"):
        run_evaluation(DEFAULT_CASES[:1], runs=0, generator=generator)


@pytest.mark.parametrize(
    ("failed_metric", "story"),
    [
        (
            "page_count",
            _story("The gentle night", ["The little star was kind."] * 7),
        ),
        (
            "language",
            _story("La douce nuit", ["La petite étoile était gentille."] * 8),
        ),
        (
            "labels",
            _story("Title: The gentle night", ["The little star was kind."] * 8),
        ),
        (
            "safety",
            _story("The weapon at night", ["The little star was kind."] * 8),
        ),
    ],
)
def test_runner_gate_detects_each_failed_metric(
    failed_metric: str,
    story: StoryGenerationResult,
) -> None:
    def generator(**_: object) -> StoryGenerationResult:
        return story

    report = run_evaluation(
        (EvalCase("case-a", "Mia", 3, "stars", "felt happy", "en"),),
        runs=1,
        generator=generator,
    )

    for metric in ("page_count", "language", "labels", "safety"):
        assert report.passed(metric) == int(metric != failed_metric)
    assert report.passed("overall") == 0
    assert not report.overall


def test_format_report_has_stable_rows_and_metric_footers() -> None:
    report = EvalReport(
        runs=(
            EvalRunResult(
                "case-a", "en", 3, 1, MetricResult(True, True, True, True), None
            ),
            EvalRunResult("case-b", "fr", 6, 1, None, "RuntimeError"),
        )
    )

    output = format_report(report)

    assert (
        "case_id language age run page_count language labels safety overall "
        "error"
    ) in output
    assert "case-a en 3 1 PASS PASS PASS PASS PASS -" in output
    assert "case-b fr 6 1 FAIL FAIL FAIL FAIL FAIL RuntimeError" in output
    assert "page_count: 1/2 (50.0%)" in output
    assert "overall: 1/2 (50.0%)" in output
    assert "private" not in output


def test_cli_accepts_stub_and_restores_provider(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        story_generation.settings,
        "story_provider",
        "ollama",
    )

    def generator(
        *, age: int, language: str, **_: object
    ) -> StoryGenerationResult:
        if language == "fr":
            return _story(
                "La nuit de Mia",
                ["Mia était heureuse sous les étoiles."] *
                story_generation.page_count_for_age(age),
            )
        return _story(
            "Mia's Night",
            ["Mia felt happy under the stars."] *
            story_generation.page_count_for_age(age),
        )

    exit_code = main(
        ["--provider", "stub", "--runs", "1"],
        generator=generator,
    )

    assert exit_code == 0
    assert story_generation.settings.story_provider == "ollama"
    assert "overall: 6/6 (100.0%)" in capsys.readouterr().out


def test_cli_defaults_to_three_runs_per_case(capsys) -> None:
    calls = 0

    def generator(
        *,
        age: int,
        language: StoryLanguage,
        **_: object,
    ) -> StoryGenerationResult:
        nonlocal calls
        calls += 1
        return _passing_story(age=age, language=language)

    exit_code = main(["--provider", "stub"], generator=generator)

    assert exit_code == 0
    assert calls == 18
    assert "overall: 18/18 (100.0%)" in capsys.readouterr().out


def test_cli_returns_failure_when_a_metric_fails(capsys) -> None:
    def generator(
        *,
        age: int,
        language: StoryLanguage,
        **_: object,
    ) -> StoryGenerationResult:
        story = _passing_story(age=age, language=language)
        return story.model_copy(update={"pages": story.pages[:-1]})

    exit_code = main(
        ["--provider", "stub", "--runs", "1"],
        generator=generator,
    )

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "page_count: 0/6 (0.0%)" in output
    assert "overall: 0/6 (0.0%)" in output


def test_cli_restores_provider_after_generation_failure(
    capsys,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        story_generation.settings,
        "story_provider",
        "claude",
    )

    def generator(**_: object) -> StoryGenerationResult:
        raise RuntimeError("private event text")

    exit_code = main(
        ["--provider", "stub", "--runs", "1"],
        generator=generator,
    )

    assert exit_code == 1
    assert story_generation.settings.story_provider == "claude"
    output = capsys.readouterr().out
    assert "RuntimeError" in output
    assert "private event text" not in output


@pytest.mark.parametrize("runs", ["0", "not-an-integer"])
def test_cli_rejects_invalid_runs(runs: str) -> None:
    with pytest.raises(SystemExit):
        main(["--runs", runs])


def test_deterministic_stub_gate_never_contacts_live_providers(
    monkeypatch,
) -> None:
    monkeypatch.setattr(story_generation.settings, "story_provider", "stub")

    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("live story provider access is forbidden")

    monkeypatch.setattr(
        story_generation,
        "ClaudeStoryProvider",
        forbidden,
    )
    monkeypatch.setattr(
        story_generation,
        "OllamaStoryProvider",
        forbidden,
    )

    report = run_evaluation(DEFAULT_CASES, runs=1)

    assert report.total == 6
    assert report.passed("page_count") == report.total
    assert report.passed("language") == report.total
    assert report.passed("labels") == report.total
    assert report.passed("safety") == report.total
    assert report.passed("overall") == report.total


def test_default_runner_rejects_paid_provider_before_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(story_generation.settings, "story_provider", "claude")

    def forbidden(**_: object) -> StoryGenerationResult:
        raise AssertionError("paid story provider access is forbidden")

    monkeypatch.setattr(story_generation, "generate_story", forbidden)

    report = run_evaluation(DEFAULT_CASES[:1], runs=1)

    assert report.runs[0].error_type == "ValueError"
