"""Every URL a IIIF document names, absolute on ``PUBLIC_SERVER_ADDRESS``.

This module is the only place a IIIF URL is minted. The paths are those of
the routes of ``manuspectrum/urls.py`` (below the LANGUAGE BOUNDARY);
``tests/test_iiif_routes.py`` resolves each one to its route name.
"""

from urllib.parse import quote

from django.conf import settings

KINDS = {
    "analysis": "annotation-collection",
    "characterization": "characterization-collection",
}


def _url(path):
    return f"{settings.PUBLIC_SERVER_ADDRESS}{path}"


def annotation(resource_id, feature_id, version=3):
    """The annotation of one zone (*feature_id*) of an analysis or a characterization."""
    return _url(f"iiif/v{version}/annotation/{resource_id}/{feature_id}")


def annotated_resource(annotation_id):
    """The resource id an ``annotation`` id (any version) names; None for any other value."""
    head = _url("iiif/v")
    if not isinstance(annotation_id, str) or not annotation_id.startswith(head):
        return None
    parts = annotation_id[len(head) :].split("/")
    if len(parts) != 4 or parts[1] != "annotation":
        return None
    return parts[2]


def annotation_first(resource_id, version=3):
    """The route answering the first zone of *resource_id*."""
    return _url(f"iiif/v{version}/annotation/{resource_id}")


def collection(resource_id, kind="analysis", version=3):
    """The AnnotationCollection (v2: Layer) of *kind* of a Document or a Component."""
    return _url(f"iiif/v{version}/{KINDS[kind]}/{resource_id}")


def page(resource_id, n, kind="analysis", version=3, only=None):
    """Page *n* (canvas position, 1-based) of a collection; *only* restricts it to those resource ids."""
    return restricted(f"{collection(resource_id, kind, version)}/page-{n}", only)


def restricted(page_id, only):
    """*page_id* restricted by ``?only=`` to the resource ids *only*, sorted; unchanged without them."""
    if not only:
        return page_id
    return page_id + "?only=" + ",".join(sorted(str(i) for i in only))


def content_state(resource_id, feature_id, download=False):
    """The published Content State of one zone; *download* asks for it as an attachment."""
    url = _url(f"iiif/v3/content-state/{resource_id}/{feature_id}")
    return f"{url}?download=1" if download else url


def explorer_manifest(query=""):
    """The Explorer manifest of the scope *query* (``ids=…``, ``document=…``, ``project=…``), language-free."""
    url = _url("iiif/v3/explorer-manifest")
    return f"{url}?{query}" if query else url


def explorer_part(scope_digest, *parts):
    """A resource the Explorer manifest of *scope_digest* creates (canvas pages, ranges); it need not dereference."""
    tail = "".join(f"/{quote(str(part), safe='')}" for part in parts)
    return _url(f"iiif/v3/explorer-manifest/{scope_digest}{tail}")


def selection_manifest(kind, resource_id):
    """The Explorer manifest of the Selection holding the whole analysis or identified material *resource_id*."""
    prefix = "ch" if kind == "characterization" else "an"
    return explorer_manifest(f"ids={prefix}:{resource_id}:-")


def data_raw(file_id):
    """The stored file, served with its true media type."""
    return _url(f"iiif/data/{file_id}/raw")


def data_series(file_id):
    """The clean CSV of a file."""
    return _url(f"iiif/data/{file_id}/series.csv")


def xy_context():
    return _url("iiif/context/xy-reading/1.jsonld")


def xy_doc():
    return _url("iiif/context/xy-reading/1")


def xy_schema():
    return _url("iiif/context/xy-reading/1/schema.json")


def auth_login():
    return _url("iiif/auth/login")


def auth_token(version):
    return _url(f"iiif/auth/{version}/token")


def auth_probe(file_id):
    return _url(f"iiif/auth/2/probe/{file_id}")


def auth_logout():
    return _url("iiif/auth/logout")


def report(resource_id):
    """The Arches report of a resource, as citations and exports name it."""
    return _url(f"report/{resource_id}")


def as_version(url, version):
    """One of our ``iiif/v3/…`` ids as the same resource of API *version*; any other URL unchanged."""
    prefix = _url("iiif/v3/")
    if isinstance(url, str) and url.startswith(prefix):
        return _url(f"iiif/v{version}/") + url[len(prefix) :]
    return url
