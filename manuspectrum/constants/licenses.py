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
from urllib.parse import urlparse, urlunparse

from django.utils import translation
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


RIGHTS_REGISTRY_HOSTS = ("creativecommons.org", "rightsstatements.org")


def _attribution_text(stored, language):
    """The attribution text of a file entry in *language*, else English, else any; None when empty.

    Arches stores it per language as ``{lang: {"value", "direction"}}``; a
    plain string or a ``{lang: text}`` mapping reads the same way.
    """

    def text(value):
        if isinstance(value, dict):
            value = value.get("value")
        return value.strip() if isinstance(value, str) else ""

    if not isinstance(stored, dict):
        return text(stored) or None
    texts = {lang: text(value) for lang, value in stored.items()}
    for lang in (language, "en"):
        if texts.get(lang):
            return texts[lang]
    return next((value for value in texts.values() if value), None)


def effective_license(entry, language):
    """The licence of a file entry as the Explorer shows it (spec §5 ``FileEntry.license``).

    A missing licence resolves to the default one, flagged ``isDefault``. The
    label comes from the catalogue in *language*; a custom licence keeps the
    label the curator typed. ``attribution`` is the entry's attribution text
    in *language*, else English, else the first one.
    """
    entry = entry if isinstance(entry, dict) else {}
    stored = entry.get(LICENSE_KEY)
    is_default = not (isinstance(stored, dict) and stored.get("id"))
    licence = default_license() if is_default else stored
    catalogue = _BY_ID.get(licence["id"])
    url = licence.get("url") or (catalogue or {}).get("url")
    if catalogue and licence["id"] != CUSTOM_LICENSE_ID:
        with translation.override(language):
            text = str(catalogue["label"])
    else:
        text = licence.get("label") or licence["id"]
    attribution = _attribution_text(entry.get("attribution"), language)
    return {
        "id": licence["id"],
        "url": url,
        "label": {"value": text, "lang": language},
        "attribution": attribution or None,
        "noDerivatives": "-ND" in licence["id"].upper(),
        "inRightsRegistry": bool(url)
        and (urlparse(url).hostname or "") in RIGHTS_REGISTRY_HOSTS,
        "isDefault": is_default,
    }


def iiif_rights(licence):
    """The IIIF ``rights`` value of an ``effective_license()`` result, or None.

    IIIF Presentation 3 ``rights`` takes a Creative Commons or
    RightsStatements.org URI in its ``http://`` form; a licence hosted
    anywhere else, or without a URL, has none.
    """
    url = (licence or {}).get("url")
    if not url:
        return None
    parsed = urlparse(url)
    if (parsed.hostname or "") not in RIGHTS_REGISTRY_HOSTS:
        return None
    return urlunparse(parsed._replace(scheme="http"))


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
