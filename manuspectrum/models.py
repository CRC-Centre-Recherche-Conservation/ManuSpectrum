import uuid
from datetime import date

from arches.app.models.models import ResourceInstance
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import JSONField
from django.utils.translation import gettext_lazy as _


class RendererConfig(models.Model):
    """
    Arches for Science
    GPL-3.0 license
    https://github.com/archesproject/arches-for-science
    """

    configid = models.UUIDField(primary_key=True, unique=True)
    rendererid = models.UUIDField()
    name = models.TextField(blank=False, null=False)
    description = models.TextField(blank=True, null=True)
    config = JSONField(default=dict)

    class Meta:
        managed = True
        db_table = "renderer_config"

    def __init__(self, *args, **kwargs):
        super(RendererConfig, self).__init__(*args, **kwargs)
        if not self.configid:
            self.configid = uuid.uuid4()


class Embargo(models.Model):
    """The end date of one restricted resource (PP-4).

    The restriction itself stays Arches': this row never decides who reads a
    resource, ``user_can_read_resource`` does. It carries what Arches has no
    place for, the end date and the audit of its changes, and is edited by
    administrators in the Django admin.

    ``ends_on`` empty means the restriction has no end and is never lifted
    automatically. The end may not be later than ``EMBARGO_MAX_MONTHS`` after
    the day the record was created, unless a superuser sets it.
    """

    ACTIVE = "active"
    LIFTED = "lifted"
    RELEASED = "released"
    STATES = (
        (ACTIVE, _("Active")),
        (LIFTED, _("Lifted")),
        (RELEASED, _("Released by hand")),
    )

    resourceinstance = models.OneToOneField(
        ResourceInstance,
        on_delete=models.CASCADE,
        related_name="embargo",
        verbose_name=_("Resource"),
    )
    ends_on = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Ends on"),
        help_text=_(
            "Last day of the restriction. Empty: the restriction has no end "
            "and is never lifted automatically."
        ),
    )
    state = models.CharField(
        max_length=16, choices=STATES, default=ACTIVE, verbose_name=_("State")
    )
    set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name=_("Restriction set by"),
    )
    created = models.DateTimeField(auto_now_add=True, verbose_name=_("Recorded on"))
    notices_sent = models.JSONField(
        default=list, blank=True, verbose_name=_("Notices sent")
    )

    class Meta:
        db_table = "ms_embargo"
        verbose_name = _("embargo")
        verbose_name_plural = _("embargoes")

    def __str__(self):
        return str(self.resourceinstance_id)

    @property
    def start(self):
        """The day the embargo began: the day its record was created."""
        return self.created.date() if self.created else date.today()

    def latest_allowed_end(self):
        return self.start + relativedelta(months=settings.EMBARGO_MAX_MONTHS)

    def validate_end(self, ends_on, *, superuser=False, today=None):
        """Raise ``ValidationError`` unless *ends_on* is an acceptable end date.

        Empty is accepted (no end). A date must be after *today*; beyond the
        maximum duration only a superuser may set it.
        """
        if ends_on is None:
            return
        today = today or date.today()
        if ends_on <= today:
            raise ValidationError(_("The end date must be after today."))
        latest = self.latest_allowed_end()
        if not superuser and ends_on > latest:
            raise ValidationError(
                _(
                    "The end date is more than %(months)d months after the start "
                    "of the embargo (latest allowed: %(latest)s). Only a "
                    "superuser can set a later date."
                ),
                params={
                    "months": settings.EMBARGO_MAX_MONTHS,
                    "latest": latest.isoformat(),
                },
            )

    def change_end(self, ends_on, by):
        """Set the end date, record who changed it, and restart the notices.

        Saves the row and writes the ``EmbargoEvent`` in one call; does
        nothing when the date is unchanged.
        """
        old = self.ends_on
        if ends_on == old:
            return None
        if old is None:
            kind = EmbargoEvent.DATED
        elif ends_on is None:
            kind = EmbargoEvent.UNDATED
        elif ends_on > old:
            kind = EmbargoEvent.EXTENDED
        else:
            kind = EmbargoEvent.SHORTENED
        self.ends_on = ends_on
        self.notices_sent = []
        self.save(update_fields=["ends_on", "notices_sent"])
        return EmbargoEvent.objects.create(
            embargo=self, kind=kind, by=by, from_date=old, to_date=ends_on
        )


class EmbargoEvent(models.Model):
    """What happened to an embargo: who, when, and the dates before and after."""

    DETECTED = "detected"
    DATED = "dated"
    EXTENDED = "extended"
    SHORTENED = "shortened"
    UNDATED = "undated"
    NOTICED = "noticed"
    LIFTED = "lifted"
    RELEASED = "released"
    LIFT_INCOMPLETE = "lift_incomplete"
    KINDS = (
        (DETECTED, _("Restriction detected")),
        (DATED, _("End date set")),
        (EXTENDED, _("Extended")),
        (SHORTENED, _("Shortened")),
        (UNDATED, _("End date removed")),
        (NOTICED, _("Notice sent")),
        (LIFTED, _("Lifted")),
        (RELEASED, _("Released by hand")),
        (LIFT_INCOMPLETE, _("Lift incomplete")),
    )

    embargo = models.ForeignKey(
        Embargo, on_delete=models.CASCADE, related_name="events"
    )
    kind = models.CharField(max_length=16, choices=KINDS, verbose_name=_("Event"))
    by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name=_("By"),
    )
    at = models.DateTimeField(auto_now_add=True, verbose_name=_("When"))
    from_date = models.DateField(null=True, blank=True, verbose_name=_("Old end"))
    to_date = models.DateField(null=True, blank=True, verbose_name=_("New end"))

    class Meta:
        db_table = "ms_embargo_event"
        ordering = ("at", "pk")
        verbose_name = _("embargo event")
        verbose_name_plural = _("embargo events")


class WorkflowCleanup(models.Model):
    """Ledger of one abandoned workflow run: noticed, then cleaned.

    ``workflowid`` has no foreign key: Arches deletes the history row when the
    run is cleaned. No user is stored; recipients are read at notice time.
    """

    workflowid = models.UUIDField(unique=True, verbose_name=_("Workflow run"))
    workflowname = models.CharField(max_length=255, verbose_name=_("Workflow"))
    last_activity = models.DateTimeField(verbose_name=_("Last activity"))
    notices_sent = models.JSONField(
        default=list, blank=True, verbose_name=_("Notices sent")
    )
    cleaned_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Cleaned on")
    )
    cleanup_transaction_id = models.UUIDField(
        null=True, blank=True, default=None, verbose_name=_("Cleanup transaction")
    )
    deleted_count = models.PositiveIntegerField(
        default=0, verbose_name=_("Resources deleted")
    )
    kept_count = models.PositiveIntegerField(
        default=0, verbose_name=_("Resources kept")
    )

    class Meta:
        db_table = "ms_workflow_cleanup"
        ordering = ("-last_activity",)
        verbose_name = _("workflow cleanup")
        verbose_name_plural = _("workflow cleanups")

    def __str__(self):
        return f"{self.workflowname} {self.workflowid}"
