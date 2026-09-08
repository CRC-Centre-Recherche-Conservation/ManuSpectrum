"""Resolution of the project's public contact address.

Kept in a side-effect-free leaf module so both the system checks
(``manuspectrum.checks``) and outbound HTTP helpers (``manuspectrum.utils.http``)
can share one definition of "the address we publish" without importing each
other.
"""

import re

from django.conf import settings

# Matches factory placeholders such as "xxxx@xxx.com" (any run of x's on
# either side of the @, optionally with a TLD).
_PLACEHOLDER_RE = re.compile(r"^x+@x+(\.[a-z]{2,})?$", re.IGNORECASE)

# Domains that can never be a real public contact address.
_PLACEHOLDER_DOMAINS = {"example.com", "example.org", "example.net", "xxx.com"}


def effective_contact_email():
    """The address the {% contact_email %} template tag would publish."""
    return (
        getattr(settings, "CONTACT_EMAIL", "")
        or getattr(settings, "DEFAULT_FROM_EMAIL", "")
        or ""
    )


def is_placeholder_email(value):
    """True when *value* is a factory placeholder, not a real address.

    Empty values are NOT placeholders: "no address configured" is a designed,
    tested state (the contact page disables its mailto button).
    """
    if not value:
        return False
    addr = value.strip().lower()
    if _PLACEHOLDER_RE.match(addr):
        return True
    domain = addr.rsplit("@", 1)[-1]
    return domain in _PLACEHOLDER_DOMAINS


def publishable_contact_email():
    """The contact address safe to expose to third parties, or ''.

    Same resolution as :func:`effective_contact_email`, minus factory
    placeholders — used where a dead address would be worse than none
    (e.g. the outbound User-Agent).
    """
    email = effective_contact_email()
    return "" if is_placeholder_email(email) else email
