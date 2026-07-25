import re
from collections.abc import Sequence
from dataclasses import dataclass


_BLOCKED_TERMS = (
    "alcohol",
    "alcool",
    "arme",
    "blood",
    "drogue",
    "drug",
    "kill",
    "sang",
    "suicide",
    "tuer",
    "violence",
    "weapon",
)
_BLOCKED_PATTERN = re.compile(
    rf"\b(?:{'|'.join(re.escape(term) for term in _BLOCKED_TERMS)})\b",
    flags=re.IGNORECASE,
)
_BLOCKED_REASON = "Content includes a blocked safety term."


@dataclass(frozen=True, slots=True)
class SafetyResult:
    is_safe: bool
    reason: str | None = None


def check_text(text: str) -> SafetyResult:
    if _BLOCKED_PATTERN.search(text):
        return SafetyResult(is_safe=False, reason=_BLOCKED_REASON)
    return SafetyResult(is_safe=True)


def check_story(page_texts: Sequence[str]) -> SafetyResult:
    if isinstance(page_texts, str):
        raise TypeError("page_texts must be a sequence of page strings")

    for page_number, page_text in enumerate(page_texts, start=1):
        result = check_text(page_text)
        if not result.is_safe:
            return SafetyResult(
                is_safe=False,
                reason=(
                    f"Page {page_number} includes a blocked safety term."
                ),
            )
    return SafetyResult(is_safe=True)
