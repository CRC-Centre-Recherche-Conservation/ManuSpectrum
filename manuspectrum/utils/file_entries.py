"""Build and repair the file entries stored in ``file-list`` tile values.

A ``file-list`` node stores a **list** of file entries in one tile — the
instrument's own export kept for the record, plus the CSV derivative the XY
reader can plot, live side by side in a single measurement tile.

Each entry carries four localised metadata fields (``altText``, ``title``,
``attribution``, ``description``). The upload widget always fills them, and
hydrates any that are missing when it loads a tile
(``arches/app/media/js/viewmodels/file-widget.js``). Nothing on the server does
the same, and ``FileListDataType.append_to_document`` walks
``f[field].keys()`` unguarded — so a single entry whose metadata is ``None``
aborts the whole search reindex with::

    AttributeError: 'NoneType' object has no attribute 'keys'

Any code that writes a file entry without going through the widget — an
importer, a conversion workflow, a repair script — must therefore produce the
metadata itself. Use :func:`build_file_entry` to create one, or
:func:`normalize_metadata` to repair one, rather than assembling the dict by
hand: hand-assembly is how the malformed entries got there in the first place.
"""

from functools import lru_cache

from django.conf import settings

#: The localised metadata fields the search indexer walks on every file entry.
METADATA_FIELDS = ("altText", "title", "attribution", "description")


@lru_cache(maxsize=8)
def _text_direction(language_code):
    """Reading direction for a language, defaulting to left-to-right.

    Cached: this is called once per field per entry in bulk repairs, and the
    answer cannot change within a process.
    """
    from arches.app.models.models import Language

    try:
        return Language.objects.get(code=language_code).default_direction
    except Exception:
        # Unknown code, or no database yet (migrations, checks). Left-to-right
        # is right for every language this project ships.
        return "ltr"


def blank_localized_string(language_code=None):
    """An empty localised string, shaped as the upload widget writes it."""
    language_code = language_code or settings.LANGUAGE_CODE
    return {language_code: {"value": "", "direction": _text_direction(language_code)}}


def normalize_metadata(entry, language_code=None):
    """Fill in a file entry's missing localised metadata, in place.

    Only ever adds: a field that already holds a value is left untouched, so
    this is safe to run over curated data. Returns the number of fields filled,
    which lets callers skip a write when there was nothing to do.
    """
    if not isinstance(entry, dict):
        return 0

    language_code = language_code or settings.LANGUAGE_CODE
    filled = 0
    for field in METADATA_FIELDS:
        current = entry.get(field)
        if current is None or current == {}:
            entry[field] = blank_localized_string(language_code)
            filled += 1
        elif isinstance(current, dict) and language_code not in current:
            # Present in another language but not this one. The widget adds the
            # active language the same way rather than replacing what is there.
            current[language_code] = blank_localized_string(language_code)[
                language_code
            ]
            filled += 1
    return filled


def build_file_entry(
    *,
    file_id,
    name,
    path,
    size,
    content_type,
    index=0,
    last_modified=None,
    language_code=None,
    **extra,
):
    """Assemble a complete ``file-list`` entry.

    ``extra`` carries the renderer-related keys when the caller already knows
    them (``renderer``, ``rendererConfig``, ``rendererConfigSource``,
    ``parsingOverrides``); leaving them out is normal, since
    :mod:`manuspectrum.functions.xy_technique_config` fills them from the
    analysis technique when the tile is saved.
    """
    entry = {
        "url": f"/files/{file_id}",
        "name": name,
        "path": path,
        "size": size,
        "type": content_type,
        "index": index,
        "status": "uploaded",
        "accepted": True,
        "file_id": str(file_id),
        "lastModified": last_modified,
    }
    normalize_metadata(entry, language_code)
    entry.update(extra)
    return entry
