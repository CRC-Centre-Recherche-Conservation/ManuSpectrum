"""Django's ``makemessages``, also extracting the msgids given to the IIIF language-map helpers.

``manuspectrum.iiif.language.gettext_map(msgid, …)`` and
``ngettext_map(singular, plural, n, …)`` translate their literal arguments
in every configured language; xgettext reads them as keywords like
``gettext`` and ``ngettext``.

``docs/`` and ``docs_claude/`` (gitignored working notes) and ``node_modules/``
are never scanned, whatever ``--ignore`` says.
"""

from django.core.management.commands import makemessages

ALWAYS_IGNORED = ("node_modules/*", "docs/*", "docs_claude/*")


class Command(makemessages.Command):
    xgettext_options = makemessages.Command.xgettext_options + [
        "--keyword=gettext_map",
        "--keyword=ngettext_map:1,2",
    ]

    def handle(self, *args, **options):
        given = options.get("ignore_patterns") or []
        options["ignore_patterns"] = [
            *given,
            *(pattern for pattern in ALWAYS_IGNORED if pattern not in given),
        ]
        return super().handle(*args, **options)
