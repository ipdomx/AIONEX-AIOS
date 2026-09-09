"""Owner email validation is bounded and never performs deliverability lookup."""
from __future__ import annotations

import pytest

from app.core.owner_input_validation import normalize_owner_user_email


@pytest.mark.parametrize('value', [
    '', 'missing-at.example.com', 'a@@example.com', 'x @example.com',
    'a@', 'a@.com', 'a@example..com', 'a' * 100_000 + '@' + '.' * 100_000,
    None, {'email': 'user@example.com'},
])
def test_invalid_email_is_rejected(value: object) -> None:
    with pytest.raises(ValueError, match='User email is invalid'):
        normalize_owner_user_email(value)  # type: ignore[arg-type]


def test_normalization_preserves_existing_case_insensitive_account_policy() -> None:
    assert normalize_owner_user_email(' User+Tag@Example.COM ') == 'user+tag@example.com'


def test_deliverability_does_not_depend_on_external_dns() -> None:
    assert normalize_owner_user_email('user@unresolvable-domain-935674.example') == 'user@unresolvable-domain-935674.example'
