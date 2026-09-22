"""Project-level Django system checks.

Registered from ``ManuspectrumConfig.ready()`` so they run with every
management command that performs system checks (``check``, ``migrate``,
``runserver``…), which makes ``migrate`` the deploy gate: an Error here
refuses to migrate a misconfigured production instance.
"""

from django.conf import settings
from django.core import checks

# Re-exported: the address helpers live in a leaf module so utils.http can
# share them without importing this (check-registering) module.
from manuspectrum.utils.contact import (  # noqa: F401
    effective_contact_email,
    is_placeholder_email,
)


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


def _package_graphs_referencing(function_id):
    """Names of the pkg/ graph files whose JSON mentions ``function_id``.

    A plain substring scan of ~2 MB: the exported graph carries its
    ``functions_x_graphs`` rows verbatim (arches/app/utils/exporter.py:89-90,
    191-199), so the id appears as text or not at all.
    """
    from pathlib import Path

    package_dir = getattr(settings, "PACKAGE_DIR", None)
    if not package_dir:
        return []
    found = []
    for path in sorted(Path(package_dir, "graphs").rglob("*.json")):
        try:
            if function_id in path.read_text(encoding="utf-8"):
                found.append(path.name)
        except OSError:
            continue
    return found


@checks.register(checks.Tags.database)
def check_summary_function_registered(app_configs, databases, **kwargs):
    """W003: a pkg/ graph references the summary function but its row is absent.

    ``load_package`` drops a ``functions_x_graphs`` entry whose Function is
    unknown without a word (arches/app/models/graph.py:571-592), so the graph
    would load with its summary configuration silently gone. Running ``migrate``
    first registers the function.

    ``SUMMARY_PACKAGE_GRAPH_IDS`` short-circuits the pkg/ scan when set.
    Database-tagged so it runs with migrate, and, like W002, silent on a
    half-migrated database.
    """
    if "default" not in (databases or []):
        return []

    from manuspectrum.functions.resource_summary import SUMMARY_FUNCTION_ID

    graph_ids = getattr(settings, "SUMMARY_PACKAGE_GRAPH_IDS", None)
    if graph_ids is None:
        graph_ids = _package_graphs_referencing(SUMMARY_FUNCTION_ID)
    if not graph_ids:
        return []

    try:
        from arches.app.models.models import Function

        registered = Function.objects.filter(pk=SUMMARY_FUNCTION_ID).exists()
    except Exception:  # noqa: BLE001 — a half-migrated DB must not block migrate
        return []
    if registered:
        return []
    return [
        checks.Warning(
            "The Resource Summary function is referenced by "
            f"{', '.join(str(g) for g in graph_ids)} but is not registered; "
            "run `python manage.py migrate` before loading the package, or the "
            "summary configuration of those graphs is dropped on load.",
            id="manuspectrum.W003",
        )
    ]


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
