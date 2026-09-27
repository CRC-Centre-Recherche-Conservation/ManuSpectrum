"""Django's ``makemessages``, also extracting the msgids given to the IIIF language-map helpers.

``manuspectrum.iiif.language.gettext_map(msgid, …)`` and
``ngettext_map(singular, plural, n, …)`` translate their literal arguments
in every configured language; xgettext reads them as keywords like
``gettext`` and ``ngettext``.
"""

from django.core.management.commands import makemessages


class Command(makemessages.Command):
    xgettext_options = makemessages.Command.xgettext_options + [
        "--keyword=gettext_map",
        "--keyword=ngettext_map:1,2",
    ]
