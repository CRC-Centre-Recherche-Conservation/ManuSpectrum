"""Licences a curator can attach to a stored file.

Each entry of a ``file-list`` value may carry a ``license`` key::

    {"id": "<SPDX id>", "url": "<licence text URL>", "label": "<custom only>"}

The key is not localised. A missing or unknown licence is shown as
``DEFAULT_LICENSE_ID``; ``LicenseRef-custom`` carries the label and URL the
curator typed. The browser receives this catalogue through
``templates/javascript.htm`` (``license_catalogue_json``) and applies the same
resolution in ``media/js/utils/file-license.js``.
"""

import json
from urllib.parse import urlsplit

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


def _is_web_url(value):
    if not isinstance(value, str):
        return False
    parts = urlsplit(value.strip())
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def default_license():
    """The licence stored on a file that has none: ``{"id", "url"}``."""
    entry = _BY_ID[DEFAULT_LICENSE_ID]
    return {"id": entry["id"], "url": entry["url"]}


def resolve(entry_license):
    """The licence to display for a stored ``license`` value.

    Returns ``{"id", "url", "label"}`` with a translated label. A missing or
    unknown id resolves to the default; a custom licence keeps its own label
    and URL, and resolves to the default unless its URL is http(s) and its
    label is not blank. A catalogue id always shows the catalogue URL.
    """
    license_id = entry_license.get("id") if isinstance(entry_license, dict) else None
    if license_id == CUSTOM_LICENSE_ID:
        label = entry_license.get("label")
        url = entry_license.get("url")
        if _is_web_url(url) and isinstance(label, str) and label.strip():
            return {"id": CUSTOM_LICENSE_ID, "url": url.strip(), "label": label.strip()}
        license_id = DEFAULT_LICENSE_ID
    entry = _BY_ID.get(license_id) or _BY_ID[DEFAULT_LICENSE_ID]
    return {"id": entry["id"], "url": entry["url"], "label": str(entry["label"])}


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
