"""The files behind the IIIF spectrum bodies: the read guard, the true media type and the clean CSV rule.

A file is read only through its ``File`` row, the tile that row hangs from
and that tile's resource: never from a path or an id written in tile data.
``file_allowed`` is the one guard of a file, shared with the spectrum
preview: the resource is in ``visible_set(reader)`` and the tile's nodegroup
is one ``readable_nodegroups`` lets through. ``readable_file`` returns None
for an unknown file and raises ``Refused`` when the file exists and the
reader may not read it.

A file has a clean CSV when ``read_series`` reads its format
(``is_readable``: a text format of ``XY_TEXT_FILE_FORMATS``; an instrument
format is served as its raw file only), it is no larger than ``SPECTRUM_PREVIEW_MAX_BYTES`` and its licence
allows derivatives; the route answers 404 besides when the file holds fewer
than two points. The clean CSV is never decimated, whatever its size:
mirador-xyviewer refuses a body over 5 MB, so such a file plots in the
Explorer and not there.
"""

import os
import re
from dataclasses import dataclass, field

from django.conf import settings

from arches.app.models.models import File

from manuspectrum.constants.licenses import effective_license
from manuspectrum.iiif.constants import MEDIA_TYPE_BY_EXTENSION, OCTET_STREAM
from manuspectrum.utils.public_visibility import visible_set
from manuspectrum.utils.spectrum_preview import is_readable
from manuspectrum.views.summary_service import readable_nodegroups

_MEDIA_TYPE = re.compile(r"^[a-z]+/[a-z0-9.+-]+$")


class Refused(Exception):
    """The file exists; the reader may not read it."""


@dataclass(frozen=True)
class FileRecord:
    """One stored file as its ``File`` row and tile give it.

    ``name`` is the name its tile's file-list entry gives it, else the stored
    file's base name; ``entry`` is that entry (licence, attribution,
    renderer configuration), ``{}`` when the tile lists it nowhere.
    """

    id: str
    path: str
    name: str
    size: int | None
    resource_id: str
    nodegroup_id: str
    config_id: str | None
    entry: dict = field(default_factory=dict)

    @property
    def media_type(self):
        return media_type(self.name, self.entry.get("type"))


def media_type(name, stored):
    """True media type of a file: by extension, else its stored type when it is a plain ``type/subtype``, else octet-stream.

    Raw instrument formats (``RAW_INSTRUMENT_EXTENSIONS``) are octet-stream;
    a ``text/x-*`` type is never trusted.
    """
    extension = os.path.splitext(name or "")[1].lower()
    if extension in MEDIA_TYPE_BY_EXTENSION:
        return MEDIA_TYPE_BY_EXTENSION[extension]
    if extension in {e.lower() for e in settings.RAW_INSTRUMENT_EXTENSIONS}:
        return OCTET_STREAM
    stored = str(stored or "").strip().lower()
    if _MEDIA_TYPE.match(stored) and not stored.startswith("text/x-"):
        return stored
    return OCTET_STREAM


def file_allowed(resource_id, nodegroup_id, reader):
    """Whether *reader* may read a file of *resource_id* held in a tile of *nodegroup_id*."""
    if str(resource_id) not in visible_set(reader).ids:
        return False
    nodegroups = readable_nodegroups(reader)
    return nodegroups is None or str(nodegroup_id) in nodegroups


def file_entry(data, file_id):
    """The file-list entry of *file_id* in a tile's data, ``{}`` when none lists it."""
    wanted = str(file_id).lower()
    for values in (data or {}).values():
        for entry in values if isinstance(values, list) else []:
            if (
                isinstance(entry, dict)
                and str(entry.get("file_id", "")).lower() == wanted
            ):
                return entry
    return {}


def file_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return None


def readable_file(file_id, reader):
    """The ``FileRecord`` of *file_id* for *reader*; None when unknown, ``Refused`` raised when not readable."""
    row = (
        File.objects.filter(pk=file_id)
        .defer("thumbnail_data")
        .select_related("tile")
        .first()
    )
    if row is None or not row.path.name or row.tile is None:
        return None
    resource_id = str(row.tile.resourceinstance_id)
    nodegroup_id = str(row.tile.nodegroup_id)
    if not file_allowed(resource_id, nodegroup_id, reader):
        raise Refused(file_id)
    entry = file_entry(row.tile.data, file_id)
    path = row.path.path
    return FileRecord(
        id=str(row.fileid),
        path=path,
        name=str(entry.get("name") or os.path.basename(row.path.name)),
        size=file_size(path),
        resource_id=resource_id,
        nodegroup_id=nodegroup_id,
        config_id=entry.get("rendererConfig") or None,
        entry=entry,
    )


def no_derivatives(entry):
    """Whether the licence of a file entry forbids derivatives."""
    return effective_license(entry, settings.LANGUAGE_CODE)["noDerivatives"]


def clean_series_available(file):
    """Whether *file* (a ``FileRecord`` or ``facts.FileFact``) has a clean CSV."""
    return (
        is_readable(file.name)
        and file.size is not None
        and file.size <= settings.SPECTRUM_PREVIEW_MAX_BYTES
        and not no_derivatives(file.entry)
    )
