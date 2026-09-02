from email_validator import (
    EmailUndeliverableError,
    caching_resolver,
    validate_email,
)

from app.config import settings


_dns_resolver = caching_resolver(
    timeout=settings.registration_email_dns_timeout_seconds,
)


def email_domain_can_receive_mail(email: str) -> bool:
    """Return false only when DNS definitively rejects email delivery."""
    try:
        validate_email(
            email,
            check_deliverability=True,
            dns_resolver=_dns_resolver,
        )
    except EmailUndeliverableError:
        return False
    return True
