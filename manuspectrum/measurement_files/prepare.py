"""Background preparation of a measurement-files run.

``prepare_run`` takes one chunk of ``queued`` items, converts and reads each
(``prepare_item``), and returns whether items remain; the Celery task
``manuspectrum.measurement_prepare`` and the management command both call it.
The Analyses of the Document are read once, when the first chunk runs, into
``catalogue.json`` of the run's staging directory and reused by every chunk
(the writer re-checks rights later). When no item is left, ``finish_run``
pairs the CSV files the lab dropped next to the raws (decision 21), computes
the causes that need the whole run (``already_provided``, ``same_target``),
settles every decision and moves the run to ``review``.

An item is ``ready`` only with a proposed Analysis, no cause and something to
write; otherwise it is ``pending`` (a cause or a missing choice) or ``aside``
(already in the database, not a measurement, a lab CSV, a CSV that breaks the
contract). A chunk that raises releases the items it had not reached, and the
item that raised becomes ``failed`` (error ``prepare``), so a poison file is
never retried.
"""

import dataclasses
import json
import logging
import os
import tempfile
from collections import defaultdict

from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from arches.app.models.models import File

from manuspectrum.constants.xy_presets import XY_PRESETS
from manuspectrum.measurement_files import catalogue, matching, staging
from manuspectrum.measurement_files.converters import (
    UnreadableFile,
    UnsupportedFormat,
    check_csv,
    convert,
    csv_name,
    fits_viewer,
    write_csv,
)
from manuspectrum.measurement_files.converters.metadata import describe
from manuspectrum.measurement_files.intake import CLAIM_STALE
from manuspectrum.models import MeasurementItem, MeasurementNameCode, MeasurementRun
from manuspectrum.views.explorer.service import Values, shelfmark as explorer_shelfmark

logger = logging.getLogger(__name__)

CATALOGUE_FILE = "catalogue.json"
CONVERTED_SUFFIX = "converted.csv"
DESCRIPTION_SUFFIX = "description.json"
UNCONVERTED = ("unreadable", "unsupported")
CONVERTED = ("csv", "raw_only")
SOFT_CAUSES = ("", "content_vs_display", "no_display")


def claim(run, states, limit, **filters):
    """Take up to *limit* items of *run* for this worker; returns them as ``claimed``.

    An item is free when its ``state`` is in *states* or when it is
    ``claimed`` for more than ``CLAIM_STALE``; rows another transaction holds
    are skipped. *filters* narrow the query further.
    """
    now = timezone.now()
    with transaction.atomic():
        items = list(
            MeasurementItem.objects.select_for_update(skip_locked=True)
            .filter(run=run, **filters)
            .filter(
                Q(state__in=states)
                | Q(state="claimed", claimed_at__lt=now - CLAIM_STALE)
            )
            .order_by("relative_dir", "source_name", "id")[:limit]
        )
        MeasurementItem.objects.filter(pk__in=[i.pk for i in items]).update(
            state="claimed", claimed_at=now
        )
    for item in items:
        item.state, item.claimed_at = "claimed", now
    return items


def document_shelfmark(document_id, user, language):
    """The Document's shelfmark: the identifier typed as one, else its first non-link identifier; ``""`` without any."""
    document_id = str(document_id)
    values = Values([document_id], ["doc_identifier", "doc_identifier_type"], user)
    node = values.node("doc_identifier")
    if node is None:
        return ""
    found = explorer_shelfmark(
        values.tiles(document_id, "doc_identifier"),
        node,
        values.node("doc_identifier_type"),
        language,
    )
    return found["value"] if found else ""


def _cards_to_json(cards):
    return [dataclasses.asdict(card) for card in cards]


def _cards_from_json(rows):
    return [
        catalogue.AnalysisCard(
            **{
                **row,
                "technique_ids": tuple(row["technique_ids"]),
                "folio_sources": tuple(row["folio_sources"]),
                "projects": tuple(row["projects"]),
                "files": tuple(catalogue.StoredFile(**f) for f in row["files"]),
            }
        )
        for row in rows
    ]


def _snapshot_path(run):
    return staging.run_dir(run.id) / CATALOGUE_FILE


def load_snapshot(run):
    """``(cards, shelfmark)`` of the run, read from ``catalogue.json`` or computed and stored once.

    A Document the user can no longer read gives no cards: every item then
    waits for a choice, and the writer refuses it anyway.
    """
    path = _snapshot_path(run)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        try:
            cards = catalogue.document_analyses(
                run.document_id, run.user, run.project_id
            )
            shelfmark = document_shelfmark(run.document_id, run.user, run.language)
        except PermissionDenied:
            cards, shelfmark = [], ""
        data = {"shelfmark": shelfmark, "cards": _cards_to_json(cards)}
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.chmod(tmp, 0o640)
        os.replace(tmp, path)
    return _cards_from_json(data["cards"]), data["shelfmark"]


def _load_bytes(item):
    if item.origin == "upload":
        return staging.read(item.run_id, item.staged_name)
    row = File.objects.filter(pk=item.source_file_id).first()
    if row is None or not row.path:
        raise FileNotFoundError(str(item.source_file_id))
    with row.path.open("rb") as handle:
        return handle.read()


def _is_csv_name(name):
    return name.lower().endswith(".csv")


def _format_key(name):
    extension = os.path.splitext(name)[1].lstrip(".").lower()
    return "opus" if extension.isdigit() else extension


def _convert(item, data):
    """Fill the conversion fields of *item* from its bytes; returns the content family or None."""
    try:
        reading = convert(data)
    except UnsupportedFormat as error:
        if error.format is None:
            item.outcome, item.reason = "not_measure", "no_reader"
        else:
            item.outcome, item.reason = "unsupported", "no_reader"
            item.detected_format = error.format
        return None
    except UnreadableFile as error:
        item.outcome, item.reason = "unreadable", error.code
        item.detected_format = error.format or ""
        return None
    item.detected_format = reading.format
    item.content_preset = reading.content_preset or ""
    item.facts = [
        {"key": f.key, "value": f.value, "unit": f.unit} for f in reading.facts
    ]
    item.warnings = list(reading.warnings)
    if reading.series is None:
        item.outcome, item.reason = "raw_only", "no_series"
        return reading.content_preset
    csv_bytes = write_csv(reading.series)
    if not fits_viewer(csv_bytes):
        item.outcome, item.reason = "raw_only", "too_large"
        return reading.content_preset
    item.outcome, item.reason = "csv", ""
    staging.store(item.run_id, item.id, csv_bytes, CONVERTED_SUFFIX)
    description = describe(reading, source_name=item.source_name, sha256=item.sha256)
    staging.store(
        item.run_id,
        item.id,
        json.dumps(description, ensure_ascii=False).encode("utf-8"),
        DESCRIPTION_SUFFIX,
    )
    return reading.content_preset


def _check_lone_csv(item, data):
    item.detected_format = "csv"
    codes = check_csv(data)
    if codes:
        item.outcome, item.reason = "unreadable", codes[0]
        item.decision, item.cause = "aside", "csv_contract"
    else:
        item.outcome, item.reason = "csv", ""


def _in_database(item, cards, target, hashes):
    """Whether a file of an Analysis already holds these bytes.

    Every card is checked by the source hash its converted CSV recorded
    (``msSourceSha256``, no bytes read); the target card's own files are
    hashed, once each per chunk (*hashes* memoises).
    """
    for card in cards:
        if any(f.sha256 == item.sha256 for f in card.files):
            return True
    if target is None:
        return False
    for stored in target.files:
        if str(stored.file_id) == str(item.source_file_id):
            continue
        if stored.file_id not in hashes:
            hashes[stored.file_id] = catalogue.stored_sha256(stored.file_id)
        if hashes[stored.file_id] == item.sha256:
            return True
    return False


def _display(card, content_preset):
    """``(config id, source, cause)`` of the display proposed for *card*.

    The technique's display by default; the converter's channel display for a
    file without calibration on an XRF (or unconfigured) Analysis; the cause
    ``content_vs_display`` when the file says another quantity of the same
    family, ``no_display`` when the technique gives no single display.
    """
    technique = card.technique_preset if card else None
    if content_preset == "xrf_channel" and (
        technique is None or matching.family_of(technique) == "xrf"
    ):
        return XY_PRESETS["xrf_channel"]["config_id"], "converter", None
    if technique is None:
        return None, "none", "no_display" if card else None
    cause = None
    if (
        content_preset
        and content_preset != technique
        and matching.family_of(content_preset) == matching.family_of(technique)
    ):
        cause = "content_vs_display"
    return XY_PRESETS[technique]["config_id"], "technique", cause


def apply_target(item, card):
    """Set the display (and its cause) of a ``csv`` item for the Analysis *card*."""
    if item.outcome != "csv":
        item.display_config_id, item.display_source = None, "none"
        return
    config_id, source, cause = _display(card, item.content_preset)
    item.display_config_id, item.display_source = config_id, source
    if cause and not item.cause:
        item.cause = cause


def has_something_to_write(item):
    """A CSV, a raw file kept alone (upload) or an unreadable raw file paired with its CSV."""
    return bool(
        item.outcome == "csv"
        or (item.outcome == "raw_only" and item.origin == "upload")
        or (item.outcome in UNCONVERTED and item.paired_item_id)
    )


def settle(item):
    """Set ``decision`` of an item not set aside: ``ready`` with a target (the chosen Analysis, else the proposed one), no cause and something to write."""
    if item.decision == "aside":
        return
    target = item.chosen_analysis_id or item.proposed_analysis_id
    ok = target and not item.cause and has_something_to_write(item)
    item.decision = "ready" if ok else "pending"


def _set_aside(item, cause):
    item.decision, item.cause = "aside", cause
    item.proposed_analysis_id = None


def propose_item(item, cards, codes, shelfmark, content_family, hashes):
    """Read the name of *item* and propose its Analysis, cause and display.

    Works on the facts already on the item (no conversion): ``prepare_item``
    calls it after converting, and ``decisions.validate_codes`` calls it again
    once the dictionary changed. A stored item keeps its Analysis
    (``source_analysis_id``); an uploaded one is matched by
    ``matching.propose``.
    """
    by_id = {c.id: c for c in cards}
    reading = matching.read_name(item.source_name, item.relative_dir, shelfmark, codes)
    item.tokens = [
        {"piece": t.piece, "meaning": t.meaning, "source": t.source}
        for t in reading.tokens
    ]
    if item.origin == "stored":
        item.proposed_analysis_id = item.source_analysis_id
        card = by_id.get(str(item.source_analysis_id))
        card_family = matching.family_of(card.technique_preset) if card else None
        family = matching.family_of(content_family)
        if card_family and family and card_family != family:
            item.cause = "format_vs_technique"
    else:
        proposal = matching.propose(reading, content_family, cards, codes, shelfmark)
        item.proposed_analysis_id = proposal.analysis_id
        item.cause = proposal.cause or ""
    card = by_id.get(str(item.proposed_analysis_id))
    if item.outcome == "raw_only" and item.reason == "too_large":
        item.cause = item.cause or "too_large"
    if _in_database(item, cards, card, hashes):
        _set_aside(item, "in_database")
    else:
        apply_target(item, card)
        if item.outcome == "raw_only" and item.origin == "stored":
            item.decision = "aside"


def prepare_item(item, cards, codes, shelfmark="", hashes=None):
    """Convert, read and match one item, then save it as ``prepared``.

    Stores ``<item id>-converted.csv`` and ``<item id>-description.json`` in
    the run's staging directory for a converted file. A ``.csv`` is checked
    against the CSV contract (decision 21 pairing comes later, in
    ``finish_run``). A stored item keeps its Analysis (``source_analysis_id``);
    an uploaded one is matched by ``matching.propose``. Bytes that cannot be
    read leave the item ``failed`` with error ``missing``.
    """
    hashes = {} if hashes is None else hashes
    try:
        data = _load_bytes(item)
    except (OSError, ValueError):
        item.state, item.error = "failed", "missing"
        item.save()
        return
    content_family = None
    if _is_csv_name(item.source_name):
        _check_lone_csv(item, data)
    else:
        content_family = _convert(item, data)
    if item.outcome == "not_measure":
        _set_aside(item, "not_measure")
    elif item.decision != "aside":
        propose_item(item, cards, codes, shelfmark, content_family, hashes)
    settle(item)
    item.state = "prepared"
    item.save()


def _release(items):
    MeasurementItem.objects.filter(
        pk__in=[i.pk for i in items], state="claimed"
    ).update(state="queued", claimed_at=None)


def _remaining(run):
    return run.items.filter(state__in=("queued", "claimed")).exists()


def prepare_run(run, *, chunk=None):
    """Prepare one chunk of *run* synchronously; returns whether items remain.

    ``False`` when the run is not ``preparing``, or once nothing is left and
    the run has moved to ``review``. A raising item becomes ``failed``, the
    unreached items of the chunk go back to ``queued`` and the exception is
    raised again (a soft time limit releases the item that was running too).
    """
    run.refresh_from_db()
    if run.state != "preparing":
        return False
    cards, shelfmark = load_snapshot(run)
    codes = {
        c.code: c.family for c in MeasurementNameCode.objects.filter(user=run.user)
    }
    items = claim(run, ("queued",), chunk or settings.MEASUREMENT_PREPARE_CHUNK)
    hashes = {}
    for index, item in enumerate(items):
        try:
            prepare_item(item, cards, codes, shelfmark, hashes)
        except SoftTimeLimitExceeded:
            _release(items[index:])
            raise
        except Exception:
            logger.exception("measurement item preparation failed")
            MeasurementItem.objects.filter(pk=item.pk).update(
                state="failed", error="prepare"
            )
            _release(items[index + 1 :])
            raise
    if _remaining(run):
        return True
    finish_run(run, cards)
    return False


def _twin_names(raw_name):
    base = os.path.splitext(raw_name)[0]
    return {csv_name(raw_name).casefold(), f"{base}.csv".casefold()}


def _pair_csv_files(items, by_id):
    raws = defaultdict(list)
    for item in items:
        if not _is_csv_name(item.source_name) and item.state == "prepared":
            raws[item.relative_dir].append(item)
    for csv in (
        i for i in items if _is_csv_name(i.source_name) and i.state == "prepared"
    ):
        twins = [
            r
            for r in raws[csv.relative_dir]
            if csv.source_name.casefold() in _twin_names(r.source_name)
        ]
        converted = next((r for r in twins if r.outcome in CONVERTED), None)
        unread = next((r for r in twins if r.outcome in UNCONVERTED), None)
        if converted is not None:
            _set_aside(csv, "lab_csv_set_aside")
            csv.paired_item = converted
        elif unread is not None and csv.outcome == "csv" and csv.decision != "aside":
            target = unread.proposed_analysis_id or csv.proposed_analysis_id
            csv.paired_item, unread.paired_item = unread, csv
            csv.proposed_analysis_id = unread.proposed_analysis_id = target
            csv.cause = "" if target else (unread.cause or csv.cause)
            apply_target(csv, by_id.get(str(target)))
            unread.cause = csv.cause


def _already_provided(item, card):
    """Whether *card* already holds a file of the format of an uploaded *item* (same kind: raw or CSV)."""
    if item.origin == "stored" or card is None:
        return False
    key = _format_key(item.source_name)
    raw = not _is_csv_name(item.source_name)
    return any(f.is_raw == raw and _format_key(f.name) == key for f in card.files)


def finish_run(run, cards=None):
    """Pair lab CSV files, compute run-wide causes, settle decisions, move *run* to ``review``.

    Idempotent and guarded: only a run still ``preparing`` is touched, under a
    row lock.
    """
    if cards is None:
        cards, _ = load_snapshot(run)
    by_id = {c.id: c for c in cards}
    with transaction.atomic():
        locked = MeasurementRun.objects.select_for_update().get(pk=run.pk)
        if locked.state != "preparing":
            return
        items = list(
            run.items.filter(state="prepared").order_by(
                "relative_dir", "source_name", "id"
            )
        )
        _pair_csv_files(items, by_id)
        live = [i for i in items if i.decision != "aside"]
        for item in live:
            if item.proposed_analysis_id and item.cause in SOFT_CAUSES:
                if _already_provided(item, by_id.get(str(item.proposed_analysis_id))):
                    item.cause = "already_provided"
        groups = defaultdict(list)
        for item in live:
            paired_raw = item.paired_item_id and not _is_csv_name(item.source_name)
            if item.proposed_analysis_id and not paired_raw:
                groups[str(item.proposed_analysis_id)].append(item)
        for members in groups.values():
            if len(members) > 1 and any(m.origin == "upload" for m in members):
                for member in members:
                    if member.origin == "upload" and member.cause in SOFT_CAUSES:
                        member.cause = "same_target"
        for item in items:
            if (
                item.outcome in UNCONVERTED
                and not item.paired_item_id
                and item.decision == "pending"
                and not item.cause
            ):
                item.cause = "unreadable_raw"
            settle(item)
            item.save()
        MeasurementRun.objects.filter(pk=run.pk, state="preparing").update(
            state="review"
        )
    run.refresh_from_db()
