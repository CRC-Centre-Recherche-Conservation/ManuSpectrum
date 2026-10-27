"""The daily embargo pass: record restrictions, warn, lift, tell.

A restriction is Arches' own ``no_access_to_resourceinstance`` grant on the
``anonymous`` user (or a group it belongs to). ``Embargo`` rows carry its end
date; they never decide who reads a resource. One pass, run daily at 06:00
Europe/Paris, does in order:

1. ``reconcile``: a resource hidden from the visitor with no active row gets
   one, dated at the detection day plus ``EMBARGO_MAX_MONTHS``; an active row whose resource is readable again
   becomes ``released``.
2. ``send_notices``: at ``EMBARGO_NOTICE_DAYS`` days before the end date, once
   per stage (``Embargo.notices_sent``), to the people concerned and, as a
   summary, to the administrators. A restriction dated inside several stages
   gets one notice, for the nearest.
3. ``lift_due``: from 06:00 Europe/Paris on the day after ``ends_on``, remove
   the grants of the visitor and of its groups through the Arches permission
   framework (the path of Arches' « revert »), reindex on commit, check the
   visitor now reads the resource, and tell the people concerned.
4. ``publish_gauges``.

Every lift follows its final notice by at least ``min(EMBARGO_NOTICE_DAYS)``
days: before step 2, ``redate_unwarned`` moves an active restriction that ends
sooner than that without the final stage in ``notices_sent`` to that many days
from today, so step 2 warns (saying the date was moved) and a later pass lifts.
This covers a missed pass and a database replaced by a restore or a snapshot
load, whose notices were voided.

A lift that fails raises no mail to the depositor: it is counted
(``manuspectrum_embargo_lifts_total{outcome="failed"}``), logged, and the row
stays overdue until the next pass. A lift that leaves the resource hidden, by a
grant the pass cannot remove or by a hidden Project above an Analysis, is
counted ``incomplete`` and recorded as an ``EmbargoEvent``.

Recipients of a notice: the user that created the resource, the user that set
the restriction and, for a Project, the creators of its Analyses. Inactive
accounts and ``anonymous`` get nothing; ``send_account_mail`` skips an account
without an address. Only one pass runs at a time (a cache lock), and each row
is changed under ``select_for_update`` after re-reading its end date, so an
extension made in the admin while the pass runs wins.
"""

import contextlib
import logging
import uuid
from collections import namedtuple
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from arches.app.models.models import ResourceInstance
from arches.app.models.resource import Resource
from arches.app.utils import permission_backend as apb
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache, caches
from django.db import transaction
from django.utils import timezone

from manuspectrum.accounts import notices
from manuspectrum.accounts.creation import creators_of, resource_items
from manuspectrum.models import Embargo, EmbargoEvent
from manuspectrum.observability import metrics
from manuspectrum.utils.public_visibility import (
    ANONYMOUS_USERNAME,
    anonymous_user,
    forget_visibility,
    hidden_resource_ids,
    visible_set,
)

logger = logging.getLogger(__name__)

LOCAL_TZ = ZoneInfo("Europe/Paris")
LIFT_HOUR = 6
LOCK_KEY = "embargo-pass-lock"
LOCK_TTL = 30 * 60
#: Analyses read for the recipients of a Project; the rest is not looked at.
PROJECT_ANALYSES_LIMIT = 500
NO_ACCESS = "no_access_to_resourceinstance"

LIFTED, INCOMPLETE, SKIPPED_EXTENDED, FAILED = metrics.EMBARGO_LIFT_OUTCOMES

#: Graph slug -> ``VisibleSet`` attribute, for the models the Explorer filters.
VISIBLE_KINDS = {
    "document": "documents",
    "component": "components",
    "analysis": "analyses",
    "project": "projects",
    "sample": "samples",
    "characterization": "characterizations",
}


#: A notice stage this pass recorded, kept until its mail is known delivered.
Claimed = namedtuple("Claimed", "row days moved stages event")


@dataclass
class PassReport:
    """What a pass did, or with ``apply=False`` would do."""

    locked: bool = False
    detected: list = field(default_factory=list)
    released: list = field(default_factory=list)
    redated: list = field(default_factory=list)
    noticed: list = field(default_factory=list)
    undelivered: list = field(default_factory=list)
    lifted: list = field(default_factory=list)
    incomplete: list = field(default_factory=list)
    skipped_extended: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    due: list = field(default_factory=list)
    undated: int = 0


def aware(moment=None):
    """*moment* (default: now) as an aware datetime; ``USE_TZ=False`` yields naive ones."""
    moment = moment or timezone.now()
    return timezone.make_aware(moment) if timezone.is_naive(moment) else moment


def local_today(now):
    return now.astimezone(LOCAL_TZ).date()


def lift_at(ends_on):
    """The instant a restriction ending on *ends_on* may be lifted."""
    return datetime.combine(
        ends_on + timedelta(days=1), time(LIFT_HOUR), tzinfo=LOCAL_TZ
    )


def is_due(embargo, now):
    return embargo.ends_on is not None and now >= lift_at(embargo.ends_on)


@contextlib.contextmanager
def single_pass(key=LOCK_KEY):
    """Yield True when this caller holds the lock *key*, False when another pass runs."""
    token = uuid.uuid4().hex
    if not cache.add(key, token, LOCK_TTL):
        yield False
        return
    try:
        yield True
    finally:
        if cache.get(key) == token:
            cache.delete(key)


def run_pass(now=None, *, apply=True, send_mail=True):
    """Run the daily pass and return its ``PassReport``.

    ``apply=False`` writes nothing, takes no lock and sends nothing.
    """
    now = aware(now)
    report = PassReport()
    if not apply:
        _run(now, report, apply=False, send_mail=False)
        return report
    with single_pass() as held:
        if not held:
            report.locked = True
            return report
        _run(now, report, apply=True, send_mail=send_mail)
        metrics.EMBARGO_PASS_TIMESTAMP.set(timezone.now().timestamp())
    return report


def _run(now, report, *, apply, send_mail):
    reconcile(now, report, apply=apply)
    redate_unwarned(now, report, apply=apply)
    send_notices(now, report, apply=apply, send_mail=send_mail)
    lift_due(now, report, apply=apply, send_mail=send_mail)
    if apply:
        publish_gauges(now)
    report.undated = Embargo.objects.filter(
        state=Embargo.ACTIVE, ends_on__isnull=True
    ).count()


def reconcile(now, report=None, *, apply=True):
    """Record restrictions Arches holds and release the ones it no longer holds."""
    report = report or PassReport()
    if apply:
        forget_visibility()
    hidden = {str(pk) for pk in hidden_resource_ids(anonymous_user())}
    rows = {
        str(pk): (state, row_pk)
        for pk, state, row_pk in Embargo.objects.values_list(
            "resourceinstance_id", "state", "pk"
        )
    }
    for resource_id in sorted(hidden):
        if resource_id in rows and rows[resource_id][0] == Embargo.ACTIVE:
            continue
        report.detected.append(resource_id)
        if apply:
            record_restriction(resource_id, now=now)
    for resource_id, (state, row_pk) in rows.items():
        if state == Embargo.ACTIVE and resource_id not in hidden:
            report.released.append(resource_id)
            if apply:
                _release(row_pk)
    return report


def record_restriction(resource_id, *, by=None, now=None):
    """Give a hidden resource its active ``Embargo`` row, dated; True when a row changed.

    The end is the detection day plus ``EMBARGO_MAX_MONTHS``, recorded as a
    ``detected`` event (by *by*, the user whose request wrote the restriction)
    then a ``dated`` event by nobody (the pass). A row that was lifted or
    released and is hidden again starts over. Called by the pass and, with *by*,
    once the transaction of a grant commits.
    """
    now = aware(now)
    ends_on = local_today(now) + relativedelta(months=settings.EMBARGO_MAX_MONTHS)
    with transaction.atomic():
        row = (
            Embargo.objects.select_for_update()
            .filter(resourceinstance_id=resource_id)
            .first()
        )
        if row is None:
            if not ResourceInstance.objects.filter(pk=resource_id).exists():
                return False
            row = Embargo.objects.create(
                resourceinstance_id=resource_id, set_by=by, ends_on=ends_on
            )
        elif row.state == Embargo.ACTIVE:
            return False
        else:
            row.state = Embargo.ACTIVE
            row.ends_on = ends_on
            row.notices_sent = []
            row.set_by = by
            row.created = now if settings.USE_TZ else timezone.make_naive(now)
            row.save()
        EmbargoEvent.objects.create(embargo=row, kind=EmbargoEvent.DETECTED, by=by)
        EmbargoEvent.objects.create(
            embargo=row, kind=EmbargoEvent.DATED, to_date=ends_on
        )
    return True


def record_grant(resource_id, grantee, request=None):
    """Record a restriction just written by *request*'s user, if the grant hides the resource.

    *grantee* is the user or group of the grant. Never raises: the pass records
    what this misses, without a setter.
    """
    try:
        visitor = anonymous_user()
        if getattr(visitor, "pk", None) is None or grantee is None:
            return
        if isinstance(grantee, User):
            concerned = grantee.pk == visitor.pk
        else:
            concerned = visitor.groups.filter(pk=grantee.pk).exists()
        if not concerned:
            return
        resource_instance = ResourceInstance.objects.filter(pk=resource_id).first()
        caches["user_permission"].clear()
        if resource_instance is None or apb.user_can_read_resource(
            visitor, resource=resource_instance
        ):
            return
        user = getattr(request, "user", None)
        by = None
        if getattr(user, "is_authenticated", False) and user.pk != visitor.pk:
            by = User.objects.filter(pk=user.pk, is_active=True).first()
        record_restriction(resource_id, by=by)
    except Exception:
        logger.exception("Recording a restriction failed")


def _release(row_pk):
    with transaction.atomic():
        row = Embargo.objects.select_for_update().get(pk=row_pk)
        if row.state != Embargo.ACTIVE:
            return
        row.state = Embargo.RELEASED
        row.save(update_fields=["state"])
        EmbargoEvent.objects.create(embargo=row, kind=EmbargoEvent.RELEASED)


def final_stage():
    """The last notice stage (days before the end), as stored in ``notices_sent``."""
    days = min(settings.EMBARGO_NOTICE_DAYS, default=None)
    return None if days is None else str(days)


def redate_unwarned(now, report=None, *, apply=True):
    """Move a restriction that would end without its final notice to a new end.

    The lift comes the morning after ``ends_on``, so a final notice sent today
    still gives ``min(EMBARGO_NOTICE_DAYS)`` days when the row ends that many
    days from today minus one. An active row ending sooner than that, without
    the final stage in ``notices_sent``, ends ``min(EMBARGO_NOTICE_DAYS)`` days
    from today instead, recorded as a ``dated`` event by nobody (old and new
    end); ``send_notices`` then warns. An end set in the admin (at least that
    many days out) is never moved. ``apply=False`` lists the rows in
    ``redated`` and ``noticed`` and writes nothing.
    """
    report = report or PassReport()
    final = final_stage()
    if final is None:
        return report
    today = local_today(now)
    new_end = today + timedelta(days=int(final))
    earliest = new_end - timedelta(days=1)
    candidates = Embargo.objects.filter(
        state=Embargo.ACTIVE, ends_on__lt=earliest
    ).order_by("ends_on", "pk")
    for candidate in candidates:
        if final in candidate.notices_sent:
            continue
        resource_id = str(candidate.resourceinstance_id)
        if not apply:
            report.redated.append(resource_id)
            report.noticed.append(resource_id)
            continue
        with transaction.atomic():
            row = Embargo.objects.select_for_update().get(pk=candidate.pk)
            if (
                row.state != Embargo.ACTIVE
                or row.ends_on is None
                or row.ends_on >= earliest
                or final in row.notices_sent
            ):
                continue
            old = row.ends_on
            row.ends_on = new_end
            row.save(update_fields=["ends_on"])
            EmbargoEvent.objects.create(
                embargo=row, kind=EmbargoEvent.DATED, from_date=old, to_date=new_end
            )
        report.redated.append(resource_id)
    return report


def due_stages(embargo, today):
    """Notice stages (as strings) reached and not yet sent for *embargo*."""
    if embargo.ends_on is None or embargo.ends_on <= today:
        return []
    return [
        str(days)
        for days in sorted(settings.EMBARGO_NOTICE_DAYS, reverse=True)
        if today >= embargo.ends_on - timedelta(days=days)
        and str(days) not in embargo.notices_sent
    ]


def send_notices(now, report=None, *, apply=True, send_mail=True):
    """Warn the people concerned at each notice stage, once per stage."""
    report = report or PassReport()
    today = local_today(now)
    horizon = today + timedelta(days=max(settings.EMBARGO_NOTICE_DAYS, default=0))
    candidates = Embargo.objects.filter(
        state=Embargo.ACTIVE, ends_on__gt=today, ends_on__lte=horizon
    ).order_by("ends_on", "pk")
    claimed = []
    moved = set(report.redated)
    for candidate in candidates:
        if not due_stages(candidate, today):
            continue
        if not apply:
            if str(candidate.resourceinstance_id) not in report.noticed:
                report.noticed.append(str(candidate.resourceinstance_id))
            continue
        with transaction.atomic():
            row = Embargo.objects.select_for_update().get(pk=candidate.pk)
            stages = due_stages(row, today) if row.state == Embargo.ACTIVE else []
            if not stages:
                continue
            row.notices_sent = sorted({*row.notices_sent, *stages})
            row.save(update_fields=["notices_sent"])
            event = EmbargoEvent.objects.create(
                embargo=row, kind=EmbargoEvent.NOTICED, to_date=row.ends_on
            )
        claimed.append(
            Claimed(
                row,
                (row.ends_on - today).days,
                str(row.resourceinstance_id) in moved,
                stages,
                event.pk,
            )
        )
        report.noticed.append(str(row.resourceinstance_id))
    if send_mail and claimed:
        _mail_notices(claimed, report)
    return report


def _mail_notices(claimed, report):
    """Send the notices claimed by this pass; forget those nobody received.

    A row's stages stay recorded when one person concerned got the mail, or
    when nobody could be written to (no recipient, no address: ``skipped``).
    A send that raises is logged and counted as failed. Every claim not
    confirmed that way loses, in a ``finally``, the stages this pass claimed
    and their ``noticed`` event, so the next pass warns again (and
    ``redate_unwarned`` keeps the lift ``min(EMBARGO_NOTICE_DAYS)`` days after
    a delivered final notice). The administrators' summary goes out either way.
    A worker killed between the claim and this release leaves the claim
    recorded.
    """
    groups = {}
    for claim in claimed:
        groups.setdefault((claim.row.ends_on, claim.days, claim.moved), []).append(
            claim.row
        )
    outcomes = {}
    done = set()
    try:
        for (ends_on, days, moved), rows in groups.items():
            context = {"ends_on": ends_on, "days": days, "moved": moved}
            try:
                by_user = _group_by_recipient(rows)
                for user, user_rows in by_user.items():
                    try:
                        outcome = notices.send_account_mail(
                            user,
                            "embargo_notice",
                            {"resources": _items(user_rows), **context},
                        )
                    except Exception:
                        logger.exception("Embargo notice failed")
                        outcome = notices.count_failure("embargo_notice")
                    for row in user_rows:
                        outcomes.setdefault(row.pk, []).append(outcome)
            except Exception:
                logger.exception("Embargo notice failed")
                notices.count_failure("embargo_notice")
                for row in rows:
                    outcomes.setdefault(row.pk, []).append(notices.FAILED)
            done.update(row.pk for row in rows)
            try:
                notices.send_summary_mail(
                    "embargo_notice", {"resources": _items(rows), **context}
                )
            except Exception:
                logger.exception("Embargo notice summary failed")
    finally:
        for claim in claimed:
            sent = outcomes.get(claim.row.pk, [])
            if claim.row.pk in done and (
                notices.SENT in sent or notices.FAILED not in sent
            ):
                continue
            try:
                _release_notice(claim.row.pk, claim.stages, claim.event)
            except Exception:
                logger.exception("Releasing an undelivered embargo notice failed")
            resource_id = str(claim.row.resourceinstance_id)
            if resource_id in report.noticed:
                report.noticed.remove(resource_id)
            report.undelivered.append(resource_id)


def _release_notice(row_pk, stages, event_pk):
    """Remove the *stages* this pass claimed and their event, under a row lock."""
    with transaction.atomic():
        row = Embargo.objects.select_for_update().get(pk=row_pk)
        kept = [stage for stage in row.notices_sent if stage not in stages]
        if kept != row.notices_sent:
            row.notices_sent = kept
            row.save(update_fields=["notices_sent"])
        EmbargoEvent.objects.filter(pk=event_pk).delete()


def lift_due(now, report=None, *, apply=True, send_mail=True):
    """Lift every active restriction whose end date has passed."""
    report = report or PassReport()
    candidates = Embargo.objects.filter(
        state=Embargo.ACTIVE, ends_on__lt=local_today(now)
    ).order_by("ends_on", "pk")
    redated = set(report.redated)
    lifted_rows = []
    for candidate in candidates:
        if not is_due(candidate, now):
            continue
        resource_id = str(candidate.resourceinstance_id)
        if resource_id in redated:
            continue
        report.due.append(resource_id)
        if not apply:
            continue
        try:
            outcome = lift_one(candidate.pk, now)
        except Exception:
            logger.exception("Embargo lift failed")
            outcome = FAILED
        if outcome is None:
            continue
        metrics.EMBARGO_LIFTS.labels(
            outcome=metrics.bounded(outcome, metrics.EMBARGO_LIFT_OUTCOMES)
        ).inc()
        getattr(report, outcome).append(resource_id)
        if outcome == LIFTED:
            lifted_rows.append(Embargo.objects.get(pk=candidate.pk))
    if send_mail and lifted_rows:
        _mail_lifted(lifted_rows)
    return report


def lift_one(embargo_pk, now):
    """Lift one restriction; returns its outcome, or None when nothing was due.

    The grants of the visitor and of its groups are removed in one transaction
    under a row lock after the end date is read again. The check that the
    visitor now reads the resource runs after the commit, on fresh permission
    memos.
    """
    with transaction.atomic():
        row = Embargo.objects.select_for_update().get(pk=embargo_pk)
        if row.state != Embargo.ACTIVE:
            return None
        if not is_due(row, now):
            return SKIPPED_EXTENDED
        resource_instance = ResourceInstance.objects.get(pk=row.resourceinstance_id)
        remove_visitor_grants(resource_instance)
        row.state = Embargo.LIFTED
        row.save(update_fields=["state"])
        transaction.on_commit(lambda: _reindex(resource_instance.pk))
    return _verify(row, resource_instance)


def remove_visitor_grants(resource_instance):
    """Remove every object grant of the visitor and of its groups, as Arches' revert does."""
    visitor = anonymous_user()
    if getattr(visitor, "pk", None) is None:
        return
    for identity in (visitor, *visitor.groups.all()):
        for perm in apb.get_perms(identity, resource_instance):
            apb.remove_perm(perm, identity, resource_instance)


def _reindex(resource_id):
    try:
        resource = Resource.objects.get(pk=resource_id)
        resource.index()
    except Exception:
        logger.exception("Reindexing a lifted resource failed")


def _verify(row, resource_instance):
    """Record whether the visitor reads the resource now; returns the outcome."""
    caches["user_permission"].clear()
    forget_visibility()
    visitor = anonymous_user()
    readable = apb.user_can_read_resource(visitor, resource=resource_instance)
    kind = VISIBLE_KINDS.get(resource_instance.graph.slug)
    public = readable and (
        kind is None or str(resource_instance.pk) in getattr(visible_set(visitor), kind)
    )
    with transaction.atomic():
        locked = Embargo.objects.select_for_update().get(pk=row.pk)
        if public:
            EmbargoEvent.objects.create(embargo=locked, kind=EmbargoEvent.LIFTED)
            return LIFTED
        if not readable:
            locked.state = Embargo.ACTIVE
            locked.save(update_fields=["state"])
        EmbargoEvent.objects.create(embargo=locked, kind=EmbargoEvent.LIFT_INCOMPLETE)
    return INCOMPLETE


def _mail_lifted(rows):
    for user, user_rows in _group_by_recipient(rows).items():
        notices.send_account_mail(
            user, "embargo_lifted", {"resources": _items(user_rows)}
        )
    notices.send_summary_mail("embargo_lifted", {"resources": _items(rows)})


def publish_gauges(now):
    """Set ``manuspectrum_embargoes`` per state from the active rows.

    ``undated`` rows are never lifted; ``overdue`` rows are past their lift
    time and still active; ``due_soon`` rows end within the last notice stage;
    ``active`` counts the dated rows not yet overdue (``due_soon`` included).
    """
    today = local_today(now)
    soon = today + timedelta(days=min(settings.EMBARGO_NOTICE_DAYS, default=0))
    counts = dict.fromkeys(metrics.EMBARGO_STATES, 0)
    for ends_on in Embargo.objects.filter(state=Embargo.ACTIVE).values_list(
        "ends_on", flat=True
    ):
        if ends_on is None:
            counts["undated"] += 1
        elif now >= lift_at(ends_on):
            counts["overdue"] += 1
        else:
            counts["active"] += 1
            if ends_on <= soon:
                counts["due_soon"] += 1
    for state, count in counts.items():
        metrics.EMBARGOES.labels(state=state).set(count)
    return counts


def project_analyses(project_id):
    """Ids of the Analyses of a Project (their ``analysis_by_project`` link), bounded."""
    from manuspectrum.utils.role_links import node_links, role_node

    node = role_node("analysis", "analysis_by_project")
    if node is None or not node.nodegroup_id:
        return []
    sources = []
    for source, _target in node_links(node, targets=[str(project_id)]):
        if source not in sources:
            sources.append(source)
        if len(sources) >= PROJECT_ANALYSES_LIMIT:
            break
    return sources


def recipients(embargo):
    """The active accounts to tell about *embargo*: creator, setter, and for a Project its Analyses' creators."""
    resource_id = str(embargo.resourceinstance_id)
    user_ids = set()
    if embargo.set_by_id:
        user_ids.add(embargo.set_by_id)
    watched = [resource_id]
    if embargo.resourceinstance.graph.slug == "project":
        watched += project_analyses(resource_id)
    user_ids.update(creators_of(watched).values())
    return list(
        User.objects.filter(pk__in=user_ids, is_active=True)
        .exclude(username=ANONYMOUS_USERNAME)
        .order_by("pk")
    )


def _group_by_recipient(rows):
    by_user = {}
    for row in rows:
        for user in recipients(row):
            by_user.setdefault(user, []).append(row)
    return by_user


def _items(rows):
    return resource_items(row.resourceinstance for row in rows)
