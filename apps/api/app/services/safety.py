"""Generated-title and page safety policy run before parent preview."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.config import settings
from app.services import openai_moderation
from app.services.cost_tracking import (
    NOOP_COST_RECORDER,
    CostRecorder,
    Usage,
    record_cost_call,
)
from app.services.retry import retry_transient

SafetyReason = Literal[
    "violence",
    "self_harm",
    "sexual",
    "hate_or_harassment",
    "illicit",
    "unsafe_content",
]

REASON_PRIORITY: tuple[SafetyReason, ...] = (
    "sexual",
    "self_harm",
    "violence",
    "hate_or_harassment",
    "illicit",
    "unsafe_content",
)

# Audit-owned marker for a provider-level flag with no true provider category.
# The namespace prevents it from being mistaken for OpenAI evidence.
UNCATEGORIZED_PROVIDER_FLAG = "storyforge:provider_flagged_uncategorized"

KEYWORD_REASONS: dict[str, SafetyReason] = {
    "violence": "violence",
    "weapon": "violence",
    "blood": "violence",
    "kill": "violence",
    "arme": "violence",
    "sang": "violence",
    "tuer": "violence",
    "suicide": "self_harm",
    "drug": "illicit",
    "alcohol": "illicit",
    "drogue": "illicit",
    "alcool": "illicit",
}

CATEGORY_REASONS: dict[str, SafetyReason] = {
    "sexual": "sexual",
    "sexual/minors": "sexual",
    "self-harm": "self_harm",
    "self-harm/intent": "self_harm",
    "self-harm/instructions": "self_harm",
    "violence": "violence",
    "violence/graphic": "violence",
    "illicit/violent": "violence",
    "hate": "hate_or_harassment",
    "hate/threatening": "hate_or_harassment",
    "harassment": "hate_or_harassment",
    "harassment/threatening": "hate_or_harassment",
    "illicit": "illicit",
}

_TERM_PATTERNS = {
    term: re.compile(rf"\b{re.escape(term)}\b", flags=re.IGNORECASE)
    for term in KEYWORD_REASONS
}


@dataclass(frozen=True)
class SafetyDecision:
    is_safe: bool
    reason_code: SafetyReason | None = None
    provider: Literal["keyword", "openai"] | None = None
    provider_model: str | None = None
    provider_request_id: str | None = None
    flagged_item_kind: Literal["title", "page"] | None = None
    flagged_page_number: int | None = None
    flagged_text: str | None = None
    categories: tuple[str, ...] = ()
    category_scores: Mapping[str, float] = field(default_factory=dict)


class SafetyConfigurationError(RuntimeError):
    """The selected safety provider is unsupported."""


class SafetyReviewUnavailable(RuntimeError):
    """Generated content could not receive the required safety decision."""


def _keyword_reasons(text: str) -> tuple[SafetyReason, ...]:
    matched = {
        KEYWORD_REASONS[term]
        for term, pattern in _TERM_PATTERNS.items()
        if pattern.search(text)
    }
    return tuple(
        reason for reason in REASON_PRIORITY if reason in matched
    )


def _keyword_decision(
    text: str,
    *,
    item_kind: Literal["title", "page"],
    page_number: int | None,
) -> SafetyDecision | None:
    reasons = _keyword_reasons(text)
    if not reasons:
        return None
    return SafetyDecision(
        is_safe=False,
        reason_code=reasons[0],
        provider="keyword",
        flagged_item_kind=item_kind,
        flagged_page_number=page_number,
        flagged_text=text,
        categories=(reasons[0],),
    )


def _parent_reason(categories: tuple[str, ...]) -> SafetyReason:
    mapped = {
        CATEGORY_REASONS.get(category, "unsafe_content")
        for category in categories
    }
    return next(
        reason for reason in REASON_PRIORITY if reason in mapped
    ) if mapped else "unsafe_content"


def _provider_decision(
    inputs: list[str],
    response: openai_moderation.ModerationResponse,
) -> SafetyDecision:
    for index, result in enumerate(response.results):
        if not result.flagged:
            continue
        categories = tuple(
            category
            for category, flagged in result.categories.items()
            if flagged
        )
        category_scores = {
            category: result.category_scores[category]
            for category in categories
        }
        if not categories:
            categories = (UNCATEGORIZED_PROVIDER_FLAG,)
            category_scores = {}
        return SafetyDecision(
            is_safe=False,
            reason_code=_parent_reason(categories),
            provider="openai",
            provider_model=response.model,
            provider_request_id=response.request_id,
            flagged_item_kind="title" if index == 0 else "page",
            flagged_page_number=None if index == 0 else index,
            flagged_text=inputs[index],
            categories=categories,
            category_scores=category_scores,
        )
    return SafetyDecision(is_safe=True)


def check_story(
    title: str,
    page_texts: Sequence[str],
    *,
    recorder: CostRecorder = NOOP_COST_RECORDER,
) -> SafetyDecision:
    """Apply keyword policy, then the configured provider, in display order."""
    inputs = [title, *page_texts]
    for index, text in enumerate(inputs):
        decision = _keyword_decision(
            text,
            item_kind="title" if index == 0 else "page",
            page_number=None if index == 0 else index,
        )
        if decision is not None:
            return decision

    if settings.safety_provider == "stub":
        return SafetyDecision(is_safe=True)
    if settings.safety_provider != "openai":
        raise SafetyConfigurationError(
            "SAFETY_PROVIDER must be stub or openai"
        )

    def _attempt(attempt: int) -> openai_moderation.ModerationResponse:
        try:
            response = openai_moderation.moderate(inputs)
        except openai_moderation.ModerationProviderError as error:
            record_cost_call(
                recorder,
                stage="moderation",
                provider="openai",
                model=settings.openai_moderation_model,
                attempt=attempt,
                outcome="provider_failure",
                usage=(Usage("moderation_request", 1),),
            )
            raise
        record_cost_call(
            recorder,
            stage="moderation",
            provider="openai",
            model=response.model,
            attempt=attempt,
            outcome="succeeded",
            usage=(Usage("moderation_request", 1),),
        )
        return response

    try:
        response = retry_transient(
            _attempt,
            is_transient=lambda e: isinstance(
                e, openai_moderation.ModerationProviderError
            ),
        )
    except openai_moderation.ModerationProviderError:
        # Raise outside the provider except block so private provider details
        # cannot be reached through the sanitized exception's context.
        raise SafetyReviewUnavailable(
            "safety review is unavailable"
        ) from None

    return _provider_decision(inputs, response)
