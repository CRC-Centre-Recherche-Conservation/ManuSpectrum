"""Offline JSON-LD helpers for the IIIF tests: vendored contexts and a PyLD document loader.

Vendored contexts (``tests/fixtures/iiif/``), fetched on 2026-09-27:

- ``presentation-3-context.json`` — http://iiif.io/api/presentation/3/context.json,
  sha256 4bef9062347af702919b625655735a67a700f847f29f6501708c426159eda02d
- ``auth-2-context.json`` — http://iiif.io/api/auth/2/context.json,
  sha256 eddeaea362c44fe7ae4a2eed8446214e4e228d3eea48ec509a8a9b1b824027cd
- ``auth-1-context.json`` — http://iiif.io/api/auth/1/context.json,
  sha256 961b3cda21b5c425a708ee9a3169727d9df9da993d65e255d9302f14fbf2bc7d
- ``anno-context.json`` — http://www.w3.org/ns/anno.jsonld (the Web Annotation
  context Presentation 3 scopes on ``Annotation``), fetched on 2026-09-27,
  sha256 c10fd886c5c726fbfd51747b8677eb8f7d02c039357269622de7382e5c20d410
- ``presentation-2-context.json`` — http://iiif.io/api/presentation/2/context.json,
  sha256 7068df34790f018db679928bfbc492d9af36c22b05902c46a7c91a19272701cb

The processor is PyLD 1.0.5, the version Arches pins. It resolves every
nested context URL before expanding and refuses the Presentation 3 context
(which reaches the Image 3 context, which reaches Presentation 3 again), so
documents are expanded here under our extension context alone; that
Presentation 3 terms are left untouched is checked on the vendored context's
terms instead. ``expand_presentation`` expands a Presentation 3 document under
the vendored Presentation 3 and Web Annotation contexts, every other context
it names (Image, Search, Auth, selector registry) read as empty: the terms
those define do not expand. ``expand_v2`` expands a Presentation 2 document
under the vendored Presentation 2 context and ours, which PyLD reads whole.
"""

import json
from pathlib import Path

from pyld import jsonld

from manuspectrum.iiif import ids, xy_reading

FIXTURES = Path(__file__).parent / "fixtures" / "iiif"


def vendored(name):
    with (FIXTURES / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def presentation_3_terms():
    """The terms the Presentation 3 context defines at its top level."""
    return vendored("presentation-3-context.json")["@context"]


def loader(url, options=None):
    """PyLD document loader serving our xy-reading context and nothing else."""
    if url != ids.xy_context():
        raise jsonld.JsonLdError(
            "Offline loader: unknown context", "jsonld.LoadDocumentError", {"url": url}
        )
    return {
        "contextUrl": None,
        "documentUrl": url,
        "document": xy_reading.context_document(),
    }


def expand(document):
    return jsonld.expand(document, {"documentLoader": loader})


PRESENTATION_3 = "http://iiif.io/api/presentation/3/context.json"
ANNOTATION = "http://www.w3.org/ns/anno.jsonld"


def presentation_loader(url, options=None):
    """PyLD document loader serving ours and the vendored Presentation 3 and Web Annotation contexts; any other is empty."""
    if url == ids.xy_context():
        return loader(url)
    documents = {
        PRESENTATION_3: "presentation-3-context.json",
        ANNOTATION: "anno-context.json",
    }
    document = vendored(documents[url]) if url in documents else {"@context": {}}
    return {"contextUrl": None, "documentUrl": url, "document": document}


def expand_presentation(document):
    return jsonld.expand(document, {"documentLoader": presentation_loader})


PRESENTATION_2 = "http://iiif.io/api/presentation/2/context.json"


def v2_loader(url, options=None):
    """PyLD document loader serving ours and the vendored Presentation 2 context, nothing else."""
    if url == PRESENTATION_2:
        return {
            "contextUrl": None,
            "documentUrl": url,
            "document": vendored("presentation-2-context.json"),
        }
    return loader(url)


def expand_v2(document):
    return jsonld.expand(document, {"documentLoader": v2_loader})
