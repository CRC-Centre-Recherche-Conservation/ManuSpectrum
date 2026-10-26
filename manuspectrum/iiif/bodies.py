"""Annotation bodies and links of the files of an analysis.

A measurement file with a clean CSV (``data.clean_series_available``) is a
``Dataset`` body at ``/iiif/data/<file>/series.csv``, ``text/csv``, carrying
its ``xyReading``. Any other measurement file is a ``Dataset`` body at its
``/iiif/data/<file>/raw`` route with its true media type
(``data.media_type``), carrying the reading of its raw columns when it is a
supported text format with a renderer configuration. A micro-imaging file is
an ``Image`` body at its raw route; an imaging manifest is a ``Manifest``
body. Every body served by a data route declares the Auth 1.0 and 2.0
services (``services.dataset_services``). A licence in a rights registry is ``rights``; any other is a
``requiredStatement`` naming it (with its attribution); an attribution under
a registry licence is a ``requiredStatement`` too.
"""

from manuspectrum.constants.licenses import (
    CUSTOM_LICENSE_ID,
    effective_license,
    iiif_rights,
)
from manuspectrum.iiif import ids, services
from manuspectrum.iiif import language as lang
from manuspectrum.iiif.data import clean_series_available
from manuspectrum.iiif.xy_reading import raw_label, raw_reading, xy_reading
from manuspectrum.utils.spectrum_preview import is_supported


def licence_fields(entry):
    """``rights`` and/or ``requiredStatement`` of a file entry's licence (``effective_license``)."""
    codes = lang.languages()
    licences = {code: effective_license(entry, code) for code in codes}
    first = licences[codes[0]]
    if first["id"] == CUSTOM_LICENSE_ID:
        name = lang.none(first["label"]["value"])
    else:
        name = lang.from_texts(
            {code: licence["label"]["value"] for code, licence in licences.items()}
        )
    attribution = lang.string_map((entry or {}).get("attribution"))
    fields = {}
    rights = iiif_rights(first)
    if rights:
        fields["rights"] = rights
        if attribution:
            fields["requiredStatement"] = {
                "label": lang.gettext_map("Attribution"),
                "value": attribution,
            }
    elif name or attribution:
        fields["requiredStatement"] = {
            "label": lang.gettext_map("Licence"),
            "value": lang.joined([name, attribution], sep=" — "),
        }
    return fields


def file_body(file):
    """The body of one ``FileFact``."""
    if file.kind == "measurement" and clean_series_available(file):
        body = {
            "id": ids.data_series(file.id),
            "type": "Dataset",
            "format": "text/csv",
            "label": lang.gettext_map("%(file)s, series", file=file.name),
        }
        body.update(licence_fields(file.entry))
        body["service"] = services.dataset_services(file.id)
        body["xyReading"] = xy_reading(file, file.config)
        return body
    body = {
        "id": ids.data_raw(file.id),
        "type": "Image" if file.kind == "micro-imaging" else "Dataset",
        "format": file.media_type,
        "label": raw_label(file),
    }
    body.update(licence_fields(file.entry))
    body["service"] = services.dataset_services(file.id)
    if file.kind == "measurement" and file.config and is_supported(file.name):
        body["xyReading"] = raw_reading(file.config)
    return body


def raw_link(file):
    """The ``seeAlso`` entry downloading a measurement file as stored."""
    return {
        "id": ids.data_raw(file.id),
        "type": "Dataset",
        "format": file.media_type,
        "label": raw_label(file),
    }


def imaging_body(url, label):
    """The ``Manifest`` body of an imaging manifest."""
    body = {"id": url, "type": "Manifest"}
    if label:
        body["label"] = label
    return body
