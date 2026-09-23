"""Licences a curator can attach to a stored file.

Each entry of a ``file-list`` value may carry a ``license`` key::

    {"id": "<SPDX id>", "url": "<licence text URL>", "label": "<custom only>"}

The key is not localised. ``LicenseRef-custom`` carries the label and URL the
curator typed. The browser receives this catalogue through
``templates/javascript.htm`` (``license_catalogue_json``); the display rule
(a missing, unknown or incomplete licence shows ``DEFAULT_LICENSE_ID``) lives
in ``media/js/utils/file-license.js``.
"""

import json

from django.utils.translation import gettext_lazy as _

LICENSE_KEY = "license"
DEFAULT_LICENSE_ID = "CC-BY-SA-4.0"
CUSTOM_LICENSE_ID = "LicenseRef-custom"

LICENSES = (
    {
        "id": "CC-BY-SA-4.0",
        "url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "label": _("CC BY-SA 4.0"),
    },
    {
        "id": "CC-BY-4.0",
        "url": "https://creativecommons.org/licenses/by/4.0/",
        "label": _("CC BY 4.0"),
    },
    {
        "id": "CC-BY-NC-4.0",
        "url": "https://creativecommons.org/licenses/by-nc/4.0/",
        "label": _("CC BY-NC 4.0"),
    },
    {
        "id": "CC-BY-NC-SA-4.0",
        "url": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
        "label": _("CC BY-NC-SA 4.0"),
    },
    {
        "id": "CC-BY-ND-4.0",
        "url": "https://creativecommons.org/licenses/by-nd/4.0/",
        "label": _("CC BY-ND 4.0"),
    },
    {
        "id": "CC0-1.0",
        "url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "label": _("CC0 1.0 (public domain dedication)"),
    },
    {
        "id": "etalab-2.0",
        "url": "https://www.etalab.gouv.fr/licence-ouverte-open-licence/",
        "label": _("Licence Ouverte / Etalab 2.0"),
    },
    {
        "id": "ODbL-1.0",
        "url": "https://opendatacommons.org/licenses/odbl/1-0/",
        "label": _("ODbL 1.0"),
    },
    {
        "id": CUSTOM_LICENSE_ID,
        "url": "",
        "label": _("Other licence…"),
    },
)

_BY_ID = {entry["id"]: entry for entry in LICENSES}


def stored_license(license_id):
    """``{"id", "url"}`` stored on a file for a catalogue licence.

    Raises ``ValueError`` for an id outside the catalogue and for
    ``LicenseRef-custom``, whose label and URL only a curator can give.
    """
    entry = _BY_ID.get(license_id)
    if entry is None or license_id == CUSTOM_LICENSE_ID:
        raise ValueError(f"{license_id!r} is not a catalogue licence")
    return {"id": entry["id"], "url": entry["url"]}


def default_license():
    """The licence stored on a file that has none."""
    return stored_license(DEFAULT_LICENSE_ID)


def catalogue_json():
    """The catalogue in the active language, as the browser reads it."""
    return json.dumps(
        {
            "default": DEFAULT_LICENSE_ID,
            "custom": CUSTOM_LICENSE_ID,
            "licenses": [
                {"id": entry["id"], "url": entry["url"], "label": str(entry["label"])}
                for entry in LICENSES
            ],
        },
        ensure_ascii=False,
    )
