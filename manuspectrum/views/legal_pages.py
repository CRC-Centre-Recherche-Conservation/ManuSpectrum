import math

from django.conf import settings
from django.utils.translation import gettext as _
from django.views.generic import TemplateView

from manuspectrum.accounts.terms import TERMS_VERSION


def _days_text(days):
    """`21 and 7`, `30`, `30, 14 and 7`: the notice days as printed in a sentence."""
    values = [str(day) for day in sorted(days, reverse=True)]
    if len(values) < 2:
        return "".join(values)
    return ", ".join(values[:-1]) + " " + _("and") + " " + values[-1]


class LegalPageView(TemplateView):
    """Legal notice, privacy policy and terms of use.

    Every duration printed on these pages is read from the settings that
    enforce it, so a change of setting changes the page.
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        login_days = settings.LOGIN_RECORDS_RETENTION_DAYS
        context.update(
            terms_version=TERMS_VERSION,
            login_records_days=login_days,
            login_records_months=max(1, math.floor(login_days / 30.44 + 0.5)),
            embargo_max_months=settings.EMBARGO_MAX_MONTHS,
            embargo_notice_days_text=_days_text(settings.EMBARGO_NOTICE_DAYS),
            workflow_cleanup_days=settings.WORKFLOW_CLEANUP_AFTER_DAYS,
            workflow_notice_days_text=_days_text(settings.WORKFLOW_NOTICE_DAYS),
            account_retention_months=settings.ACCOUNT_RETENTION_MONTHS,
            account_notice_days=settings.ACCOUNT_RETENTION_NOTICE_DAYS,
            session_cookie_name=settings.SESSION_COOKIE_NAME,
            csrf_cookie_name=settings.CSRF_COOKIE_NAME,
            language_cookie_name=settings.LANGUAGE_COOKIE_NAME,
        )
        return context
