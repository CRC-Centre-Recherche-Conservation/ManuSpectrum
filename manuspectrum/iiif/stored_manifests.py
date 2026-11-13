"""The read guard of the stored manifests served at ``ids.stored_manifest``.

A stored manifest (Arches' ``IIIFManifest``) is not a resource: Arches' own
``/manifest/<uuid>`` serves any of them to anyone. The IIIF route serves a
manifest only when a tile of a naming role names it
(``sources.local_manifest_id`` of any URL of the tile value): an imaging tile
of an analysis of ``visible_set(reader).analyses`` or a source-manifest tile
of a Document of ``visible_set(reader).documents``, in a nodegroup of
``readable_nodegroup_ids(reader)``. This covers every manifest the IIIF output
names, and the further manifests such tiles hold. That is the rule
``data.file_allowed`` applies to the tile holding a stored file. Any other
manifest, and an unknown id, gives None: a bodyless 404, as for a Document
the reader may not see.
"""

from arches.app.models.models import IIIFManifest, TileModel

from manuspectrum.iiif.sources import local_manifest_id, original_url
from manuspectrum.utils.public_visibility import readable_nodegroup_ids, visible_set
from manuspectrum.utils.role_links import role_node
from manuspectrum.utils.roles import ROLES

# (role of a node naming a stored manifest, the ``VisibleSet`` set its
# resource must be in)
NAMING_ROLES = (("imaging", "analyses"), ("doc_manifest", "documents"))


def tile_urls(value):
    """The URLs a manifest tile value holds: a string, a ``{"url": …}`` object, or a list of them."""
    for item in value if isinstance(value, list) else [value]:
        url = item.get("url") if isinstance(item, dict) else item
        if isinstance(url, str) and url:
            yield url


def named_for(globalid, reader, version=None):
    """Whether a resource *reader* may see names the stored manifest *globalid* in a tile it may read.

    The tiles of each naming role are narrowed in the database to those whose
    value holds the id as text, then each URL is read as the IIIF output
    reads it. *version* is the ``data_version()`` the request read, else read
    here.
    """
    globalid = str(globalid)
    visible = visible_set(reader, version)
    readable = readable_nodegroup_ids(reader)
    for role, kind in NAMING_ROLES:
        node = role_node(*ROLES[role])
        if node is None or node.nodegroup_id not in readable:
            continue
        shown = getattr(visible, kind)
        rows = TileModel.objects.filter(
            nodegroup_id=node.nodegroup_id,
            **{f"data__{node.nodeid}__icontains": globalid},
        ).values_list("resourceinstance_id", f"data__{node.nodeid}")
        for resource_id, value in rows:
            if str(resource_id) in shown and any(
                local_manifest_id(url) == globalid for url in tile_urls(value)
            ):
                return True
    return False


def readable_manifest(globalid, reader, version=None):
    """``(stored JSON, original URL)`` of the manifest *globalid* for *reader*; None when it is unknown, not a JSON object, or not ``named_for`` the reader.

    The original URL is the publisher's (``sources.original_url`` of the row's
    ``url``), None for a manifest created here. The row is read once.
    """
    if not named_for(globalid, reader, version):
        return None
    row = (
        IIIFManifest.objects.filter(globalid=globalid)
        .values_list("manifest", "url")
        .first()
    )
    if row is None or not isinstance(row[0], dict):
        return None
    return row[0], original_url(row[1])
