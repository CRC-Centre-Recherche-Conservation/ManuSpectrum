"""Django admin additions.

`UserProfile` is registered by Arches with the default `ModelAdmin`; it is
registered again here, without the stored secret, to give superusers the
two-factor reset (a user who lost the device is identified by other means, then
reset here). The reset clears the secret and mails the user a personal
enrolment link (`accounts/twofactor.py`); « Send the two-factor enrolment link »
sends it again to the selected accounts that hold no secret.

`Embargo` carries the end date of a restricted resource. Administrators date
and extend it here; every change is recorded as an `EmbargoEvent` (who, when,
old end, new end). Access is Django's own model permission (`change_embargo`),
held by the « Site managers » group (migration 0015, `accounts/roles.py`).
`WorkflowCleanup` is a read-only ledger.

The User admin is the one place for accounts: its list shows two-factor
enrolment and the planned anonymisation date, the change page a read-only
« Account » section, and the two-factor actions above are offered there too
(`UserProfile` stays registered for its Arches fields but is left off the admin
index). Its add form takes an e-mail address and no password: the account is
created with an unusable password and, unless unticked, invited at once
(`accounts/activation.py`); « Send invitation » sends it again.
`TermsAcceptance` is a read-only ledger of the terms each user accepted.
"""

import logging
from datetime import timedelta
from types import SimpleNamespace

from arches.app.models.models import UserProfile
from dateutil.relativedelta import relativedelta
from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.db import transaction
from django.db.models import OuterRef, Q, Subquery
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from manuspectrum.accounts import (
    activation,
    audience,
    notices,
    retention,
    roles,
    twofactor,
)
from manuspectrum.accounts.creation import resource_label
from manuspectrum.accounts.embargo import local_today
from manuspectrum.models import (
    AccountRetention,
    Embargo,
    EmbargoEvent,
    SiteNotice,
    TermsAcceptance,
    WorkflowCleanup,
    site_now,
)
from manuspectrum.utils.public_visibility import ANONYMOUS_USERNAME

logger = logging.getLogger(__name__)


class TwoFactorActionsMixin:
    """The two superuser actions on two-factor enrolment, shared by the profile and User admins.

    ``_profiles(queryset)`` turns the selection into ``UserProfile`` rows.
    """

    def _profiles(self, queryset):
        raise NotImplementedError

    def _superuser_only(self, request):
        if request.user.is_superuser:
            return True
        self.message_user(
            request,
            _("Only a superuser can reset two-factor authentication."),
            messages.ERROR,
        )
        return False

    def _mail_links(self, request, users):
        outcomes = [twofactor.send_reset_link(user) for user in users]
        sent = outcomes.count(notices.SENT)
        if sent:
            self.message_user(
                request,
                ngettext(
                    "The enrolment link was mailed to %(count)d account.",
                    "The enrolment link was mailed to %(count)d accounts.",
                    sent,
                )
                % {"count": sent},
            )
        if len(outcomes) - sent:
            self.message_user(
                request,
                ngettext(
                    "%(count)d account got no mail (inactive, no address or mail failure).",
                    "%(count)d accounts got no mail (inactive, no address or mail failure).",
                    len(outcomes) - sent,
                )
                % {"count": len(outcomes) - sent},
                messages.WARNING,
            )

    @admin.action(description=_("Reset two-factor authentication (superuser)"))
    def reset_two_factor(self, request, queryset):
        if not self._superuser_only(request):
            return
        profiles = list(
            self._profiles(queryset)
            .exclude(encrypted_mfa_hash__isnull=True)
            .exclude(encrypted_mfa_hash="")
            .select_related("user")
        )
        UserProfile.objects.filter(pk__in=[p.pk for p in profiles]).update(
            encrypted_mfa_hash=None
        )
        logger.info(
            "Two-factor reset by user %s for %s account(s)",
            request.user.pk,
            len(profiles),
        )
        self.message_user(
            request,
            ngettext(
                "Two-factor authentication was reset for %(count)d account.",
                "Two-factor authentication was reset for %(count)d accounts.",
                len(profiles),
            )
            % {"count": len(profiles)},
        )
        self._mail_links(request, [p.user for p in profiles])

    @admin.action(description=_("Send the two-factor enrolment link (superuser)"))
    def send_enrolment_link(self, request, queryset):
        if not self._superuser_only(request):
            return
        profiles = (
            self._profiles(queryset)
            .filter(Q(encrypted_mfa_hash__isnull=True) | Q(encrypted_mfa_hash=""))
            .select_related("user")
        )
        self._mail_links(request, [p.user for p in profiles])


class UserProfileAdmin(TwoFactorActionsMixin, admin.ModelAdmin):
    """The Arches profile, reached from the User page and left off the admin index."""

    list_display = ("user", "two_factor")
    search_fields = ("user__username",)
    exclude = ("encrypted_mfa_hash",)
    actions = ["reset_two_factor", "send_enrolment_link"]

    def get_model_perms(self, request):
        return {}

    def _profiles(self, queryset):
        return queryset

    @admin.display(boolean=True, description=_("Two-factor authentication"))
    def two_factor(self, profile):
        return bool(profile.encrypted_mfa_hash)


admin.site.unregister(UserProfile)
admin.site.register(UserProfile, UserProfileAdmin)


class EmbargoForm(forms.ModelForm):
    """Validates the end date against the policy; a superuser may exceed the maximum."""

    class Meta:
        model = Embargo
        fields = ("ends_on",)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_ends_on(self):
        ends_on = self.cleaned_data["ends_on"]
        if ends_on != self.instance.ends_on:
            if ends_on is None and not (self.user and self.user.is_superuser):
                raise forms.ValidationError(
                    _("Only a superuser can remove the end date of a restriction.")
                )
            if self.instance.state != Embargo.ACTIVE:
                raise forms.ValidationError(
                    _("Only an active restriction can change its end date.")
                )
            self.instance.validate_end(
                ends_on, superuser=bool(self.user and self.user.is_superuser)
            )
        return ends_on


class EmbargoEventInline(admin.TabularInline):
    model = EmbargoEvent
    extra = 0
    can_delete = False
    fields = ("at", "kind", "by", "from_date", "to_date")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class UndatedFilter(admin.SimpleListFilter):
    title = _("end date")
    parameter_name = "dated"

    def lookups(self, request, model_admin):
        return (("no", _("No end date")), ("yes", _("Has an end date")))

    def queryset(self, request, queryset):
        if self.value() == "no":
            return queryset.filter(ends_on__isnull=True)
        if self.value() == "yes":
            return queryset.filter(ends_on__isnull=False)
        return queryset


class EmbargoAdmin(admin.ModelAdmin):
    form = EmbargoForm
    list_display = ("resource", "graph", "ends_on", "state", "notices")
    list_filter = ("state", UndatedFilter)
    search_fields = ("resourceinstance__resourceinstanceid",)
    fields = ("resource", "graph", "state", "set_by", "created", "notices", "ends_on")
    readonly_fields = ("resource", "graph", "state", "set_by", "created", "notices")
    inlines = [EmbargoEventInline]
    actions = ["extend_3", "extend_6", "extend_12"]
    list_select_related = ("resourceinstance", "resourceinstance__graph")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        user = request.user

        class UserForm(form):
            def __init__(self, *args, **kw):
                super().__init__(*args, user=user, **kw)

        return UserForm

    @admin.display(description=_("Resource"))
    def resource(self, embargo):
        return resource_label(embargo.resourceinstance)

    @admin.display(description=_("Model"))
    def graph(self, embargo):
        return embargo.resourceinstance.graph.name

    @admin.display(description=_("Notices sent"))
    def notices(self, embargo):
        return ", ".join(str(n) for n in embargo.notices_sent) or "-"

    def save_model(self, request, obj, form, change):
        new_end = obj.ends_on
        if change and "ends_on" in form.changed_data:
            obj.ends_on = form.initial.get("ends_on")
            try:
                obj.change_end(new_end, request.user)
            except forms.ValidationError as error:
                request._embargo_change_refused = True
                self.message_user(request, error.messages[0], messages.ERROR)
        else:
            super().save_model(request, obj, form, change)

    def log_change(self, request, obj, message):
        """Skip the admin log entry of a save the model refused."""
        if getattr(request, "_embargo_change_refused", False):
            return None
        return super().log_change(request, obj, message)

    def response_change(self, request, obj):
        """Return to the change page with only the error when the model refused the save."""
        if getattr(request, "_embargo_change_refused", False):
            return HttpResponseRedirect(request.get_full_path())
        return super().response_change(request, obj)

    def extend(self, request, queryset, months):
        done = 0
        for embargo in queryset:
            if embargo.state != Embargo.ACTIVE or embargo.ends_on is None:
                self.message_user(
                    request,
                    _("%(resource)s: only a dated, active restriction can be extended.")
                    % {"resource": resource_label(embargo.resourceinstance)},
                    messages.WARNING,
                )
                continue
            target = embargo.ends_on + relativedelta(months=months)
            try:
                embargo.validate_end(target, superuser=request.user.is_superuser)
            except forms.ValidationError as error:
                self.message_user(
                    request,
                    "%s: %s"
                    % (resource_label(embargo.resourceinstance), error.messages[0]),
                    messages.ERROR,
                )
                continue
            try:
                embargo.change_end(target, request.user)
            except forms.ValidationError as error:
                self.message_user(
                    request,
                    "%s: %s"
                    % (resource_label(embargo.resourceinstance), error.messages[0]),
                    messages.ERROR,
                )
                continue
            done += 1
        if done:
            self.message_user(
                request,
                ngettext(
                    "%(count)d restriction was extended.",
                    "%(count)d restrictions were extended.",
                    done,
                )
                % {"count": done},
            )

    @admin.action(
        description=_("Extend the end date by 3 months"), permissions=["change"]
    )
    def extend_3(self, request, queryset):
        self.extend(request, queryset, 3)

    @admin.action(
        description=_("Extend the end date by 6 months"), permissions=["change"]
    )
    def extend_6(self, request, queryset):
        self.extend(request, queryset, 6)

    @admin.action(
        description=_("Extend the end date by 12 months"), permissions=["change"]
    )
    def extend_12(self, request, queryset):
        self.extend(request, queryset, 12)


class WorkflowCleanupAdmin(admin.ModelAdmin):
    list_display = (
        "workflowname",
        "workflowid",
        "last_activity",
        "cleaned_at",
        "deleted_count",
        "kept_count",
    )
    list_filter = ("workflowname",)
    search_fields = ("workflowid",)

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


def _paris_time_widget():
    """Native date and time inputs.

    The admin's own widget compares the browser clock with ``TIME_ZONE`` and
    prints an offset note when the browser is in another zone; its « Now »
    shortcut fills the browser's time. These fields hold Paris times.
    """
    return forms.SplitDateTimeWidget(
        date_attrs={"type": "date"},
        time_attrs={"type": "time"},
        date_format="%Y-%m-%d",
        time_format="%H:%M",
    )


class SiteNoticeForm(forms.ModelForm):
    """Validates through ``SiteNotice.clean`` (dates, reminders, link labels)."""

    starts_at = forms.SplitDateTimeField(
        label=SiteNotice._meta.get_field("starts_at").verbose_name,
        help_text=SiteNotice._meta.get_field("starts_at").help_text,
        widget=_paris_time_widget(),
    )
    ends_at = forms.SplitDateTimeField(
        label=SiteNotice._meta.get_field("ends_at").verbose_name,
        help_text=SiteNotice._meta.get_field("ends_at").help_text,
        widget=_paris_time_widget(),
    )

    class Meta:
        model = SiteNotice
        fields = "__all__"
        widgets = {
            "text_en": forms.Textarea(attrs={"rows": 3, "cols": 80}),
            "text_fr": forms.Textarea(attrs={"rows": 3, "cols": 80}),
        }


class SiteNoticeAdmin(admin.ModelAdmin):
    form = SiteNoticeForm
    list_display = (
        "__str__",
        "kind",
        "display",
        "starts_at",
        "ends_at",
        "state",
    )
    list_filter = ("kind", "display")
    ordering = ("-starts_at",)
    readonly_fields = ("schedule",)
    fieldsets = (
        (_("Text"), {"fields": ("kind", "display", "text_en", "text_fr")}),
        (
            _("Details link"),
            {"fields": ("link_url", "link_label_en", "link_label_fr")},
        ),
        (_("Schedule"), {"fields": ("starts_at", "ends_at", "reminders", "schedule")}),
    )

    def view_on_site(self, obj):
        return f"{reverse('root')}?ms-notice-preview={obj.pk}"

    @staticmethod
    def _moments(notice):
        """(first appearance, other reminders, start, end), naive site times."""
        reminders = notice.reminder_seconds()
        shown = [notice.starts_at - timedelta(seconds=r) for r in reminders]
        return shown[:1], shown[1:], notice.starts_at, notice.ends_at

    @admin.display(description=_("State"))
    def state(self, notice):
        now = site_now()
        first = self._moments(notice)[0]
        if now >= notice.ends_at:
            return _("over")
        if now >= notice.starts_at:
            return _("shown") if notice.display == SiteNotice.ONCE else _("in progress")
        if first and now >= first[0]:
            return _("shown")
        return _("scheduled")

    @admin.display(description=_("Schedule"))
    def schedule(self, notice):
        if not notice.starts_at or not notice.ends_at:
            return "-"
        day = "D j M H:i"
        zone = " (%s)" % settings.SITE_NOTICE_TIME_ZONE
        if notice.display == SiteNotice.ONCE:
            return (
                _("Shown from %(start)s until %(end)s")
                % {
                    "start": date_format(notice.starts_at, day),
                    "end": date_format(notice.ends_at, day),
                }
            ) + zone
        if not notice.reminder_seconds():
            return "-"
        first, later, start, end = self._moments(notice)
        parts = [
            _("Shown from %(when)s") % {"when": date_format(first[0], day)},
        ]
        if later:
            parts.append(
                _("reminders %(when)s")
                % {"when": ", ".join(date_format(m, day) for m in later)}
            )
        ends_later = end.date() != start.date()
        parts.append(
            _("in progress %(start)s–%(end)s")
            % {
                "start": date_format(start, day),
                "end": date_format(end, day if ends_later else "H:i"),
            }
        )
        if not ends_later:
            parts.append(_("gone at %(when)s") % {"when": date_format(end, "H:i")})
        return " · ".join(str(p) for p in parts) + zone


admin.site.register(Embargo, EmbargoAdmin)
admin.site.register(WorkflowCleanup, WorkflowCleanupAdmin)
admin.site.register(SiteNotice, SiteNoticeAdmin)


def _user_admin_class():
    User = get_user_model()
    registered = admin.site._registry.get(User)
    if registered is not None:
        admin.site.unregister(User)
        return type(registered)
    from django.contrib.auth.admin import UserAdmin

    return UserAdmin


_BaseUserAdmin = _user_admin_class()


class AccountCreationForm(forms.ModelForm):
    """Add form of the User admin: no password, the account is invited instead.

    The account gets an unusable password; the person chooses theirs from the
    invitation link. The address is required and unique among users, whatever
    its case.
    """

    invite_now = forms.BooleanField(
        required=False,
        initial=True,
        label=_("Send the invitation now"),
        help_text=_(
            "The person receives a link to accept the terms and set a password."
        ),
    )

    class Meta:
        model = get_user_model()
        fields = ("username", "email", "first_name", "last_name", "groups")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True

    def clean_username(self):
        username = self.cleaned_data["username"]
        if self._meta.model.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(
                _("A user with that username already exists."), code="unique"
            )
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if self._meta.model.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                _("A user with that e-mail address already exists."), code="unique"
            )
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_unusable_password()
        if commit:
            user.save()
            self.save_m2m()
        return user


class TwoFactorFilter(admin.SimpleListFilter):
    title = _("two-factor authentication")
    parameter_name = "two_factor"

    def lookups(self, request, model_admin):
        return (("yes", _("Enrolled")), ("no", _("Not enrolled")))

    def queryset(self, request, queryset):
        no_secret = Q(userprofile__encrypted_mfa_hash__isnull=True) | Q(
            userprofile__encrypted_mfa_hash=""
        )
        if self.value() == "yes":
            return queryset.exclude(no_secret)
        if self.value() == "no":
            return queryset.filter(no_secret)
        return queryset


class InvitingUserAdmin(TwoFactorActionsMixin, _BaseUserAdmin):
    """Users: the list at a glance, the add form with the invitation, the account section.

    A staff account that is not a superuser grants only the assignable groups,
    never staff or superuser status, direct permissions or a password; it
    cannot change the user name, e-mail address or dates of an existing account,
    nor change, delete or invite an account managed by superusers, its own
    included (`accounts/roles.py`). The rule holds on the server: those fields
    are left out of its forms, and a change or delete of a protected account is
    refused.
    """

    add_form = AccountCreationForm
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "email",
                    "first_name",
                    "last_name",
                    "groups",
                    "invite_now",
                ),
            },
        ),
    )
    fieldsets = (
        *_BaseUserAdmin.fieldsets,
        (
            _("Account"),
            {
                "fields": (
                    "two_factor",
                    "planned_anonymisation",
                    "invitation_state",
                    "terms_accepted",
                    "profile_link",
                )
            },
        ),
    )
    readonly_fields = (
        "two_factor",
        "planned_anonymisation",
        "invitation_state",
        "terms_accepted",
        "profile_link",
    )
    list_display = (
        "username",
        "full_name",
        "email",
        "is_active",
        "two_factor",
        "last_login",
        "planned_anonymisation",
        "is_staff",
        "is_superuser",
    )
    list_filter = ("is_active", TwoFactorFilter, "is_staff", "is_superuser", "groups")
    list_select_related = ("userprofile",)
    actions = [
        *(_BaseUserAdmin.actions or []),
        "send_invitation",
        "copy_addresses",
        "reset_two_factor",
        "send_enrolment_link",
    ]
    superuser_actions = ("copy_addresses", "reset_two_factor", "send_enrolment_link")

    def get_queryset(self, request):
        ledger = AccountRetention.objects.filter(user_id=OuterRef("pk"))
        return (
            super()
            .get_queryset(request)
            .annotate(
                ledger_noticed_on=Subquery(ledger.values("noticed_on")[:1]),
                ledger_noticed_for=Subquery(ledger.values("noticed_for")[:1]),
                ledger_anonymised_on=Subquery(ledger.values("anonymised_on")[:1]),
            )
        )

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            for name in self.superuser_actions:
                actions.pop(name, None)
        return actions

    def _profiles(self, queryset):
        return UserProfile.objects.filter(user_id__in=queryset.values("pk"))

    def _may_manage(self, request, user):
        if user is None or request.user.is_superuser:
            return True
        return user.pk != request.user.pk and not roles.managed_by_superusers(user)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and self._may_manage(
            request, obj
        )

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and self._may_manage(
            request, obj
        )

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if obj is None or request.user.is_superuser:
            return fieldsets
        return [
            (
                name,
                {
                    **options,
                    "fields": [f for f in options["fields"] if f != "password"],
                },
            )
            for name, options in fieldsets
        ]

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if request.user.is_superuser:
            return fields
        fields = (*fields, "is_staff", "is_superuser", "user_permissions")
        if obj is None:
            return fields
        return (*fields, "username", "email", "last_login", "date_joined")

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "groups" and not request.user.is_superuser:
            kwargs["queryset"] = roles.assignable_groups()
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def user_change_password(self, request, id, form_url=""):
        if not request.user.is_superuser:
            raise PermissionDenied
        return super().user_change_password(request, id, form_url)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change and form.cleaned_data.get("invite_now"):
            transaction.on_commit(lambda: self._invite(request, [obj]))

    @admin.display(description=_("Full name"), ordering="last_name")
    def full_name(self, user):
        return user.get_full_name() or "-"

    @admin.display(boolean=True, description=_("Two-factor authentication"))
    def two_factor(self, user):
        try:
            return bool(user.userprofile.encrypted_mfa_hash)
        except ObjectDoesNotExist:
            return False

    @admin.display(description=_("Planned anonymisation"))
    def planned_anonymisation(self, user):
        if not user.pk:
            return "-"
        if hasattr(user, "ledger_anonymised_on"):
            row = SimpleNamespace(
                noticed_on=user.ledger_noticed_on,
                noticed_for=user.ledger_noticed_for,
                anonymised_on=user.ledger_anonymised_on,
            )
        else:
            row = AccountRetention.objects.filter(user_id=user.pk).first()
        planned = retention.planned_anonymisation(
            user, row, local_today(timezone.now())
        )
        if planned is not None:
            return date_format(planned, "SHORT_DATE_FORMAT")
        if row is not None and row.anonymised_on:
            return _("Anonymised on %(date)s") % {
                "date": date_format(row.anonymised_on, "SHORT_DATE_FORMAT")
            }
        if user.is_superuser:
            return _("Never (superuser)")
        return "-"

    @admin.display(description=_("Invitation"))
    def invitation_state(self, user):
        if user.username == ANONYMOUS_USERNAME:
            return _("Cannot be invited: this is the system account for visitors.")
        if activation.can_be_invited(user):
            return _("Can be invited: no password yet.")
        if not user.has_usable_password():
            return _(
                "Cannot be invited: the account is inactive or has no e-mail address."
            )
        return _("Has a password.")

    @admin.display(description=_("Terms of use accepted"))
    def terms_accepted(self, user):
        version = (
            TermsAcceptance.objects.filter(user=user)
            .order_by("-accepted_at")
            .values_list("version", flat=True)
            .first()
        )
        return version or _("Not yet")

    @admin.display(description=_("Arches profile"))
    def profile_link(self, user):
        profile = UserProfile.objects.filter(user=user).first()
        if profile is None:
            return "-"
        opts = UserProfile._meta
        url = reverse(
            f"admin:{opts.app_label}_{opts.model_name}_change", args=[profile.pk]
        )
        return format_html('<a href="{}">{}</a>', url, _("Open the Arches profile"))

    @admin.action(description=_("Copy the e-mail addresses"))
    def copy_addresses(self, request, queryset):
        if not request.user.is_superuser:
            self.message_user(
                request,
                _("Only a superuser can copy the e-mail addresses."),
                messages.ERROR,
            )
            return None
        reached = audience.audience(queryset)
        logger.info(
            "Addresses listed by user %s for %s account(s)",
            request.user.pk,
            len(reached.addresses),
        )
        context = {
            **self.admin_site.each_context(request),
            "title": _("Copy the e-mail addresses"),
            "opts": self.model._meta,
            "audience": reached,
            "addresses_text": ", ".join(reached.addresses),
        }
        return TemplateResponse(request, "admin/copy_addresses.html", context)

    @admin.action(
        description=_("Send invitation (account with no password)"),
        permissions=["change"],
    )
    def send_invitation(self, request, queryset):
        users = list(queryset)
        allowed = [user for user in users if self._may_manage(request, user)]
        skipped = len(users) - len(allowed)
        if skipped:
            self.message_user(
                request,
                ngettext(
                    "%(count)d account was skipped: only a superuser can invite it.",
                    "%(count)d accounts were skipped: only a superuser can invite them.",
                    skipped,
                )
                % {"count": skipped},
                messages.ERROR,
            )
        self._invite(request, allowed)

    def _invite(self, request, users):
        sent = 0
        for user in users:
            if not activation.can_be_invited(user):
                self.message_user(
                    request,
                    _(
                        "%(user)s was skipped: the account must be active, have an "
                        "e-mail address and no usable password."
                    )
                    % {"user": user.get_username()},
                    messages.ERROR,
                )
                continue
            if activation.send_invitation(user) == notices.SENT:
                sent += 1
                logger.info(
                    "Invitation sent for user %s by user %s", user.pk, request.user.pk
                )
            else:
                self.message_user(
                    request,
                    _("The invitation to %(user)s could not be sent.")
                    % {"user": user.get_username()},
                    messages.ERROR,
                )
        if sent:
            self.message_user(
                request,
                ngettext(
                    "%(count)d invitation was sent.",
                    "%(count)d invitations were sent.",
                    sent,
                )
                % {"count": sent},
            )


admin.site.register(get_user_model(), InvitingUserAdmin)


class TermsAcceptanceAdmin(admin.ModelAdmin):
    list_display = ("user", "version", "accepted_at")
    list_filter = ("version",)
    search_fields = ("user__username",)
    readonly_fields = ("user", "version", "accepted_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(TermsAcceptance, TermsAcceptanceAdmin)
