"""Measurement-files batch API, part 1: runs, uploads, stored files, prepare.

Back-office endpoints for Resource Editors, below the language boundary. A run
is visible only to its creator (a bodyless 404 otherwise). Errors carry a
reason code, never a translated sentence. Request bounds are checked from
``Content-Length`` before the body is read, then again on what was received.
"""

import json
import uuid

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseNotFound, JsonResponse
from django.utils.cache import patch_cache_control
from django.utils.decorators import method_decorator
from django.views import View

from arches.app.utils.decorators import group_required

from manuspectrum.constants.measurement_files import ITEM_STATES
from manuspectrum.measurement_files import catalogue, intake
from manuspectrum.models import MeasurementItem, MeasurementRun

RECENT_ITEMS = 20


def _json(payload, status=200):
    response = JsonResponse(payload, status=status)
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
