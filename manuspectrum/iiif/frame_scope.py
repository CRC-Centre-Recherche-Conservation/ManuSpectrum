"""Pure helpers of the ``annotation_frames`` verbs: the browser-measured frames file.

The file is written by the console script of ``verify --refused-out`` and read
by ``--frames``. Format::

    {"version": 1, "measured_at": "<ISO 8601>", "origin": "<https://host>",
     "frames": [{"service": "<id>", "info": {"width": int, "height": int,
                                              "tiles": [...]?, "tile_width": int?}}],
     "failed": [["<service>", "<reason>"]]}

``info`` holds raw ``info.json`` fields; ``units.info_from_json`` decides what
they mean.
"""

import json
from dataclasses import dataclass

from manuspectrum.iiif import units
from manuspectrum.views.explorer.values import rewrite_legacy_url

FRAMES_FILE_VERSION = 1


@dataclass(frozen=True)
class FramesFile:
    """The content of a frames file: usable image descriptions by service, and the services it could not measure."""

    frames: dict
    failed: list
    measured_at: str
    origin: str


def read_frames_file(path):
    """The ``FramesFile`` at *path*; ValueError, whose message is the reason, when the file cannot be used.

    Services are normalised with ``rewrite_legacy_url(...).rstrip("/")``. An
    entry that is not an image description is listed in ``failed`` with its
    reason, after the services the script itself could not measure.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            body = json.load(handle)
    except UnicodeDecodeError as error:
        raise ValueError(f"not UTF-8 text ({error})") from error
    except OSError as error:
        raise ValueError(f"cannot read the frames file: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"not JSON ({error})") from error
    if not isinstance(body, dict):
        raise ValueError("the frames file is not a JSON object")
    if body.get("version") != FRAMES_FILE_VERSION:
        raise ValueError(
            f"unsupported version {body.get('version')!r} (expected {FRAMES_FILE_VERSION})"
        )
    for key in ("measured_at", "origin"):
        if not isinstance(body.get(key), str) or not body[key]:
            raise ValueError(f"{key} is missing")
    entries = body.get("frames")
    if not isinstance(entries, list):
        raise ValueError("frames is not a list")
    failed = []
    for item in body.get("failed") or []:
        if (
            isinstance(item, (list, tuple))
            and len(item) == 2
            and all(isinstance(part, str) for part in item)
        ):
            failed.append((item[0], item[1]))
        else:
            raise ValueError("failed holds an entry that is not [service, reason]")
    found = {}
    for entry in entries:
        service = entry.get("service") if isinstance(entry, dict) else None
        if not isinstance(service, str) or not service:
            failed.append((str(service), "entry without a service"))
            continue
        service = rewrite_legacy_url(service).rstrip("/")
        info = units.info_from_json(entry.get("info"))
        if info is None:
            failed.append((service, "not an image description"))
            continue
        found[service] = info
    return FramesFile(found, failed, body["measured_at"], body["origin"])
