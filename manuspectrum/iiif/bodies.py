"""Annotation bodies and links of the files of an analysis.

A measurement file is a ``Dataset`` body and a micro-imaging file an
``Image`` body, both pointing at the file's ``/iiif/data/<file>/raw`` route
with its true media type (``facts.media_type``); an imaging manifest is a
``Manifest`` body. A licence in a rights registry is ``rights``; any other is
a ``requiredStatement`` naming it (with its attribution); an attribution under
a registry licence is a ``requiredStatement`` too.
"""

from manuspectrum.constants.licenses import (
    CUSTOM_LICENSE_ID,
    effective_license,
    iiif_rights,
)
from manuspectrum.iiif import ids
from manuspectrum.iiif import language as lang


def raw_label(file):
    return lang.gettext_map("%(file)s, raw file", file=file.name)


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
    body = {
        "id": ids.data_raw(file.id),
        "type": "Image" if file.kind == "micro-imaging" else "Dataset",
        "format": file.media_type,
        "label": raw_label(file),
    }
    body.update(licence_fields(file.entry))
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
