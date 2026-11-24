"""Which raw instrument file of a file list goes with which CSV.

One rule for the Data Lab (``views/explorer/values.file_entries``) and for the
measurement-file catalogue. A CSV here is a readable file (``is_readable``) that
is not itself a raw instrument file.
"""

import os

from manuspectrum.utils.spectrum_preview import is_raw_instrument, is_readable


def pair(entries):
    """``{raw file id: csv file id}`` for the entries of one file list.

    *entries* are file-list dicts (``file_id``, ``name``, optionally
    ``msSourceFileId``); entries without a ``file_id`` are ignored. Three passes,
    each skipping a file already paired:

    1. a CSV whose ``msSourceFileId`` names a file of the list;
    2. the whole raw name equals the CSV's base name (case ignored), the name the
       converters give: ``x.0`` and ``x.0.csv``;
    3. the raw file's base name equals the CSV's base name: ``x.mca`` and ``x.csv``.

    With two CSVs of one base name, the last one is the candidate.
    """
    items = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or not entry.get("file_id"):
            continue
        name = str(entry.get("name") or "")
        items.append(
            {
                "id": str(entry["file_id"]),
                "base": os.path.splitext(name)[0].casefold(),
                "name": name.casefold(),
                "raw": is_raw_instrument(name),
                "csv": is_readable(name) and not is_raw_instrument(name),
                "source": (
                    str(entry["msSourceFileId"])
                    if entry.get("msSourceFileId")
                    else None
                ),
            }
        )
    paired, taken = {}, set()

    def link(raw_id, csv_id):
        paired[raw_id] = csv_id
        taken.update((raw_id, csv_id))

    known = {item["id"] for item in items}
    for item in items:
        source = item["source"]
        if (
            item["csv"]
            and source in known
            and source != item["id"]
            and item["id"] not in taken
            and source not in taken
        ):
            link(source, item["id"])
    readable = {i["base"]: i for i in items if i["csv"]}
    raw_by_base = {i["base"]: i for i in items if i["raw"]}
    raw_by_name = {i["name"]: i for i in items if i["raw"]}
    for twins in (raw_by_name, raw_by_base):
        for base, item in readable.items():
            twin = twins.get(base)
            if twin is None or twin["id"] in taken or item["id"] in taken:
                continue
            link(twin["id"], item["id"])
    return paired
