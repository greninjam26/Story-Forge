"""Construct private moderation records without owning the transaction."""

from sqlalchemy.orm import Session

from app.models import ModerationRecord, Story, StoryStatus
from app.services.safety import (
    UNCATEGORIZED_PROVIDER_FLAG,
    SafetyDecision,
)


def _valid_decision(decision: SafetyDecision) -> bool:
    if (
        decision.is_safe
        or decision.reason_code is None
        or decision.provider not in {"keyword", "openai"}
        or decision.flagged_item_kind not in {"title", "page"}
        or decision.flagged_text is None
    ):
        return False

    if decision.flagged_item_kind == "title":
        if decision.flagged_page_number is not None:
            return False
    elif (
        decision.flagged_page_number is None
        or decision.flagged_page_number < 1
    ):
        return False

    if decision.provider == "openai":
        contains_uncategorized_marker = (
            UNCATEGORIZED_PROVIDER_FLAG in decision.categories
        )
        is_uncategorized_provider_flag = (
            decision.reason_code == "unsafe_content"
            and decision.categories == (UNCATEGORIZED_PROVIDER_FLAG,)
            and not decision.category_scores
        )
        if (
            not decision.provider_model
            or not decision.provider_request_id
            or (
                contains_uncategorized_marker
                and not is_uncategorized_provider_flag
            )
            or (
                not is_uncategorized_provider_flag
                and (
                    not decision.categories
                    or set(decision.category_scores)
                    != set(decision.categories)
                )
            )
        ):
            return False
    elif (
        decision.provider_model is not None
        or decision.provider_request_id is not None
        or not decision.categories
        or decision.categories != (decision.reason_code,)
        or decision.category_scores
    ):
        return False

    return True


def add_record(
    db: Session,
    story: Story,
    decision: SafetyDecision,
) -> ModerationRecord:
    """Add, but do not commit, one record for a safety-rejected story."""
    if (
        story.status is not StoryStatus.REJECTED
        or story.safety_reason != decision.reason_code
        or not _valid_decision(decision)
    ):
        raise ValueError("invalid safety decision for moderation audit")

    record = ModerationRecord(
        story=story,
        provider=decision.provider,
        model=decision.provider_model,
        provider_request_id=decision.provider_request_id,
        flagged_item_kind=decision.flagged_item_kind,
        flagged_page_number=decision.flagged_page_number,
        flagged_text=decision.flagged_text,
        categories=list(decision.categories),
        category_scores=dict(decision.category_scores),
        review_status="pending",
    )
    db.add(record)
    return record
