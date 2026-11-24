"""Format detection by content, and the one entry point `convert`.

`READERS` holds the content-signed formats in detection order; each reader
module has `FORMAT`, `READER_VERSION`, `sniff(head)` and `read(data)`. A new
reader goes into `READERS`, never after the fallback. A known format without a
reader is named in `KNOWN_UNREAD`. `FALLBACK` (plain text columns) is tried
last, after `KNOWN_UNREAD`, so a known unread format never falls into it. File
names and extensions are never read.
"""

import logging

from . import bruker_spx, delimited, elio_mca
from .base import MAX_CHANNELS, Reading, UnreadableFile, UnsupportedFormat

logger = logging.getLogger(__name__)

HEAD_SIZE = 4096


READERS = (bruker_spx, elio_mca)
FALLBACK = delimited

KNOWN_UNREAD = {
    "amptek_mca": lambda head: b"<<PMCA SPECTRUM>>" in head,
    "renishaw_wdf": lambda head: head.startswith(b"WDF1"),
}


def detect(data: bytes) -> str | None:
    head = data[:HEAD_SIZE]
    for reader in READERS:
        if reader.sniff(head):
            return reader.FORMAT
    for name, matches in KNOWN_UNREAD.items():
        if matches(head):
            return name
    if FALLBACK.sniff(head):
        return FALLBACK.FORMAT
    return None


def convert(data: bytes) -> Reading:
    """Read `data`; raises `UnsupportedFormat` or `UnreadableFile` only."""
    name = detect(data)
    if name is None or name in KNOWN_UNREAD:
        raise UnsupportedFormat(name)
    reader = next(r for r in (*READERS, FALLBACK) if r.FORMAT == name)
    try:
        return reader.read(data)
    except (UnreadableFile, UnsupportedFormat):
        raise
    except Exception as error:
        logger.warning("%s reader failed: %s", name, type(error).__name__)
        raise UnreadableFile("malformed") from None
