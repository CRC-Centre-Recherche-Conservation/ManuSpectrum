"""The daily pass over abandoned workflow runs: warn, then clean.

A run is a ``workflow_history`` row of a kind in ``KINDS`` that is not
completed. Its last activity is the newest of the row's ``created`` and the
``edit_log`` rows written under its id (the workflow id is the transaction id
of everything the run writes). A run idle for ``WORKFLOW_CLEANUP_AFTER_DAYS``
is cleaned; its owners are told ``WORKFLOW_NOTICE_DAYS`` days before. Completed
runs are never read.

Warned and cleaned are the users who created resources in the run
(``creation.created_in_transaction``), never the creators of resources the run
only reused. A notice goes once per stage, recorded in the ``WorkflowCleanup``
ledger as ``"<days>@<date>"``; a run that shows new activity restarts its
notices. The cleanup date is the later of the idle limit and the last stage's
date plus its days, so a run found overdue (first deployment, missed passes) is
warned before it is cleaned.

Cleaning deletes, through ``Resource.delete`` under one fresh transaction id
(recorded in the ledger, so the activity report counts them as cleaned, not
deleted), only the resources the run created that are still drafts, were not
edited under another transaction and are not referenced by a resource that
stays. A reference whose tile the run wrote itself (the link to a Project) does
not count. Everything else is kept and reported. The history row goes with the
cleanup. Every run is cleaned in its own transaction under a row lock on its
ledger entry; one pass runs at a time (a cache lock).
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta

from arches.app.models.models import (
    EditLog,
    ResourceInstance,
    ResourceXResource,
    WorkflowHistory,
)
from arches.app.models.resource import Resource
from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.functional import lazy
from django.utils.translation import gettext_lazy as _

from manuspectrum.accounts import notices
from manuspectrum.accounts.creation import created_in_transaction, resource_items
from manuspectrum.accounts.embargo import LOCAL_TZ, local_today, single_pass
from manuspectrum.accounts.models import WorkflowCleanup
from manuspectrum.observability import metrics
from manuspectrum.utils.public_visibility import (
    ANONYMOUS_USERNAME,
    draft_state_id_set,
)

logger = logging.getLogger(__name__)

KINDS = metrics.WORKFLOW_KINDS
LOCK_KEY = "workflow-cleanup-pass-lock"
KIND_LABELS = {
    "create-project-workflow": _("Create a project"),
    "import-biblissima-workflow": _("Import from Biblissima"),
}

CLEANED, KEPT_RESOURCES, FAILED = metrics.WORKFLOW_CLEANUP_OUTCOMES
NOT_DRAFT, MODIFIED, LINKED = "not_draft", "modified", "linked"


@dataclass
class Run:
    workflowid: uuid.UUID
    name: str
    last_activity: object


@dataclass
class Plan:
    """What cleaning a run would do: ids to delete, ids kept with the reason."""

    created: dict = field(default_factory=dict)
    deletable: list = field(default_factory=list)
    kept: dict = field(default_factory=dict)
    reused: list = field(default_factory=list)


@dataclass
class PassReport:
    """What a pass did, or with ``apply=False`` would do."""

    locked: bool = False
    noticed: list = field(default_factory=list)
    cleaned: list = field(default_factory=list)
    kept_resources: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    deleted: int = 0
    kept: int = 0
    plans: dict = field(default_factory=dict)


class WorkflowTransactionError(Exception):
    """A ``transactionId`` the request may not use: *status* 400 or 403."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def workflow_transaction(raw, user):
    """The workflow id a write request may use as its transaction id, or None.

    An absent id gives None (the caller mints its own). Anything else must be
    a UUID (400) and, as Arches does for a transaction reversal, must not
    belong to someone else (403): the id of a run that has a history row
    needs that row to be *user*'s and open, an id with no history row must not
    already appear in the edit log under other users only.
    """
    if raw in (None, ""):
        return None
    try:
        workflowid = uuid.UUID(str(raw)) if isinstance(raw, (str, uuid.UUID)) else None
    except ValueError:
        workflowid = None
    if workflowid is None:
        raise WorkflowTransactionError(400, "Invalid transactionId")
    history = WorkflowHistory.objects.filter(pk=workflowid).first()
    if history is not None:
        if history.user_id != user.pk or history.completed:
            raise WorkflowTransactionError(403, "Forbidden transactionId")
    else:
        written = EditLog.objects.filter(transactionid=workflowid)
        if written.exists() and not written.filter(userid=str(user.pk)).exists():
            raise WorkflowTransactionError(403, "Forbidden transactionId")
    return workflowid


def _aware(value):
    return value.astimezone() if value.tzinfo is None else value


def _stage_entry(stage, day):
    return f"{stage}@{day.isoformat()}"


def parse_sent(entries):
    """``{stage days: date sent}`` from the ledger's ``notices_sent``."""
    sent = {}
    for entry in entries or []:
        try:
            stage, day = str(entry).split("@")
            sent[int(stage)] = date.fromisoformat(day)
        except ValueError:
            continue
    return sent


def cleanup_on(activity_day, sent):
    """The day a run idle since *activity_day* may be cleaned."""
    on = activity_day + timedelta(days=settings.WORKFLOW_CLEANUP_AFTER_DAYS)
    final = min(settings.WORKFLOW_NOTICE_DAYS, default=None)
    if final is not None and final in sent:
        on = max(on, sent[final] + timedelta(days=final))
    return on


def due_stages(idle_days, sent):
    """Notice stages (days before the cleanup) reached and not yet sent."""
    return [
        stage
        for stage in sorted(settings.WORKFLOW_NOTICE_DAYS, reverse=True)
        if idle_days >= settings.WORKFLOW_CLEANUP_AFTER_DAYS - stage
        and stage not in sent
    ]


def open_runs(now, only=None):
    """The open runs of a cleaned kind that may be near their notice, with their last activity."""
    horizon = settings.WORKFLOW_CLEANUP_AFTER_DAYS - max(
        settings.WORKFLOW_NOTICE_DAYS, default=0
    )
    histories = WorkflowHistory.objects.filter(
        completed=False,
        workflowname__in=KINDS,
        created__lte=now - timedelta(days=horizon),
    ).order_by("created", "pk")
    if only:
        histories = histories.filter(pk__in=only)
    histories = list(histories)
    latest = dict(
        EditLog.objects.filter(transactionid__in=[h.pk for h in histories])
        .values("transactionid")
        .annotate(last=Max("timestamp"))
        .values_list("transactionid", "last")
    )
    return [
        Run(
            h.pk,
            h.workflowname,
            max(
                _aware(h.created),
                _aware(latest[h.pk]) if latest.get(h.pk) else _aware(h.created),
            ),
        )
        for h in histories
    ]


def plan_cleanup(workflowid):
    """Classify the resources of a run: those to delete and those to keep."""
    plan = Plan()
    plan.created = created_in_transaction(workflowid)
    touched = set(
        EditLog.objects.filter(transactionid=workflowid)
        .values_list("resourceinstanceid", flat=True)
        .distinct()
    )
    plan.reused = sorted(touched - set(plan.created))
    instances = {
        str(r.pk): r for r in ResourceInstance.objects.filter(pk__in=list(plan.created))
    }
    plan.created = {rid: uid for rid, uid in plan.created.items() if rid in instances}
    drafts = draft_state_id_set()
    modified = set(
        EditLog.objects.filter(resourceinstanceid__in=list(instances))
        .exclude(transactionid=workflowid)
        .values_list("resourceinstanceid", flat=True)
    )
    eligible = set()
    for rid, instance in instances.items():
        if str(instance.resource_instance_lifecycle_state_id) not in drafts:
            plan.kept[rid] = NOT_DRAFT
        elif rid in modified:
            plan.kept[rid] = MODIFIED
        else:
            eligible.add(rid)
    inbound = {}
    for to_id, from_id, tile_id in ResourceXResource.objects.filter(
        to_resource_id__in=list(eligible)
    ).values_list("to_resource_id", "from_resource_id", "tile_id"):
        if str(from_id) != str(to_id):
            inbound.setdefault(str(to_id), []).append(
                (str(from_id) if from_id else None, str(tile_id) if tile_id else None)
            )
    own_tiles = _tiles_written_by(
        workflowid, {tile for refs in inbound.values() for _f, tile in refs if tile}
    )
    changed = True
    while changed:
        changed = False
        for rid in sorted(eligible):
            if any(
                source not in eligible
                and not (source not in plan.created and tile in own_tiles)
                for source, tile in inbound.get(rid, [])
            ):
                eligible.discard(rid)
                plan.kept[rid] = LINKED
                changed = True
    plan.deletable = sorted(eligible)
    return plan


def _tiles_written_by(workflowid, tile_ids):
    """Tiles whose last edit-log row belongs to the transaction *workflowid*."""
    if not tile_ids:
        return set()
    last = {}
    for tile_id, transaction_id, timestamp in EditLog.objects.filter(
        tileinstanceid__in=list(tile_ids)
    ).values_list("tileinstanceid", "transactionid", "timestamp"):
        mine = transaction_id == workflowid
        previous = last.get(tile_id)
        if (
            previous is None
            or timestamp > previous[0]
            or (timestamp == previous[0] and not mine)
        ):
            last[tile_id] = (timestamp, mine)
    return {tile_id for tile_id, (_t, mine) in last.items() if mine}


def _label(kinds):
    labels = [KIND_LABELS[k] for k in dict.fromkeys(kinds)]
    return lazy(lambda: ", ".join(str(label) for label in labels), str)()


def _recipients(user_ids):
    return list(
        User.objects.filter(pk__in=user_ids, is_active=True)
        .exclude(username=ANONYMOUS_USERNAME)
        .order_by("pk")
    )


def _items_by_user(created, resource_ids):
    """``{user id: [ResourceInstance]}`` of the *resource_ids* each user created."""
    by_user = {}
    wanted = [rid for rid in resource_ids if created.get(rid) is not None]
    for instance in ResourceInstance.objects.filter(pk__in=wanted).order_by("pk"):
        by_user.setdefault(created[str(instance.pk)], []).append(instance)
    return by_user


def run_pass(now=None, *, apply=True, send_mail=True, only=None):
    """Run the daily pass and return its ``PassReport``.

    ``apply=False`` writes nothing, takes no lock and sends nothing; *only* is
    a list of workflow ids that restricts the pass to those runs.
    """
    now = now or timezone.now()
    report = PassReport()
    if not apply:
        _run(now, report, apply=False, send_mail=False, only=only)
        return report
    with single_pass(LOCK_KEY) as held:
        if not held:
            report.locked = True
            return report
        _run(now, report, apply=True, send_mail=send_mail, only=only)
        metrics.WORKFLOW_CLEANUP_TIMESTAMP.set(timezone.now().timestamp())
    return report


def _run(now, report, *, apply, send_mail, only):
    today = local_today(now)
    noticed, cleaned = [], []
    for run in open_runs(now, only):
        try:
            outcome = _handle(run, now, today, report, apply=apply)
        except Exception:
            logger.exception("Workflow cleanup failed")
            report.failed.append(str(run.workflowid))
            if apply:
                metrics.WORKFLOW_CLEANUPS.labels(
                    kind=metrics.bounded(run.name, metrics.WORKFLOW_KINDS),
                    outcome=FAILED,
                ).inc()
            continue
        if outcome is None:
            continue
        kind, payload = outcome
        (noticed if kind == "notice" else cleaned).append(payload)
    if send_mail:
        _mail_notices(noticed)
        _mail_cleaned(cleaned)


def _handle(run, now, today, report, *, apply):
    """Notice and/or clean one run; returns ``("notice"|"clean", payload)`` or None."""
    ledger = WorkflowCleanup.objects.filter(workflowid=run.workflowid).first()
    sent = _sent_of(ledger, run.last_activity)
    activity_day = run.last_activity.astimezone(LOCAL_TZ).date()
    idle = (today - activity_day).days
    stages = due_stages(idle, sent)
    result = None
    if stages:
        report.noticed.append(str(run.workflowid))
        if apply:
            claimed = _claim_notice(run, stages, today)
            if claimed is None:
                report.noticed.pop()
                return None
            sent = claimed
            result = (
                "notice",
                {
                    "run": run,
                    "cleanup_on": cleanup_on(activity_day, sent),
                    "days": max((cleanup_on(activity_day, sent) - today).days, 0),
                    "created": created_in_transaction(run.workflowid),
                },
            )
        else:
            sent = {**sent, **dict.fromkeys(stages, today)}
    if not (
        idle >= settings.WORKFLOW_CLEANUP_AFTER_DAYS
        and today >= cleanup_on(activity_day, sent)
    ):
        return result
    if not apply:
        report.plans[str(run.workflowid)] = plan_cleanup(run.workflowid)
        return result
    return _clean(run, report) or result


def _sent_of(ledger, last_activity):
    if ledger is None or _aware(ledger.last_activity) < last_activity:
        return {}
    return parse_sent(ledger.notices_sent)


def _claim_notice(run, stages, today):
    """Record *stages* as sent under a row lock; the new ``sent`` map, or None when raced."""
    with transaction.atomic():
        ledger, _created = WorkflowCleanup.objects.get_or_create(
            workflowid=run.workflowid,
            defaults={
                "workflowname": run.name,
                "last_activity": run.last_activity,
            },
        )
        ledger = WorkflowCleanup.objects.select_for_update().get(pk=ledger.pk)
        if ledger.cleaned_at:
            return None
        sent = _sent_of(ledger, run.last_activity)
        if _aware(ledger.last_activity) < run.last_activity:
            ledger.last_activity = run.last_activity
        stages = [s for s in stages if s not in sent]
        if not stages:
            return None
        for stage in stages:
            sent[stage] = today
        ledger.notices_sent = [
            _stage_entry(stage, day)
            for stage, day in sorted(sent.items(), reverse=True)
        ]
        ledger.save(update_fields=["last_activity", "notices_sent"])
    return sent


def _clean(run, report):
    """Delete what the run created and may lose, and drop its history row."""
    kind = metrics.bounded(run.name, metrics.WORKFLOW_KINDS)
    transaction_id = uuid.uuid4()
    attempted = []
    try:
        with transaction.atomic():
            ledger, _created = WorkflowCleanup.objects.get_or_create(
                workflowid=run.workflowid,
                defaults={
                    "workflowname": run.name,
                    "last_activity": run.last_activity,
                },
            )
            ledger = WorkflowCleanup.objects.select_for_update().get(pk=ledger.pk)
            history = (
                WorkflowHistory.objects.select_for_update()
                .filter(pk=run.workflowid, completed=False)
                .first()
            )
            if ledger.cleaned_at or history is None:
                return None
            if _newer_activity(run):
                return None
            plan = plan_cleanup(run.workflowid)
            instances = {
                str(r.pk): r
                for r in ResourceInstance.objects.filter(pk__in=list(plan.created))
            }
            deleted_items = _by_user_items(plan, plan.deletable, instances, link=False)
            kept_items = _by_user_items(plan, list(plan.kept), instances)
            outside = {
                str(source)
                for source in ResourceXResource.objects.filter(
                    to_resource_id__in=plan.deletable
                ).values_list("from_resource_id", flat=True)
                if source and str(source) not in plan.deletable
            }
            attempted = list(plan.deletable)
            for rid in plan.deletable:
                Resource.objects.get(pk=rid).delete(transaction_id=transaction_id)
            history.delete()
            ledger.cleaned_at = timezone.now()
            ledger.cleanup_transaction_id = transaction_id
            ledger.deleted_count = len(plan.deletable)
            ledger.kept_count = len(plan.kept)
            ledger.save(
                update_fields=[
                    "cleaned_at",
                    "cleanup_transaction_id",
                    "deleted_count",
                    "kept_count",
                ]
            )
            transaction.on_commit(lambda: _reindex(outside))
    except Exception:
        _reindex(attempted)
        raise
    outcome = KEPT_RESOURCES if plan.kept else CLEANED
    metrics.WORKFLOW_CLEANUPS.labels(kind=kind, outcome=outcome).inc()
    metrics.WORKFLOW_CLEANUP_RESOURCES.labels(outcome="deleted").inc(
        len(plan.deletable)
    )
    metrics.WORKFLOW_CLEANUP_RESOURCES.labels(outcome="kept").inc(len(plan.kept))
    report.cleaned.append(str(run.workflowid))
    if plan.kept:
        report.kept_resources.append(str(run.workflowid))
    report.deleted += len(plan.deletable)
    report.kept += len(plan.kept)
    return (
        "clean",
        {
            "run": run,
            "deleted": deleted_items,
            "kept": kept_items,
        },
    )


def _newer_activity(run):
    latest = EditLog.objects.filter(transactionid=run.workflowid).aggregate(
        last=Max("timestamp")
    )["last"]
    return latest is not None and _aware(latest) > run.last_activity


def _by_user_items(plan, resource_ids, instances, *, link=True):
    """``{user id or None: [{"name", "url"?}]}`` for the resources, read before deletion."""
    by_user = {}
    for rid in resource_ids:
        (item,) = resource_items([instances[rid]])
        if not link:
            item = {"name": item["name"]}
        by_user.setdefault(plan.created.get(rid), []).append(item)
    return by_user


def _reindex(resource_ids):
    for resource_id in resource_ids:
        try:
            resource = Resource.objects.filter(pk=resource_id).first()
            if resource is not None:
                resource.index()
        except Exception:
            logger.exception("Reindexing after a workflow cleanup failed")


def _mail_notices(payloads):
    if not payloads:
        return
    everything = []
    for payload in payloads:
        run = payload["run"]
        by_user = _items_by_user(payload["created"], list(payload["created"]))
        for user in _recipients(by_user):
            notices.send_account_mail(
                user,
                "workflow_notice",
                {
                    "workflow": KIND_LABELS[run.name],
                    "cleanup_on": payload["cleanup_on"],
                    "days": payload["days"],
                    "resources": resource_items(by_user[user.pk]),
                },
            )
        everything.append(payload)
    first = min(everything, key=lambda p: p["cleanup_on"])
    names = [p["run"].name for p in everything]
    notices.send_summary_mail(
        "workflow_notice",
        {
            "workflow": _label(names),
            "cleanup_on": first["cleanup_on"],
            "days": first["days"],
            "resources": resource_items(
                ResourceInstance.objects.filter(
                    pk__in=[rid for p in everything for rid in p["created"]]
                ).order_by("pk")
            ),
        },
    )


def _mail_cleaned(payloads):
    if not payloads:
        return
    for payload in payloads:
        users = {*payload["deleted"], *payload["kept"]} - {None}
        for user in _recipients(users):
            notices.send_account_mail(
                user,
                "workflow_cleaned",
                {
                    "workflow": KIND_LABELS[payload["run"].name],
                    "deleted": payload["deleted"].get(user.pk, []),
                    "kept": payload["kept"].get(user.pk, []),
                },
            )
    notices.send_summary_mail(
        "workflow_cleaned",
        {
            "workflow": _label([p["run"].name for p in payloads]),
            "deleted": [i for p in payloads for v in p["deleted"].values() for i in v],
            "kept": [i for p in payloads for v in p["kept"].values() for i in v],
        },
    )
