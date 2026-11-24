"""Measurement-files batch API, parts 1 and 2: runs, uploads, stored files, prepare, review.

Back-office endpoints for Resource Editors, below the language boundary. A run
is visible only to its creator (a bodyless 404 otherwise). Errors carry a
reason code, never a translated sentence. Request bounds are checked from
``Content-Length`` before the body is read, then again on what was received.
"""

import json
import unicodedata
import uuid

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseNotFound, JsonResponse
from django.db import transaction
from django.utils import timezone, translation
from django.utils.cache import patch_cache_control
from django.utils.decorators import method_decorator
from django.utils.translation import gettext
from django.views import View

from arches.app.utils.decorators import group_required

from manuspectrum.constants.measurement_files import CAUSES, ITEM_STATES
from manuspectrum.constants.xy_presets import XY_PRESETS
from manuspectrum.measurement_files import catalogue, decisions, intake, matching
from manuspectrum.measurement_files import prepare, staging, undo, writer
from manuspectrum.measurement_files.converters.base import UNREADABLE_LABELS
from manuspectrum.models import (
    MeasurementItem,
    MeasurementNameCode,
    MeasurementRun,
    RendererConfig,
)

RECENT_ITEMS = 20
ITEMS_PER_PAGE = 200


def _json(payload, status=200):
    response = JsonResponse(payload, status=status, safe=False)
    patch_cache_control(response, private=True, no_store=True)
    return response


def _error(reason, status):
    return _json({"error": reason}, status)


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _body(request):
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _item(item):
    return {
        "id": str(item.id),
        "origin": item.origin,
        "name": item.source_name,
        "relative_dir": item.relative_dir,
        "size": item.size,
        "sha256": item.sha256,
        "state": item.state,
        "outcome": item.outcome,
    }


def _run(run):
    return {
        "id": str(run.id),
        "state": run.state,
        "document_id": str(run.document_id),
        "project_id": str(run.project_id) if run.project_id else None,
        "language": run.language,
    }


def _rejections(rejected):
    return [{"name": r.name, "reason": r.reason} for r in rejected]


def _counts(run):
    counts = {state: 0 for state in ITEM_STATES}
    for item_state in run.items.values_list("state", flat=True):
        counts[item_state] += 1
    counts["total"] = sum(counts.values())
    return counts


@method_decorator(
    group_required("Resource Editor", raise_exception=True), name="dispatch"
)
class RunBase(View):
    def own_run(self, request, run_id):
        run = MeasurementRun.objects.filter(pk=run_id, user=request.user).first()
        return run


class RunCreateView(RunBase):
    """201 for a new run, 200 when the same user repeats a ``workflow_id`` (idempotent)."""

    def post(self, request):
        data = _body(request)
        if data is None:
            return _error("bad_request", 400)
        workflow_id = _uuid(data.get("workflow_id"))
        document_id = _uuid(data.get("document_id"))
        project_raw = data.get("project_id")
        project_id = _uuid(project_raw) if project_raw else None
        language = data.get("language")
        if (
            workflow_id is None
            or document_id is None
            or (project_raw and project_id is None)
            or language not in {code for code, _ in settings.LANGUAGES}
        ):
            return _error("bad_request", 400)
        existing = MeasurementRun.objects.filter(pk=workflow_id).first()
        if existing is not None:
            if existing.user_id != request.user.pk:
                return HttpResponseNotFound()
            return _json({"run": _run(existing)}, 200)
        try:
            cards = catalogue.document_analyses(document_id, request.user, project_id)
        except PermissionDenied:
            return _error("document_unavailable", 404)
        if not any(card.editable for card in cards):
            return _error("no_editable_analysis", 422)
        run, created = MeasurementRun.objects.get_or_create(
            pk=workflow_id,
            defaults={
                "user": request.user,
                "document_id": document_id,
                "project_id": project_id,
                "language": language,
            },
        )
        if run.user_id != request.user.pk:
            return HttpResponseNotFound()
        return _json({"run": _run(run)}, 201 if created else 200)


class RunView(RunBase):
    """State, counts and the last items; ``?with=status`` adds ``document_status``.

    The status costs about five queries per Analysis, so polls leave it out.
    """

    def get(self, request, run_id):
        run = self.own_run(request, run_id)
        if run is None:
            return HttpResponseNotFound()
        intake.resume_if_stalled(run)
        run.refresh_from_db()
        recent = run.items.order_by("-claimed_at", "-id")[:RECENT_ITEMS]
        status = None
        if request.GET.get("with") == "status":
            try:
                status = catalogue.document_status(
                    run.document_id, request.user, run.project_id
                )
            except PermissionDenied:
                pass
        return _json(
            {
                "state": run.state,
                "counts": _counts(run),
                "recent": [_item(i) for i in recent],
                **({"report": undo.report(run)} if run.state == "undone" else {}),
                **(
                    {"document_status": status}
                    if request.GET.get("with") == "status"
                    else {}
                ),
            }
        )


class RunFilesView(RunBase):
    def post(self, request, run_id):
        run = self.own_run(request, run_id)
        if run is None:
            return HttpResponseNotFound()
        length = request.META.get("CONTENT_LENGTH")
        try:
            length = int(length) if length else 0
        except ValueError:
            length = 0
        if length > settings.MEASUREMENT_MAX_ZIP_BYTES:
            return _error("request_too_large", 413)
        if run.state != "collecting":
            return _error("run_not_collecting", 409)
        files = request.FILES.getlist("files")
        if not files:
            return _error("no_files", 400)
        if len(files) > settings.MEASUREMENT_MAX_REQUEST_FILES:
            return _error("too_many_files", 400)
        paths = request.POST.getlist("paths")
        if len(paths) not in (0, len(files)):
            return _error("paths_mismatch", 400)
        alone_zip = len(files) == 1 and files[0].name.lower().endswith(".zip")
        if length > settings.MEASUREMENT_MAX_REQUEST_BYTES and not alone_zip:
            return _error("request_too_large", 413)
        accepted, rejected = [], []
        for number, upload in enumerate(files):
            relative_dir = paths[number] if paths else ""
            if upload.name.lower().endswith(".zip"):
                if len(files) > 1:
                    rejected.append(intake.Rejection(upload.name, "zip_alone"))
                    continue
                if upload.size > settings.MEASUREMENT_MAX_ZIP_BYTES:
                    return _error("request_too_large", 413)
                try:
                    results = intake.expand_zip(run, upload)
                except intake.ZipRefused as refused:
                    return _error(f"zip_{refused.reason}", 400)
            else:
                results = [intake.accept_upload(run, upload.name, relative_dir, upload)]
            for result in results:
                (rejected if isinstance(result, intake.Rejection) else accepted).append(
                    result
                )
        return _json(
            {
                "accepted": [_item(i) for i in accepted],
                "rejected": _rejections(rejected),
            }
        )


class RunStoredView(RunBase):
    def get(self, request, run_id):
        run = self.own_run(request, run_id)
        if run is None:
            return HttpResponseNotFound()
        selected = {
            str(f)
            for f in run.items.filter(origin="stored").values_list(
                "source_file_id", flat=True
            )
        }
        groups = {}
        for card, stored in intake.stored_candidates(run, request.user):
            key = "opus" if stored.extension.isdigit() else stored.extension
            groups.setdefault(key, []).append(
                {
                    "file_id": stored.file_id,
                    "name": stored.name,
                    "analysis_id": card.id,
                    "analysis_name": card.name,
                    "editable": card.editable,
                    "selected": stored.file_id in selected,
                }
            )
        return _json(
            {"formats": [{"format": k, "files": v} for k, v in sorted(groups.items())]}
        )

    def post(self, request, run_id):
        run = self.own_run(request, run_id)
        if run is None:
            return HttpResponseNotFound()
        data = _body(request)
        ids = data.get("file_ids") if data else None
        if not isinstance(ids, list) or not ids or not all(_uuid(i) for i in ids):
            return _error("bad_request", 400)
        if run.state != "collecting":
            return _error("run_not_collecting", 409)
        accepted, rejected = intake.select_stored(
            run, request.user, [str(_uuid(i)) for i in ids]
        )
        return _json(
            {
                "accepted": [_item(i) for i in accepted],
                "rejected": _rejections(rejected),
            }
        )


class RunPrepareView(RunBase):
    def post(self, request, run_id):
        run = self.own_run(request, run_id)
        if run is None:
            return HttpResponseNotFound()
        if run.state == "collecting" and not run.items.exists():
            return _error("no_files", 409)
        outcome = intake.start_preparation(run)
        if outcome == "refused":
            return _error("run_not_collecting", 409)
        return _json({"state": "preparing"}, 202 if outcome == "started" else 200)


def _enqueue_write(run_id):
    transaction.on_commit(lambda: intake.send(intake.WRITE_TASK, run_id))


class RunWriteView(RunBase):
    """``POST``: start writing a reviewed run; 409 unless it is in ``review`` with nothing pending."""

    def post(self, request, run_id):
        run = self.own_run(request, run_id)
        if run is None:
            return HttpResponseNotFound()
        with transaction.atomic():
            locked = MeasurementRun.objects.select_for_update().get(pk=run.pk)
            if locked.state == "writing":
                return _json({"state": "writing"})
            if locked.state != "review":
                return _error("run_not_in_review", 409)
            if not decisions.ready_to_write(locked):
                return _error("items_pending", 409)
            if not locked.items.filter(state="prepared", decision="ready").exists():
                return _error("nothing_to_write", 409)
            MeasurementRun.objects.filter(pk=run.pk).update(
                state="writing", stop_requested=False
            )
            _enqueue_write(run.id)
        return _json({"state": "writing"}, 202)


class RunRetryView(RunBase):
    """``POST``: put the items the writer failed back to ``ready`` and write again."""

    def post(self, request, run_id):
        run = self.own_run(request, run_id)
        if run is None:
            return HttpResponseNotFound()
        with transaction.atomic():
            locked = MeasurementRun.objects.select_for_update().get(pk=run.pk)
            if locked.state not in ("review", "written"):
                return _error("run_not_retryable", 409)
            changed = locked.items.filter(
                state="failed", error__in=writer.WRITE_ERRORS
            ).update(state="prepared", decision="ready", error="", claimed_at=None)
            if not changed:
                return _error("nothing_to_retry", 409)
            MeasurementRun.objects.filter(pk=run.pk).update(
                state="writing", stop_requested=False, finished_at=None
            )
            _enqueue_write(run.id)
        return _json({"state": "writing", "retried": changed}, 202)


class RunStopView(RunBase):
    """``POST``: ask a writing run to stop after the Analysis it is on."""

    def post(self, request, run_id):
        run = self.own_run(request, run_id)
        if run is None:
            return HttpResponseNotFound()
        stopped = MeasurementRun.objects.filter(pk=run.pk, state="writing").update(
            stop_requested=True
        )
        if not stopped:
            return _error("run_not_writing", 409)
        return _json({"state": "writing", "stop_requested": True}, 202)


class RunBatchUndoView(RunBase):
    """``POST``: undo what the run added (« Supprimer »), in any state.

    A ``writing`` run is refused (409 ``writing``): stop it first. A run with nothing written only loses its staging, items and decisions and
    is ``undone`` at once; otherwise it goes to ``undoing`` and the task does
    the rest. A repeated call while ``undoing`` or once ``undone`` is a no-op.
    """

    def post(self, request, run_id):
        run = self.own_run(request, run_id)
        if run is None:
            return HttpResponseNotFound()
        with transaction.atomic():
            locked = MeasurementRun.objects.select_for_update().get(pk=run.pk)
            if locked.state in ("undoing", "undone"):
                return _json({"state": locked.state})
            if locked.state == "writing":
                return _error("writing", 409)
            undo.reset_failed(locked)
            if not locked.items.filter(state="written").exists():
                staging.remove_run(locked.id)
                locked.decisions.all().delete()
                locked.items.all().delete()
                MeasurementRun.objects.filter(pk=locked.pk).update(
                    state="undone", stop_requested=False, finished_at=timezone.now()
                )
                return _json({"state": "undone", "report": undo.report(locked)})
            MeasurementRun.objects.filter(pk=locked.pk).update(
                state="undoing", stop_requested=False
            )
            transaction.on_commit(lambda: intake.send(intake.UNDO_TASK, run.id))
        return _json({"state": "undoing"}, 202)


def _fold(text):
    """Case- and accent-insensitive form used by the search boxes."""
    text = unicodedata.normalize("NFKD", str(text or "")).casefold()
    return "".join(c for c in text if not unicodedata.combining(c))


def _last_action(run):
    last = run.decisions.first()
    if last is None:
        return None
    return {
        "action": last.action,
        "items": len(last.before.get("items", {})),
        "codes": len(last.before.get("codes", {})),
        "created_at": last.created_at.isoformat(),
    }


def _display_names(items):
    ids = {i.display_config_id for i in items if i.display_config_id}
    names = dict(
        RendererConfig.objects.filter(pk__in=ids).values_list("configid", "name")
    )
    for preset in XY_PRESETS.values():
        names.setdefault(uuid.UUID(preset["config_id"]), preset["name"])
    return names


def _folio(item):
    return next((t["piece"] for t in item.tokens if t["meaning"] == "folio"), "")


def _review_item(item, cards, names):
    """One row of the review table; call under ``translation.override(run.language)``."""
    target = item.chosen_analysis_id or item.proposed_analysis_id
    card = cards.get(str(target)) if target else None
    return {
        "id": str(item.id),
        "origin": item.origin,
        "name": item.source_name,
        "relative_dir": item.relative_dir,
        "format": item.detected_format,
        "outcome": item.outcome,
        "state": item.state,
        "decision": item.decision,
        "cause": item.cause,
        "cause_label": gettext(CAUSES[item.cause]) if item.cause in CAUSES else "",
        "reason": item.reason,
        "reason_label": (
            gettext(UNREADABLE_LABELS[item.reason])
            if item.outcome == "unreadable" and item.reason in UNREADABLE_LABELS
            else ""
        ),
        "analysis": (
            {"id": str(target), "label": card.name if card else None}
            if target
            else None
        ),
        "proposed_analysis_id": (
            str(item.proposed_analysis_id) if item.proposed_analysis_id else None
        ),
        "technique": (
            {
                "preset": card.technique_preset,
                "label": card.technique_label.get(translation.get_language())
                or next(iter(card.technique_label.values()), ""),
            }
            if card
            else None
        ),
        "display": {
            "config_id": (
                str(item.display_config_id) if item.display_config_id else None
            ),
            "name": names.get(item.display_config_id),
            "source": item.display_source,
            "auto": item.display_source == "technique",
        },
        "tokens": item.tokens,
        "paired_item_id": str(item.paired_item_id) if item.paired_item_id else None,
        "group_folio": _folio(item),
    }


class RunItemsView(RunBase):
    """The review table: one row per file, filtered, grouped and paged (200 per page).

    ``state`` is the decision (``pending``, ``ready``, ``aside``), ``cause`` a
    key of ``CAUSES``, ``q`` a case- and accent-insensitive search over the
    file, folder, analysis, folio sources, technique and name pieces, ``group``
    one of ``folio``, ``technique``, ``state`` (sets ``group`` on each row and
    sorts by it). ``ready_to_write`` is true when no prepared item is pending.
    """

    def get(self, request, run_id):
        run = self.own_run(request, run_id)
        if run is None:
            return HttpResponseNotFound()
        state, cause = request.GET.get("state"), request.GET.get("cause")
        group = request.GET.get("group", "")
        if group not in ("", "folio", "technique", "state"):
            return _error("bad_request", 400)
        try:
            page = max(int(request.GET.get("page", 1)), 1)
        except ValueError:
            return _error("bad_request", 400)
        cards = {c.id: c for c in prepare.load_snapshot(run)[0]}
        rows = run.items.exclude(state__in=("queued", "claimed", "removed"))
        if state:
            rows = rows.filter(decision=state)
        if cause:
            rows = rows.filter(cause=cause)
        rows = list(rows.order_by("relative_dir", "source_name", "id"))
        needle = _fold(request.GET.get("q", "")).strip()
        if needle:
            rows = [i for i in rows if needle in self._haystack(i, cards)]
        with translation.override(run.language):
            names = _display_names(rows)
            data = [_review_item(i, cards, names) for i in rows]
        for row in data:
            row["group"] = {
                "folio": row["group_folio"],
                "technique": (row["technique"] or {}).get("label", ""),
                "state": row["decision"],
            }.get(group, "")
        if group:
            data.sort(key=lambda r: (_fold(r["group"]), r["relative_dir"], r["name"]))
        total = len(data)
        start = (page - 1) * ITEMS_PER_PAGE
        return _json(
            {
                "items": data[start : start + ITEMS_PER_PAGE],
                "total": total,
                "page": page,
                "pages": max(-(-total // ITEMS_PER_PAGE), 1),
                "ready_to_write": decisions.ready_to_write(run),
                "last_action": _last_action(run),
            }
        )

    @staticmethod
    def _haystack(item, cards):
        target = item.chosen_analysis_id or item.proposed_analysis_id
        card = cards.get(str(target)) if target else None
        parts = [item.source_name, item.relative_dir]
        parts += [t["piece"] for t in item.tokens]
        if card:
            parts += [card.name, *card.folio_sources, *card.technique_label.values()]
        return _fold(" ".join(parts))


class RunCausesView(RunBase):
    """Every cause a prepared item carries, with the actions each offers.

    ``pending`` counts the items of the cause still to decide, ``settled`` the
    others (decided or set aside). Most pending first, then most items. The
    cause stays on an item once decided, so ``items?cause=`` lists both.
    """

    def get(self, request, run_id):
        run = self.own_run(request, run_id)
        if run is None:
            return HttpResponseNotFound()
        counts = {}
        for cause, decision in (
            run.items.filter(state="prepared")
            .exclude(cause="")
            .values_list("cause", "decision")
        ):
            entry = counts.setdefault(cause, [0, 0])
            entry[decision == "pending"] += 1
        with translation.override(run.language):
            rows = [
                {
                    "cause": cause,
                    "label": gettext(CAUSES[cause]) if cause in CAUSES else cause,
                    "actions": list(decisions.CAUSE_ACTIONS.get(cause, ())),
                    "pending": pending,
                    "settled": settled,
                }
                for cause, (settled, pending) in counts.items()
            ]
        rows.sort(
            key=lambda r: (-r["pending"], -(r["pending"] + r["settled"]), r["cause"])
        )
        return _json(rows)


class RunAnalysesView(RunBase):
    """The analysis picker, read from the run's catalogue snapshot (never the database).

    Editable analyses only. ``q`` searches name, folio sources and technique;
    ``technique`` is a preset key or a technique id; ``folio`` a folio such as
    ``1r`` or ``f1r``; ``item`` marks the analysis proposed for that item and
    warns when it already holds a file of the item's format. ``hidden`` counts
    analyses matching ``q`` that the technique and folio filters leave out.
    ``receives`` counts the files of this batch (not set aside) going to the
    analysis.
    """

    def get(self, request, run_id):
        run = self.own_run(request, run_id)
        if run is None:
            return HttpResponseNotFound()
        cards, shelfmark = prepare.load_snapshot(run)
        codes = {c.code: c.family for c in run.user.measurement_name_codes.all()}
        item = None
        if request.GET.get("item"):
            item = run.items.filter(pk=_uuid(request.GET["item"])).first()
            if item is None:
                return HttpResponseNotFound()
        receives = {}
        for target, chosen in (
            run.items.filter(state="prepared")
            .exclude(decision="aside")
            .values_list("proposed_analysis_id", "chosen_analysis_id")
        ):
            key = str(chosen or target or "")
            receives[key] = receives.get(key, 0) + 1
        needle = _fold(request.GET.get("q", "")).strip()
        technique = request.GET.get("technique", "")
        folio = request.GET.get("folio", "").strip().lower()
        if folio and not folio.startswith("f"):
            folio = f"f{folio}"
        out, hidden = [], 0
        with translation.override(run.language):
            for card in cards:
                if not card.editable:
                    continue
                if needle and needle not in _fold(
                    " ".join(
                        [card.name, *card.folio_sources, *card.technique_label.values()]
                    )
                ):
                    continue
                keys = matching.analysis_keys(card, codes, shelfmark)
                if (
                    technique
                    and technique != card.technique_preset
                    and technique not in card.technique_ids
                ) or (folio and folio not in keys.folios):
                    hidden += 1
                    continue
                out.append(
                    {
                        "id": card.id,
                        "name": card.name,
                        "technique": {
                            "preset": card.technique_preset,
                            "label": card.technique_label.get(
                                translation.get_language()
                            )
                            or next(iter(card.technique_label.values()), ""),
                        },
                        "folios": sorted(keys.folios),
                        "already": len(card.files),
                        "receives": receives.get(card.id, 0),
                        "proposed": bool(
                            item and str(item.proposed_analysis_id) == card.id
                        ),
                        "same_format": bool(
                            item and prepare._already_provided(item, card)
                        ),
                    }
                )
        return _json({"analyses": out, "hidden": hidden})


class RunDecisionsView(RunBase):
    """``POST {action, item_ids, params}``: one action, one journal row; see ``decisions``."""

    def post(self, request, run_id):
        run = self.own_run(request, run_id)
        if run is None:
            return HttpResponseNotFound()
        data = _body(request)
        if data is None:
            return _error("bad_request", 400)
        try:
            result = decisions.apply_action(
                run.pk, data.get("action"), data.get("item_ids"), data.get("params", {})
            )
        except decisions.ActionError as refused:
            return _error(refused.reason, refused.status)
        return _json(_decision_answer(run, result["changed"], result["skipped"]))


class RunUndoView(RunBase):
    def post(self, request, run_id):
        run = self.own_run(request, run_id)
        if run is None:
            return HttpResponseNotFound()
        try:
            action = decisions.undo_last(run.pk)
        except decisions.ActionError as refused:
            return _error(refused.reason, refused.status)
        return _json({**_decision_answer(run, 0, []), "undone": action})


def _decision_answer(run, changed, skipped):
    return {
        "changed": changed,
        "skipped": skipped,
        "ready_to_write": decisions.ready_to_write(run),
        "last_action": _last_action(run),
    }


class RunPreviewView(RunBase):
    """One item's preview as JSON: ``csv`` (the staged CSV text, or null), ``description`` (``{en, fr}``), ``display``, ``facts``, ``warnings``.

    The CSV rides inside a JSON body so one request carries everything the
    preview shows. It is the converted CSV, or the lab's own for a lone CSV.
    ``private, no-store``.
    """

    def get(self, request, run_id, item_id):
        run = self.own_run(request, run_id)
        if run is None:
            return HttpResponseNotFound()
        item = run.items.filter(pk=item_id).first()
        if item is None:
            return HttpResponseNotFound()
        csv_text = description = None
        for name in (f"{item.id}-{prepare.CONVERTED_SUFFIX}",) + (
            (item.staged_name,)
            if item.origin == "upload" and item.outcome == "csv"
            else ()
        ):
            try:
                csv_text = staging.read(run.id, name).decode("utf-8")
                break
            except (OSError, ValueError):
                continue
        try:
            description = json.loads(
                staging.read(run.id, f"{item.id}-{prepare.DESCRIPTION_SUFFIX}")
            )
        except (OSError, ValueError):
            pass
        config = RendererConfig.objects.filter(pk=item.display_config_id).first()
        return _json(
            {
                "csv": csv_text,
                "description": description,
                "display": {
                    "config_id": (
                        str(item.display_config_id) if item.display_config_id else None
                    ),
                    "name": config.name if config else None,
                    "config": config.config if config else None,
                    "source": item.display_source,
                },
                "facts": item.facts,
                "warnings": item.warnings,
            }
        )


class CodesView(RunBase):
    """The signed-in editor's dictionary of file-name codes (spec 7.3).

    ``GET`` lists it; ``POST {code, family}`` adds or changes an entry (201 or
    200); ``DELETE ?code=`` (or ``{code}`` in the body) removes one. Codes are
    unique per user whatever their case.
    """

    def get(self, request):
        rows = MeasurementNameCode.objects.filter(user=request.user).order_by(
            "code", "id"
        )
        return _json(
            {
                "codes": [
                    {
                        "code": r.code,
                        "family": r.family,
                        "created_at": r.created_at.isoformat(),
                        "last_used_at": (
                            r.last_used_at.isoformat() if r.last_used_at else None
                        ),
                    }
                    for r in rows
                ],
                "families": sorted(decisions.FAMILIES | {matching.IGNORE}),
            }
        )

    def post(self, request):
        data = _body(request)
        code, family = (data or {}).get("code"), (data or {}).get("family")
        if not decisions.clean_code(code):
            return _error("bad_code", 400)
        if not decisions.clean_family(family):
            return _error("bad_family", 400)
        code = code.strip()
        existed = MeasurementNameCode.objects.filter(
            user=request.user, code__iexact=code
        ).exists()
        try:
            decisions.write_codes(request.user, {code: family})
        except decisions.ActionError as refused:
            return _error(refused.reason, refused.status)
        return _json({"code": code, "family": family}, 200 if existed else 201)

    def delete(self, request):
        code = request.GET.get("code") or (_body(request) or {}).get("code")
        if not isinstance(code, str) or not code.strip():
            return _error("bad_request", 400)
        deleted, _ = MeasurementNameCode.objects.filter(
            user=request.user, code__iexact=code.strip()
        ).delete()
        return _json({}, 200) if deleted else HttpResponseNotFound()
