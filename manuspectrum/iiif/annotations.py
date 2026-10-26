"""The Presentation 3 annotation of one analysis zone (``supplementing``).

One annotation per located zone, its id ``ids.annotation(analysis, feature)``.
Bodies are the analysis's files and imaging manifests (``bodies``); the target
is the zone on its canvas, part of the Document's source manifest
(``selectors.target``). ``metadata`` holds, when present, the technique,
dates, operators, instrument, conditions, projects, Document, Component and
« Status: Draft » for an unpublished analysis; every label and value is a
language map. ``seeAlso`` links the report, the published dataset (its web
address as ``id``, its stored label under ``none``) and each measurement file
as stored.
"""

from django.utils.translation import gettext_noop

from manuspectrum.iiif import bodies, ids, selectors
from manuspectrum.iiif import language as lang
from manuspectrum.views.explorer.values import dataset_url

METADATA = (
    (gettext_noop("Technique"), "technique"),
    (gettext_noop("Dates"), "dates"),
    (gettext_noop("Operators"), "operators"),
    (gettext_noop("Instrument"), "instrument"),
    (gettext_noop("Conditions"), "conditions"),
    (gettext_noop("Project"), "projects"),
    (gettext_noop("Document"), "document"),
    (gettext_noop("Component"), "component"),
    (gettext_noop("Identified materials"), "materials"),
)


def name_of(fact):
    """The analysis's name, else its id under ``none``."""
    return fact.name or lang.none(fact.id)


def metadata(fact):
    entries = [
        {"label": lang.gettext_map(label), "value": getattr(fact, attribute)}
        for label, attribute in METADATA
        if getattr(fact, attribute)
    ]
    if fact.draft:
        entries.append(
            {"label": lang.gettext_map("Status"), "value": lang.gettext_map("Draft")}
        )
    return entries


def see_also(fact):
    links = [
        {
            "id": ids.report(fact.id),
            "type": "Text",
            "format": "text/html",
            "label": name_of(fact),
        }
    ]
    address = dataset_url(fact.dataset)
    if address:
        link = {"id": address, "type": "Text", "format": "text/html"}
        label = lang.none((fact.dataset or {}).get("label") or "")
        if label:
            link["label"] = label
        links.append(link)
    links.extend(bodies.raw_link(f) for f in fact.files if f.kind == "measurement")
    return links


def analysis_annotation(doc, fact, zone):
    """The annotation of *zone* of the analysis *fact* of the document facts *doc*."""
    annotation = {
        "id": ids.annotation(fact.id, zone.feature),
        "type": "Annotation",
        "motivation": "supplementing",
        "label": name_of(fact),
    }
    body = [bodies.file_body(f) for f in fact.files]
    body += [bodies.imaging_body(url, label) for url, label in fact.imaging]
    if body:
        annotation["body"] = body
    annotation["target"] = selectors.target(zone.canvas, doc.manifest_url, zone.shape)
    entries = metadata(fact)
    if entries:
        annotation["metadata"] = entries
    annotation["seeAlso"] = see_also(fact)
    return annotation
