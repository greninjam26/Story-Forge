import dns.exception
import dns.resolver
import pytest

from app.services import email_validation


class _FailingResolver:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def resolve(self, _domain: str, _record_type: str) -> None:
        raise self.error


def test_nonexistent_email_domain_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        email_validation,
        "_dns_resolver",
        _FailingResolver(dns.resolver.NXDOMAIN()),
    )

    assert not email_validation.email_domain_can_receive_mail(
        "parent@missing-domain.example"
    )


def test_dns_timeout_does_not_block_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        email_validation,
        "_dns_resolver",
        _FailingResolver(dns.exception.Timeout()),
    )

    assert email_validation.email_domain_can_receive_mail(
        "parent@temporarily-unavailable.example"
    )


def test_unavailable_nameservers_do_not_block_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        email_validation,
        "_dns_resolver",
        _FailingResolver(dns.resolver.NoNameservers()),
    )

    assert email_validation.email_domain_can_receive_mail(
        "parent@temporarily-unavailable.example"
    )
