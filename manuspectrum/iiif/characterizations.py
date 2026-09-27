"""The Presentation 3 annotation of one zone of an identified material (``classifying``, C3).

One annotation per zone (``ids.annotation(characterization, feature)``); no
``metadata``. Its bodies are, in order: one plain-text ``TextualBody`` per
language of ``settings.LANGUAGES`` (``describing``) naming the materials with
their certainty, the colours, the layers and the elements with their level;
one ``SpecificResource`` per concept that stores a URI, its ``source`` the
URI as stored (a string: the IIIF schema admits no untyped source object)
and its ``label`` every label of the item (material ``classifying``,
certainty ``assessing``, colour, layer and element ``describing``); and one
``linking`` body per zone of each cited analysis the reader may see, its
source that zone's annotation id. A cited analysis with no zone on the
Document's canvases is linked through its report in ``seeAlso`` instead.
No ``canonical``: the zones of one identified material are distinct
annotations, and one canonical IRI would let a client merge them.
"""

from django.conf import settings
from django.utils import translation
from django.utils.translation import gettext, gettext_noop

from manuspectrum.iiif import ids, selectors
from manuspectrum.iiif import language as lang

PARTS = (
    ("colours", gettext_noop("Colour: %(colours)s")),
    ("layers", gettext_noop("Layer: %(layers)s")),
)


def name_of(fact):
    """The materials of *fact*, else its name, else its id under ``none``."""
    return (
        lang.joined(concept.labels for concept, _ in fact.materials)
        or fact.name
        or lang.none(fact.id)
    )


def _texts(pairs, code):
    return ", ".join(
        lang.text_in(
            lang.qualified(concept.labels, qualifier.labels if qualifier else None),
            code,
        )
        for concept, qualifier in pairs
    )


def text(fact, code):
    """The plain-text description of *fact* in the language *code*; "" when it states nothing."""
    with translation.override(code):
        parts = [_texts(fact.materials, code)]
        for attribute, pattern in PARTS:
            concepts = getattr(fact, attribute)
            if concepts:
                parts.append(
                    gettext(pattern)
                    % {
                        attribute: ", ".join(
                            lang.text_in(c.labels, code) for c in concepts
                        )
                    }
                )
        if fact.elements:
            parts.append(
                gettext("Elements: %(elements)s")
                % {"elements": _texts(fact.elements, code)}
            )
    parts = [p for p in parts if p]
    return ". ".join(parts) + "." if parts else ""


def _concept_body(concept, purpose):
    return {
        "type": "SpecificResource",
        "purpose": purpose,
        "source": concept.uri,
        "label": concept.labels,
    }


def concept_bodies(fact):
    """The ``SpecificResource`` bodies of the concepts of *fact* that store a URI, each (purpose, URI) once."""
    candidates = [(c, "classifying") for c, _ in fact.materials]
    candidates += [(q, "assessing") for _, q in fact.materials if q]
    candidates += [(c, "describing") for c in (*fact.colours, *fact.layers)]
    candidates += [(c, "describing") for c, _ in fact.elements]
    seen, found = set(), []
    for concept, purpose in candidates:
        if concept.uri and (purpose, concept.uri) not in seen:
            seen.add((purpose, concept.uri))
            found.append(_concept_body(concept, purpose))
    return found


def characterization_annotation(doc, fact, zone):
    """The annotation of *zone* of the identified material *fact* of the document facts *doc*."""
    body = []
    for code, _ in settings.LANGUAGES:
        value = text(fact, code)
        if value:
            body.append(
                {
                    "type": "TextualBody",
                    "purpose": "describing",
                    "format": "text/plain",
                    "language": code,
                    "value": value,
                }
            )
    body += concept_bodies(fact)
    see_also = [
        {
            "id": ids.report(fact.id),
            "type": "Text",
            "format": "text/html",
            "label": name_of(fact),
        }
    ]
    for analysis, features in fact.evidence:
        if features:
            body += [
                {
                    "type": "SpecificResource",
                    "purpose": "linking",
                    "source": {
                        "id": ids.annotation(analysis, feature),
                        "type": "Annotation",
                    },
                }
                for feature in features
            ]
            continue
        link = {"id": ids.report(analysis), "type": "Text", "format": "text/html"}
        label = doc.names.get(analysis)
        if label:
            link["label"] = label
        see_also.append(link)
    annotation = {
        "id": ids.annotation(fact.id, zone.feature),
        "type": "Annotation",
        "motivation": "classifying",
        "label": name_of(fact),
    }
    if body:
        annotation["body"] = body
    annotation["target"] = selectors.target(zone.canvas, doc.manifest_url, zone.shape)
    annotation["seeAlso"] = see_also
    return annotation
