"""Django admin additions.

`UserProfile` is registered by Arches with the default `ModelAdmin`; it is
registered again here, without the stored secret, to give superusers the
two-factor reset (a user who lost the device is identified by other means, then
reset here). The reset clears the secret and mails the user a personal
enrolment link (`accounts/twofactor.py`); « Send the two-factor enrolment link »
sends it again to the selected accounts that hold no secret.

`Embargo` carries the end date of a restricted resource. Administrators date
and extend it here; every change is recorded as an `EmbargoEvent` (who, when,
old end, new end). Access is Django's own model permission (`change_embargo`);
no group is created for it. `WorkflowCleanup` is a read-only ledger.

The User admin gains the action « Send invitation » (account activation,
`accounts/activation.py`); `TermsAcceptance` is a read-only ledger of the
terms each user accepted.
"""

import logging

from arches.app.models.models import UserProfile
from dateutil.relativedelta import relativedelta
from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from manuspectrum.accounts import activation, audience, notices, twofactor
from manuspectrum.accounts.creation import resource_label
from manuspectrum.models import Embargo, EmbargoEvent, TermsAcceptance, WorkflowCleanup

logger = logging.getLogger(__name__)


class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "two_factor")
    search_fields = ("user__username",)
    exclude = ("encrypted_mfa_hash",)
    actions = ["reset_two_factor", "send_enrolment_link"]

    @admin.display(boolean=True, description=_("Two-factor authentication"))
    def two_factor(self, profile):
        return bool(profile.encrypted_mfa_hash)

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
            queryset.exclude(encrypted_mfa_hash__isnull=True)
            .exclude(encrypted_mfa_hash="")
            .select_related("user")
        )
        queryset.filter(pk__in=[p.pk for p in profiles]).update(encrypted_mfa_hash=None)
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
        profiles = queryset.filter(
            Q(encrypted_mfa_hash__isnull=True) | Q(encrypted_mfa_hash="")
        ).select_related("user")
        self._mail_links(request, [p.user for p in profiles])


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

    @admin.action(description=_("Extend the end date by 3 months"))
    def extend_3(self, request, queryset):
        self.extend(request, queryset, 3)

    @admin.action(description=_("Extend the end date by 6 months"))
    def extend_6(self, request, queryset):
        self.extend(request, queryset, 6)

    @admin.action(description=_("Extend the end date by 12 months"))
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


admin.site.register(Embargo, EmbargoAdmin)
admin.site.register(WorkflowCleanup, WorkflowCleanupAdmin)


def _user_admin_class():
    User = get_user_model()
    registered = admin.site._registry.get(User)
    if registered is not None:
        admin.site.unregister(User)
        return type(registered)
    from django.contrib.auth.admin import UserAdmin

    return UserAdmin


_BaseUserAdmin = _user_admin_class()


class InvitingUserAdmin(_BaseUserAdmin):
    actions = [*(_BaseUserAdmin.actions or []), "send_invitation", "copy_addresses"]

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.pop("copy_addresses", None)
        return actions

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
        sent = 0
        for user in queryset:
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
