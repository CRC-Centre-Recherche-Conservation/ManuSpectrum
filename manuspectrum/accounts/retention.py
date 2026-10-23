"""The daily retention pass: warn, then anonymise accounts nobody signs in to.

An account is a real user (not ``anonymous``, not already anonymised, active or
not) whose last activity, ``last_login`` or ``date_joined`` when it never
signed in, is ``ACCOUNT_RETENTION_MONTHS`` old. Its owner is told
``ACCOUNT_RETENTION_NOTICE_DAYS`` days before, once, by the ``AccountRetention``
ledger; the account is anonymised on the later of the end of the period and the
notice date plus the notice days, so an account found overdue is warned before
it is touched. A sign-in after the notice changes the last activity: the notice
is void and the clock restarts.

Anonymising never deletes: first name, last name and e-mail are cleared, the
username becomes ``former-user-<id>``, the password is unusable, the account is
deactivated, the two-factor secret and phone are cleared, the sessions and the
sign-in records of the account are removed, and in Arches' ``edit_log`` the
e-mail is erased and the username replaced while first and last names stay as
contribution credit. Permissions, group memberships, accepted terms and Person
resources stay. One transaction per account; a second run does nothing.

Superusers are warned and listed to the administrators once for a human
decision, and are never anonymised.

One pass runs at a time (a cache lock). The ledger holds no personal data.
"""

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from zoneinfo import ZoneInfo

from arches.app.models.models import EditLog, UserProfile
from axes.models import AccessAttempt, AccessFailureLog, AccessLog
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone

from manuspectrum.accounts import notices
from manuspectrum.accounts.embargo import LOCAL_TZ, aware, local_today, single_pass
from manuspectrum.models import AccountRetention
from manuspectrum.observability import metrics
from manuspectrum.utils.public_visibility import ANONYMOUS_USERNAME

logger = logging.getLogger(__name__)

LOCK_KEY = "account-retention-pass-lock"
USERNAME_FORMAT = "former-user-{}"

ANONYMISED, FAILED = metrics.ACCOUNT_ANONYMISATION_OUTCOMES


@dataclass
class PassReport:
    """What a pass did, or with ``apply=False`` would do; user ids, never names."""

    locked: bool = False
    noticed: list = field(default_factory=list)
    reset: list = field(default_factory=list)
    anonymised: list = field(default_factory=list)
    superusers_due: list = field(default_factory=list)
    failed: list = field(default_factory=list)


def former_username(user_id):
    return USERNAME_FORMAT.format(user_id)


def last_activity_day(user):
    """The local day of the account's last sign-in, or of its creation when it never signed in."""
    moment = user.last_login or user.date_joined
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo(settings.TIME_ZONE))
    return moment.astimezone(LOCAL_TZ).date()


def due_on(activity_day):
    """The first day an account last active on *activity_day* may be anonymised."""
    return activity_day + relativedelta(months=settings.ACCOUNT_RETENTION_MONTHS)


def notice_on(activity_day):
    return due_on(activity_day) - timedelta(days=settings.ACCOUNT_RETENTION_NOTICE_DAYS)


def anonymise_on(activity_day, noticed_on):
    """The day the account is anonymised once the notice went on *noticed_on*."""
    return max(
        due_on(activity_day),
        noticed_on + timedelta(days=settings.ACCOUNT_RETENTION_NOTICE_DAYS),
    )


def planned_date(activity_day, noticed_on, today):
    """The day an account last active on *activity_day* is anonymised; pure, writes nothing.

    *noticed_on* is the day of its valid notice, or None when it has none yet.
    With a notice the date is ``anonymise_on(activity_day, noticed_on)``; with
    none it is the end of the retention period while *today* is before the
    notice period, else the date a notice sent *today* would give. The pass
    and the admin both read this one rule.
    """
    if noticed_on is not None:
        return anonymise_on(activity_day, noticed_on)
    if today < notice_on(activity_day):
        return due_on(activity_day)
    return anonymise_on(activity_day, today)


def anonymisation_date(user, today=None):
    """The day *user*'s account is anonymised if it stays unused, recording the notice when due.

    Before the notice period the date is the end of the retention period and the
    daily pass sends its own notice later. Once the account is inside it, the
    notice is recorded in the ledger now (the caller mails it), so the pass
    does not warn a second time and the date returned is the one it applies.
    """
    today = today or local_today(timezone.now())
    activity = last_activity_day(user)
    if today < notice_on(activity):
        return planned_date(activity, None, today)
    row = AccountRetention.objects.filter(user_id=user.pk).first()
    if row and row.noticed_on and row.noticed_for == activity:
        return planned_date(activity, row.noticed_on, today)
    if row and row.noticed_on:
        _clear_notice(row)
    _claim_notice(user, activity, today)
    row = AccountRetention.objects.get(user_id=user.pk)
    return planned_date(activity, row.noticed_on, today)


def planned_anonymisation(user, row, today=None):
    """The day the pass would anonymise *user*, or None when it never will; writes nothing.

    *row* is the account's ``AccountRetention`` ledger row, or None. It
    follows the rule of ``_handle``: superusers, ``anonymous`` and accounts
    already anonymised are left out; a notice made void by a later activity
    counts for nothing. The date itself is ``planned_date``. Inactive accounts
    are treated like active ones.
    """
    if (
        user.is_superuser
        or user.username == ANONYMOUS_USERNAME
        or user.username == former_username(user.pk)
        or (row is not None and row.anonymised_on)
    ):
        return None
    today = today or local_today(timezone.now())
    activity = last_activity_day(user)
    valid = row is not None and row.noticed_on and row.noticed_for == activity
    return planned_date(activity, row.noticed_on if valid else None, today)


def candidates():
    """Users the pass looks at: real, not anonymised yet, with their ledger row."""
    done = set(
        AccountRetention.objects.filter(anonymised_on__isnull=False).values_list(
            "user_id", flat=True
        )
    )
    rows = {row.user_id: row for row in AccountRetention.objects.all()}
    users = User.objects.exclude(username=ANONYMOUS_USERNAME).order_by("pk")
    return [
        (user, rows.get(user.pk))
        for user in users
        if user.pk not in done and user.username != former_username(user.pk)
    ]


def run_pass(now=None, *, apply=True, send_mail=True):
    """Run the daily pass and return its ``PassReport``.

    ``apply=False`` writes nothing, takes no lock and sends nothing.
    """
    now = aware(now)
    report = PassReport()
    if not apply:
        _run(now, report, apply=False, send_mail=False)
        return report
    with single_pass(LOCK_KEY) as held:
        if not held:
            report.locked = True
            return report
        _run(now, report, apply=True, send_mail=send_mail)
        metrics.ACCOUNT_RETENTION_TIMESTAMP.set(timezone.now().timestamp())
    return report


def _run(now, report, *, apply, send_mail):
    today = local_today(now)
    to_mail, review = [], []
    for user, row in candidates():
        try:
            outcome = _handle(user, row, today, report, apply=apply)
        except Exception:
            logger.exception("Account retention failed")
            report.failed.append(user.pk)
            if apply:
                metrics.ACCOUNT_ANONYMISATIONS.labels(outcome=FAILED).inc()
            continue
        if outcome is not None:
            to_mail.append(outcome)
        if user.pk in report.superusers_due and apply:
            review.append(user.username)
    if send_mail:
        _mail_notices(to_mail)
        _mail_summary(report, review)


def _handle(user, row, today, report, *, apply):
    """Void, notice, list or anonymise one account; returns a notice to mail, or None."""
    activity = last_activity_day(user)
    noticed_on = row.noticed_on if row else None
    if row and noticed_on and row.noticed_for != activity:
        report.reset.append(user.pk)
        if apply:
            _clear_notice(row)
        noticed_on = None
        row = None
    if today < notice_on(activity):
        return None
    if noticed_on is None:
        report.noticed.append(user.pk)
        if not apply:
            return None
        if not _claim_notice(user, activity, today):
            report.noticed.pop()
            return None
        return (user, planned_date(activity, None, today))
    if today < planned_date(activity, noticed_on, today):
        return None
    if user.is_superuser:
        if row.listed_on is None:
            report.superusers_due.append(user.pk)
            if apply:
                _mark_listed(row, today)
        return None
    if not apply:
        report.anonymised.append(user.pk)
        return None
    if anonymise(user.pk, today):
        report.anonymised.append(user.pk)
        metrics.ACCOUNT_ANONYMISATIONS.labels(outcome=ANONYMISED).inc()
    return None


def _clear_notice(row):
    with transaction.atomic():
        locked = AccountRetention.objects.select_for_update().get(pk=row.pk)
        locked.noticed_on = locked.noticed_for = locked.listed_on = None
        locked.save(update_fields=["noticed_on", "noticed_for", "listed_on"])


def _mark_listed(row, today):
    with transaction.atomic():
        locked = AccountRetention.objects.select_for_update().get(pk=row.pk)
        locked.listed_on = today
        locked.save(update_fields=["listed_on"])


def _claim_notice(user, activity, today):
    """Record the notice under a row lock; False when another pass already did."""
    with transaction.atomic():
        row, _created = AccountRetention.objects.get_or_create(user_id=user.pk)
        row = AccountRetention.objects.select_for_update().get(pk=row.pk)
        if row.anonymised_on or row.noticed_on:
            return False
        row.noticed_on, row.noticed_for = today, activity
        row.save(update_fields=["noticed_on", "noticed_for"])
    return True


def anonymise(user_id, today=None):
    """Anonymise one account in one transaction; False when there was nothing to do.

    Refuses ``anonymous`` and superusers, and an account already anonymised.
    """
    today = today or local_today(timezone.now())
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        if user.username == ANONYMOUS_USERNAME or user.is_superuser:
            return False
        row, _created = AccountRetention.objects.get_or_create(user_id=user.pk)
        row = AccountRetention.objects.select_for_update().get(pk=row.pk)
        if row.anonymised_on or user.username == former_username(user.pk):
            return False
        old_username = user.username
        new_username = former_username(user.pk)
        EditLog.objects.filter(userid=str(user.pk)).update(
            user_email="", user_username=new_username
        )
        EditLog.objects.filter(provisional_userid=str(user.pk)).update(
            provisional_user_username=new_username
        )
        LogEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(User),
            object_id=str(user.pk),
        ).update(object_repr=new_username)
        user.first_name = user.last_name = user.email = ""
        user.username = new_username
        user.set_unusable_password()
        user.is_active = False
        user.skip_deactivation_notice = True
        user.save()
        UserProfile.objects.filter(user=user).update(encrypted_mfa_hash=None, phone="")
        _end_sessions(user.pk)
        _purge_sign_in_records(old_username)
        row.anonymised_on = today
        row.save(update_fields=["anonymised_on"])
    return True


def _end_sessions(user_id):
    expired = []
    for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        if session.get_decoded().get("_auth_user_id") == str(user_id):
            expired.append(session.pk)
    Session.objects.filter(pk__in=expired).delete()


def _purge_sign_in_records(username):
    for model in (AccessAttempt, AccessLog, AccessFailureLog):
        model.objects.filter(username__iexact=username).delete()


def _mail_notices(claimed):
    for user, on in claimed:
        notices.send_account_mail(
            user,
            "anonymisation_notice",
            {
                "on": on,
                "days": settings.ACCOUNT_RETENTION_NOTICE_DAYS,
                "review": user.is_superuser,
                "active": user.is_active,
            },
            allow_inactive=True,
        )


def _mail_summary(report, review):
    if not (report.noticed or report.anonymised or review):
        return
    notices.send_summary_mail(
        "anonymisation_summary",
        {
            "months": settings.ACCOUNT_RETENTION_MONTHS,
            "anonymised": len(report.anonymised),
            "noticed": len(report.noticed),
            "review": review,
        },
    )


def send_deactivation_notice(user):
    """Tell *user* their account was deactivated and when it will be anonymised.

    Never raises: a failure is logged and the deactivation stands.
    """
    try:
        today = local_today(timezone.now())
        notices.send_account_mail(
            user,
            "deactivation_notice",
            {
                "deactivated_on": today,
                "on": anonymisation_date(user, today),
                "review": user.is_superuser,
            },
            allow_inactive=True,
        )
    except Exception:
        logger.exception("Deactivation notice failed")
