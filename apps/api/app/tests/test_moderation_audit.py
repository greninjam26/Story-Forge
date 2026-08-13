from dataclasses import replace

import pytest

from app.models import (
    Child,
    ModerationRecord,
    Parent,
    Story,
    StoryStatus,
)
from app.services import moderation_audit
from app.services.safety import SafetyDecision


def _story(db, suffix: str = "") -> Story:
    parent = Parent(email=f"audit{suffix}@example.com")
    child = Child(
        parent=parent,
        name="Camille",
        age=7,
        interests="stars",
        language="en",
    )
    story = Story(
        child=child,
        event_text="Camille felt nervous about school.",
        title="Generated title",
        language="en",
        status=StoryStatus.REJECTED,
        failure_reason="safety_generated_page_2_blocked",
        safety_reason="violence",
    )
    db.add(story)
    db.commit()
    return story


def _openai_decision(**overrides: object) -> SafetyDecision:
    decision = SafetyDecision(
        is_safe=False,
        reason_code="violence",
        provider="openai",
        provider_model="omni-moderation-test",
        provider_request_id="req_test_123",
        flagged_item_kind="page",
        flagged_page_number=2,
        flagged_text="Only this generated page is retained.",
        categories=("violence", "new-category"),
        category_scores={"violence": 0.93, "new-category": 0.81},
    )
    return replace(decision, **overrides)


def test_add_record_builds_openai_page_audit_without_committing(
    db_session_factory,
) -> None:
    with db_session_factory() as db:
        story = _story(db)

        record = moderation_audit.add_record(
            db,
            story,
            _openai_decision(),
        )
        db.flush()

        assert record.story_id == story.id
        assert record.provider == "openai"
        assert record.model == "omni-moderation-test"
        assert record.provider_request_id == "req_test_123"
        assert record.flagged_item_kind == "page"
        assert record.flagged_page_number == 2
        assert record.flagged_text == (
            "Only this generated page is retained."
        )
        assert record.categories == ["violence", "new-category"]
        assert record.category_scores == {
            "violence": 0.93,
            "new-category": 0.81,
        }
        assert record.review_status == "pending"
        assert record.reviewed_at is None
        record_id = record.id
        db.rollback()

    with db_session_factory() as db:
        assert db.get(ModerationRecord, record_id) is None


def test_add_record_builds_keyword_title_audit(
    db_session_factory,
) -> None:
    with db_session_factory() as db:
        story = _story(db)
        story.safety_reason = "self_harm"
        decision = SafetyDecision(
            is_safe=False,
            reason_code="self_harm",
            provider="keyword",
            flagged_item_kind="title",
            flagged_text="Rejected title",
            categories=("self_harm",),
        )

        record = moderation_audit.add_record(db, story, decision)

        assert record.model is None
        assert record.provider_request_id is None
        assert record.flagged_item_kind == "title"
        assert record.flagged_page_number is None
        assert record.flagged_text == "Rejected title"
        assert record.categories == ["self_harm"]
        assert record.category_scores == {}


def test_add_record_accepts_uncategorized_openai_flag(
    db_session_factory,
) -> None:
    with db_session_factory() as db:
        story = _story(db)
        story.safety_reason = "unsafe_content"

        record = moderation_audit.add_record(
            db,
            story,
            _openai_decision(
                reason_code="unsafe_content",
                categories=(
                    "storyforge:provider_flagged_uncategorized",
                ),
                category_scores={},
            ),
        )

        assert record.categories == [
            "storyforge:provider_flagged_uncategorized"
        ]
        assert record.category_scores == {}


@pytest.mark.parametrize(
    "decision",
    [
        SafetyDecision(is_safe=True),
        _openai_decision(reason_code=None),
        _openai_decision(provider=None),
        _openai_decision(provider_model=None),
        _openai_decision(provider_request_id=None),
        _openai_decision(flagged_item_kind=None),
        _openai_decision(
            flagged_item_kind="title",
            flagged_page_number=1,
        ),
        _openai_decision(flagged_page_number=None),
        _openai_decision(flagged_page_number=0),
        _openai_decision(flagged_text=None),
        _openai_decision(categories=()),
        _openai_decision(category_scores={}),
        _openai_decision(category_scores={"not-retained": 0.5}),
        _openai_decision(
            reason_code="unsafe_content",
            categories=(
                "storyforge:provider_flagged_uncategorized",
            ),
            category_scores={
                "storyforge:provider_flagged_uncategorized": 0.5,
            },
        ),
        _openai_decision(
            reason_code="unsafe_content",
            categories=(
                "storyforge:provider_flagged_uncategorized",
                "violence",
            ),
            category_scores={
                "storyforge:provider_flagged_uncategorized": 0.5,
                "violence": 0.9,
            },
        ),
        SafetyDecision(
            is_safe=False,
            reason_code="self_harm",
            provider="keyword",
            flagged_item_kind="title",
            flagged_text="Rejected title",
            categories=("self_harm", "violence"),
        ),
        SafetyDecision(
            is_safe=False,
            reason_code="self_harm",
            provider="keyword",
            provider_model="not-allowed",
            flagged_item_kind="title",
            flagged_text="Rejected title",
            categories=("self_harm",),
        ),
        SafetyDecision(
            is_safe=False,
            reason_code="self_harm",
            provider="keyword",
            flagged_item_kind="title",
            flagged_text="Rejected title",
            categories=("self_harm",),
            category_scores={"self_harm": 0.9},
        ),
    ],
)
def test_add_record_rejects_incomplete_or_inconsistent_decisions(
    db_session_factory,
    decision: SafetyDecision,
) -> None:
    with db_session_factory() as db:
        story = _story(db)
        story.safety_reason = decision.reason_code

        with pytest.raises(ValueError, match="invalid safety decision"):
            moderation_audit.add_record(db, story, decision)


@pytest.mark.parametrize(
    ("status", "safety_reason"),
    [
        (StoryStatus.PENDING_REVIEW, "violence"),
        (StoryStatus.REJECTED, None),
        (StoryStatus.REJECTED, "self_harm"),
    ],
)
def test_add_record_rejects_story_without_matching_rejection_state(
    db_session_factory,
    status: StoryStatus,
    safety_reason: str | None,
) -> None:
    with db_session_factory() as db:
        story = _story(db)
        story.status = status
        story.safety_reason = safety_reason

        with pytest.raises(ValueError, match="invalid safety decision"):
            moderation_audit.add_record(
                db,
                story,
                _openai_decision(),
            )


@pytest.mark.parametrize("delete_target", ["story", "child", "parent"])
def test_moderation_record_cascades_with_owned_story(
    db_session_factory,
    delete_target: str,
) -> None:
    with db_session_factory() as db:
        story = _story(db, suffix=delete_target)
        record = moderation_audit.add_record(
            db,
            story,
            _openai_decision(),
        )
        db.commit()
        record_id = record.id

        if delete_target == "story":
            db.delete(story)
        elif delete_target == "child":
            db.delete(story.child)
        else:
            db.delete(story.child.parent)
        db.commit()

        assert db.get(ModerationRecord, record_id) is None
