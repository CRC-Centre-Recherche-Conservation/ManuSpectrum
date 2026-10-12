"""Django admin additions.

`UserProfile` is registered by Arches with the default `ModelAdmin`; it is
registered again here, without the stored secret, to give superusers the
two-factor reset (a user who lost the device is identified by other means, then
reset here).

`Embargo` carries the end date of a restricted resource. Administrators date
and extend it here; every change is recorded as an `EmbargoEvent` (who, when,
old end, new end). Access is Django's own model permission (`change_embargo`);
no group is created for it. `WorkflowCleanup` is a read-only ledger.
"""

import logging

from arches.app.models.models import UserProfile
from dateutil.relativedelta import relativedelta
from django import forms
from django.contrib import admin, messages
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from manuspectrum.models import Embargo, EmbargoEvent, WorkflowCleanup

logger = logging.getLogger(__name__)


class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "two_factor")
    search_fields = ("user__username",)
    exclude = ("encrypted_mfa_hash",)
    actions = ["reset_two_factor"]

    @admin.display(boolean=True, description=_("Two-factor authentication"))
    def two_factor(self, profile):
        return bool(profile.encrypted_mfa_hash)

    @admin.action(description=_("Reset two-factor authentication (superuser)"))
    def reset_two_factor(self, request, queryset):
        if not request.user.is_superuser:
            self.message_user(
                request,
                _("Only a superuser can reset two-factor authentication."),
                messages.ERROR,
            )
            return
        count = queryset.exclude(encrypted_mfa_hash__isnull=True).update(
            encrypted_mfa_hash=None
        )
        logger.info(
            "Two-factor reset by user %s for %s account(s)", request.user.pk, count
        )
        self.message_user(
            request,
            ngettext(
                "Two-factor authentication was reset for %(count)d account.",
                "Two-factor authentication was reset for %(count)d accounts.",
                count,
            )
            % {"count": count},
        )


admin.site.unregister(UserProfile)
admin.site.register(UserProfile, UserProfileAdmin)


def resource_label(resourceinstance):
    """The resource's display name in the active language, else any language."""
    descriptors = resourceinstance.descriptors or {}
    for language in (get_language(), *descriptors):
        name = (descriptors.get(language) or {}).get("name")
        if name:
            return name
    return str(resourceinstance.pk)


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
            obj.change_end(new_end, request.user)
        else:
            super().save_model(request, obj, form, change)

    def extend(self, request, queryset, months):
        done = 0
        for embargo in queryset:
            if embargo.state != Embargo.ACTIVE or embargo.ends_on is None:
                self.message_user(
                    request,
                    _("%(resource)s: only a dated, active embargo can be extended.")
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
            embargo.change_end(target, request.user)
            done += 1
        if done:
            self.message_user(
                request,
                ngettext(
                    "%(count)d embargo was extended.",
                    "%(count)d embargoes were extended.",
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
