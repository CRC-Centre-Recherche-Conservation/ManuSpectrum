"""Project-level Django system checks.

Registered from ``ManuspectrumConfig.ready()`` so they run with every
management command that performs system checks (``check``, ``migrate``,
``runserver``…), which makes ``migrate`` the deploy gate: an Error here
refuses to migrate a misconfigured production instance.
"""

import re

from django.conf import settings
from django.core import checks

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


@checks.register(checks.Tags.database)
def check_published_graph_languages(app_configs, databases, **kwargs):
    """Every LANGUAGES entry needs PublishedGraph rows for publications in use.

    Arches serialises each graph PER LANGUAGE at publication time. Activating a
    new language after publishing leaves those serialisations missing, and every
    Arches page under /<lang>/ then 500s (`NoneType has no attribute
    'serialized_graph'` — find_publication_in_language has no fallback).
    Fix: ``python manage.py i18n synclanguages`` (official add-a-language sync,
    covers resource models AND branches).

    Database-tagged so it runs with migrate — the natural deploy gate. Wrapped
    defensively: on a fresh database the Arches tables may not exist yet.
    """
    try:
        from arches.app.models.models import (
            GraphModel,
            PublishedGraph,
            ResourceInstance,
        )

        # Every graph's CURRENT publication (resource models AND branches —
        # the graph designer loads branch cards too, same crash), plus any
        # older publication still pinned by a resource instance.
        used_pubs = set(
            GraphModel.objects.filter(publication__isnull=False).values_list(
                "publication_id", flat=True
            )
        ) | set(
            ResourceInstance.objects.exclude(graph_publication_id=None)
            .values_list("graph_publication_id", flat=True)
            .distinct()
        )
        if not used_pubs:
            return []
        messages = []
        for code, _name in settings.LANGUAGES:
            covered = set(
                PublishedGraph.objects.filter(
                    language=code, publication_id__in=used_pubs
                ).values_list("publication_id", flat=True)
            )
            missing = used_pubs - covered
            if missing:
                messages.append(
                    checks.Warning(
                        f"Language '{code}' has no published-graph serialisation "
                        f"for {len(missing)} graph publication(s) in use — Arches "
                        f"pages under /{code}/ will raise 500. Run "
                        "`python manage.py i18n synclanguages` (the official "
                        "add-a-language sync: it updates publications for "
                        "models AND branches).",
                        id="manuspectrum.W002",
                    )
                )
        return messages
    except Exception:  # noqa: BLE001 — a half-migrated DB must not block migrate
        return []


@checks.register()
def check_contact_email(app_configs, **kwargs):
    """Block prod deploys while the public contact address is a placeholder.

    The About > Contact page publishes ``CONTACT_EMAIL`` (falling back to
    ``DEFAULT_FROM_EMAIL``) as a live mailto: link. Shipping the factory
    placeholder means visitors mail a dead address.
    """
    email = effective_contact_email()
    if not is_placeholder_email(email):
        return []

    msg = (
        "The public contact page would publish the placeholder address "
        f"'{email}' (from CONTACT_EMAIL / DEFAULT_FROM_EMAIL). Set a real "
        "address in settings_local.py, or empty both settings to disable "
        "the contact button."
    )
    if settings.DEBUG:
        return [checks.Warning(msg, id="manuspectrum.W001")]
    return [checks.Error(msg, id="manuspectrum.E001")]
