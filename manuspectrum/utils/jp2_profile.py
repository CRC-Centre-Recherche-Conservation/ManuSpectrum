"""Encoding check for JPEG 2000 deposits, read from the headers only.

Cantaloupe decodes a JP2 with one ``opj_decompress`` subprocess per request. A
file of one level of resolution, or a large one made of a single tile, costs
hundreds of megabytes per decode, so ``check_upload`` refuses those at the
door. It reads the JP2 signature and ``jp2c`` box, then the codestream main
header (SIZ: image and tile size; COD: decomposition levels) in a few hundred
bytes, never the pixels, from any seekable binary file (an uploaded file
included). COC and tile-part headers are not read.

Rules, from ``settings``:

- ``JP2_MIN_RESOLUTION_LEVELS``: above 4 megapixels a file needs at least this
  many resolution levels (decomposition levels + 1);
- ``JP2_MAX_TILE_PIXELS``: a file whose tiles (clipped to the image) hold more
  pixels than this is refused; a file of one tile covering the image is the
  largest case.

Cantaloupe picks the processor from the file extension, so a file that starts
with the JP2 signature under another name is refused too.
"""

import math
import os
import struct
from dataclasses import dataclass

from django.conf import settings
from django.utils.html import escape
from django.utils.translation import gettext as _, ngettext

LEVELS_CHECK_ABOVE_PIXELS = 4_000_000
RECOMMENDED_COMMAND = (
    'opj_compress -i in.tif -o out.jp2 -n 7 -t 1024,1024 -c "[256,256]" '
    '-b "64,64" -p RPCL -SOP -PLT -TP R'
)

SIGNATURE_BOX = b"\x00\x00\x00\x0cjP  \r\n\x87\n"
SOC, SIZ, COD, SOT, EOC = 0xFF4F, 0xFF51, 0xFF52, 0xFF90, 0xFFD9
SIZ_MIN_LENGTH = 38
MAX_BOXES = 64
MAX_MARKER_SEGMENTS = 64


class InvalidJp2(Exception):
    """The bytes are not a readable JPEG 2000 file (wrong format, truncated, damaged)."""


@dataclass(frozen=True)
class Jp2Profile:
    width: int
    height: int
    tile_width: int
    tile_height: int
    decomposition_levels: int

    @property
    def resolution_levels(self):
        return self.decomposition_levels + 1

    @property
    def pixels(self):
        return self.width * self.height

    @property
    def tile_pixels(self):
        """Pixels of one tile, clipped to the image."""
        return min(self.tile_width, self.width) * min(self.tile_height, self.height)


def _read(fileobj, size):
    data = fileobj.read(size)
    if len(data) != size:
        raise InvalidJp2("truncated")
    return data


def _find_codestream(fileobj):
    """Position ``fileobj`` on the first byte of the ``jp2c`` box content.

    A ``jp2h`` box must come first, as the standard requires.
    """
    fileobj.seek(0, 2)
    end = fileobj.tell()
    fileobj.seek(0)
    if _read(fileobj, 12) != SIGNATURE_BOX:
        raise InvalidJp2("signature")
    position = 12
    header_seen = False
    for _index in range(MAX_BOXES):
        fileobj.seek(position)
        length, box_type = struct.unpack(">I4s", _read(fileobj, 8))
        header = 8
        if length == 1:
            (length,) = struct.unpack(">Q", _read(fileobj, 8))
            header = 16
        elif length == 0:
            length = end - position
        if length < header:
            raise InvalidJp2("box")
        if box_type == b"jp2h":
            header_seen = True
        if box_type == b"jp2c":
            if not header_seen:
                raise InvalidJp2("no jp2h")
            fileobj.seek(position + header)
            return
        position += length
        if position >= end:
            break
    raise InvalidJp2("no codestream")


def read_profile(fileobj):
    """Read the encoding profile of a JP2 stream; raise ``InvalidJp2`` if unreadable."""
    try:
        _find_codestream(fileobj)
        if struct.unpack(">H", _read(fileobj, 2))[0] != SOC:
            raise InvalidJp2("soc")
        marker, siz_length = struct.unpack(">HH", _read(fileobj, 4))
        if marker != SIZ or siz_length < SIZ_MIN_LENGTH:
            raise InvalidJp2("siz")
        (
            _rsiz,
            xsiz,
            ysiz,
            xosiz,
            yosiz,
            xtsiz,
            ytsiz,
            _xtosiz,
            _ytosiz,
        ) = struct.unpack(">HIIIIIIII", _read(fileobj, 34))
        _read(fileobj, siz_length - SIZ_MIN_LENGTH + 2)
        levels = None
        for _index in range(MAX_MARKER_SEGMENTS):
            marker, length = struct.unpack(">HH", _read(fileobj, 4))
            if marker in (SOT, EOC) or marker >> 8 != 0xFF or length < 2:
                break
            body = _read(fileobj, length - 2)
            if marker == COD:
                if len(body) < 6:
                    raise InvalidJp2("cod")
                levels = body[5]
                break
        if levels is None:
            raise InvalidJp2("cod")
    except (struct.error, OverflowError) as error:
        raise InvalidJp2("header") from error
    width, height = xsiz - xosiz, ysiz - yosiz
    if width <= 0 or height <= 0 or xtsiz <= 0 or ytsiz <= 0 or levels > 32:
        raise InvalidJp2("values")
    return Jp2Profile(
        width=width,
        height=height,
        tile_width=xtsiz,
        tile_height=ytsiz,
        decomposition_levels=levels,
    )


@dataclass(frozen=True)
class Refusal:
    message: str
    advise_encoding: bool = False


def _megapixels(pixels):
    """Megapixels rounded up to one decimal, so a refusal never reads as the limit."""
    return f"{math.ceil(pixels / 100_000) / 10:.1f}"


def check_upload(name, fileobj):
    """Return the ``Refusal`` of a ``.jp2`` deposit, or None when it may be served.

    ``name`` is escaped in the message: the plugin page renders alert text as HTML.
    """
    shown = escape(name)
    try:
        profile = read_profile(fileobj)
    except InvalidJp2:
        return Refusal(
            _(
                '"{name}" is not a valid JPEG 2000 file (wrong format, truncated or damaged).'
            ).format(name=shown)
        )
    finally:
        fileobj.seek(0)
    minimum = getattr(settings, "JP2_MIN_RESOLUTION_LEVELS", 5)
    tile_max = getattr(settings, "JP2_MAX_TILE_PIXELS", 20_000_000)
    if (
        profile.pixels > LEVELS_CHECK_ABOVE_PIXELS
        and profile.resolution_levels < minimum
    ):
        return Refusal(
            ngettext(
                '"{name}" cannot be served efficiently: it has {levels} resolution level, at least {minimum} are required.',
                '"{name}" cannot be served efficiently: it has {levels} resolution levels, at least {minimum} are required.',
                profile.resolution_levels,
            ).format(name=shown, levels=profile.resolution_levels, minimum=minimum),
            advise_encoding=True,
        )
    if profile.tile_pixels > tile_max:
        return Refusal(
            _(
                '"{name}" cannot be served efficiently: it has tiles of {megapixels} MP (at most {limit} MP). Encode it with 1024 × 1024 tiles.'
            ).format(
                name=shown,
                megapixels=_megapixels(profile.tile_pixels),
                limit=_megapixels(tile_max),
            ),
            advise_encoding=True,
        )
    return None


def check_deposit(files):
    """Return one translated refusal message for the uploaded ``files``, or None.

    Every file is sniffed on its first 12 bytes: a file that starts with the JP2
    signature is refused unless it is named ``.jp2``, and a ``.jp2`` goes through
    ``check_upload``. The recommended command closes the message once.
    """
    refusals = []
    for upload in files:
        name = upload.name
        named_jp2 = os.path.splitext(name)[1].lower() == ".jp2"
        signed = upload.read(len(SIGNATURE_BOX)) == SIGNATURE_BOX
        upload.seek(0)
        if named_jp2:
            refusal = check_upload(name, upload)
        elif signed:
            refusal = Refusal(
                _(
                    '"{name}" is a JPEG 2000 file but is not named .jp2: rename it with the .jp2 extension.'
                ).format(name=escape(name))
            )
        else:
            refusal = None
        if refusal:
            refusals.append(refusal)
    if not refusals:
        return None
    messages = [refusal.message for refusal in refusals]
    if any(refusal.advise_encoding for refusal in refusals):
        messages.append(
            _("Recommended lossless encoding: {command}").format(
                command=RECOMMENDED_COMMAND
            )
        )
    return " ".join(messages)
