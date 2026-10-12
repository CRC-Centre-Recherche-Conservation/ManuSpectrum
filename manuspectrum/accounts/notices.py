"""Account mail: notices about a user's data and account.

Every mail is a service notice, sent one per recipient (never `cc`/`bcc`),
English first then French in the same message, with the subject prefix
`[ManuSpectrum][Account]` and the header `X-ManuSpectrum-Category: Account`
(`deploy/OBSERVABILITY.md`, « Sorting the mail »). The sender is
`DEFAULT_FROM_EMAIL`. There is no unsubscribe link: the footer says why.

`KINDS` is the closed vocabulary. `send_account_mail` writes to one account;
`send_summary_mail` writes the administrators' copy to
`ACCOUNT_SUMMARY_RECIPIENTS` (the host's `ALERT_EMAILS`) for the kinds that
have one. Neither raises: the outcome (`sent`, `failed`, `skipped`) is returned
and counted in `manuspectrum_account_mails_total`. A log line names the kind and
the exception class, never an address, a name or a link.

Context per kind (`resources` and `kept` are lists of `{"name", "url"}`,
`url` optional and absolute):

- `embargo_notice`: `resources`, `ends_on` (date), `days` (days left).
- `embargo_lifted`: `resources`.
- `workflow_notice`: `workflow` (label), `cleanup_on` (date), `days`, `resources`.
- `workflow_cleaned`: `workflow`, `deleted`, `kept`.
- `invitation`: `link` (personal, time-limited), `expires_on` (date).
- `anonymisation_notice`: `on` (date), `days`, `review` (True for a superuser,
  whose account is not anonymised automatically).
- `anonymisation_summary`: `months`, `anonymised` (count), `noticed` (count),
  `review` (usernames of superusers due for a decision); administrators only.
- `password_reset` is sent by `AccountPasswordResetForm`.
"""

import logging
from collections import namedtuple

from django.conf import settings
from django.contrib.auth.forms import PasswordResetForm
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import translation
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from manuspectrum.observability import metrics

logger = logging.getLogger(__name__)

SUBJECT_PREFIX = "[ManuSpectrum][Account] "
CATEGORY_HEADER = "X-ManuSpectrum-Category"
CATEGORY = "Account"
LANGUAGES = ("en", "fr")

Kind = namedtuple("Kind", "to_user summary")

KINDS = {
    "embargo_notice": Kind(to_user=True, summary=True),
    "embargo_lifted": Kind(to_user=True, summary=True),
    "workflow_notice": Kind(to_user=True, summary=True),
    "workflow_cleaned": Kind(to_user=True, summary=True),
    "invitation": Kind(to_user=True, summary=False),
    "anonymisation_notice": Kind(to_user=True, summary=False),
    "anonymisation_summary": Kind(to_user=False, summary=True),
    "password_reset": Kind(to_user=True, summary=False),
}

SENT, FAILED, SKIPPED = metrics.ACCOUNT_MAIL_OUTCOMES


def _day(value):
    return date_format(value, "DATE_FORMAT")


def _embargo_notice(ctx):
    return {
        "subject": _("Restriction ending on %(date)s") % {"date": _day(ctx["ends_on"])},
        "paragraphs": [
            _(
                "The restriction that keeps the data below private ends on %(date)s, "
                "%(days)s days from now. The day after, it is lifted automatically "
                "and the data become visible to everyone."
            )
            % {"date": _day(ctx["ends_on"]), "days": ctx["days"]},
            _(
                "If it must last longer, ask an administrator to extend it before "
                "that date, by replying to the contact address below."
            ),
        ],
        "items": ctx.get("resources", []),
    }


def _embargo_lifted(ctx):
    return {
        "subject": _("Your data are now public"),
        "paragraphs": [
            _(
                "The restriction on the data below has ended and was lifted: "
                "they are now visible to everyone."
            )
        ],
        "items": ctx.get("resources", []),
    }


def _workflow_notice(ctx):
    return {
        "subject": _("Unfinished workflow to be cleaned on %(date)s")
        % {"date": _day(ctx["cleanup_on"])},
        "paragraphs": [
            _(
                "The workflow « %(workflow)s » has not been used for a long time "
                "and is not finished. On %(date)s, %(days)s days from now, it is "
                "cleaned: its trace is deleted, and so are the records it created "
                "and listed below, if they are still drafts, were not modified "
                "elsewhere and are not linked to other records."
            )
            % {
                "workflow": ctx["workflow"],
                "date": _day(ctx["cleanup_on"]),
                "days": ctx["days"],
            },
            _("Open the workflow again before that date to keep it."),
        ],
        "items": ctx.get("resources", []),
    }


def _workflow_cleaned(ctx):
    paragraphs = [
        _("The unfinished workflow « %(workflow)s » has been cleaned.")
        % {"workflow": ctx["workflow"]}
    ]
    if ctx.get("deleted"):
        paragraphs.append(_("Deleted records:"))
    return {
        "subject": _("Unfinished workflow cleaned"),
        "paragraphs": paragraphs,
        "items": ctx.get("deleted", []),
        "paragraphs_after": (
            [_("Records kept, because other work depends on them:")]
            if ctx.get("kept")
            else []
        ),
        "items_after": ctx.get("kept", []),
    }


def _invitation(ctx):
    return {
        "subject": _("Your ManuSpectrum account"),
        "paragraphs": [
            _(
                "An account has been created for you on ManuSpectrum. Use the "
                "button below to read the terms of use, accept them, choose your "
                "password and set up two-factor authentication."
            ),
            _("The link is personal and works until %(date)s.")
            % {"date": _day(ctx["expires_on"])},
        ],
        "link": ctx["link"],
        "button": _("Activate my account"),
    }


def _anonymisation_notice(ctx):
    if ctx.get("review"):
        paragraphs = [
            _(
                "This account has not been used for a long time. On %(date)s the "
                "administrators decide what happens to it."
            )
            % {"date": _day(ctx["on"])},
            _("Sign in before that date to keep it as it is."),
        ]
    else:
        paragraphs = [
            _(
                "You have not signed in to ManuSpectrum for a long time. On "
                "%(date)s, %(days)s days from now, your account will be "
                "anonymised: your name, e-mail address and password are erased "
                "and the account is closed. Nothing you described is deleted."
            )
            % {"date": _day(ctx["on"]), "days": ctx["days"]},
            _("Sign in before that date to keep your account."),
        ]
    return {
        "subject": _("Your account will be anonymised on %(date)s")
        % {"date": _day(ctx["on"])},
        "paragraphs": paragraphs,
    }


def _anonymisation_summary(ctx):
    paragraphs = [
        _(
            "Accounts without sign-in for %(months)s months: %(anonymised)s "
            "anonymised, %(noticed)s newly warned."
        )
        % {
            "months": ctx["months"],
            "anonymised": ctx["anonymised"],
            "noticed": ctx["noticed"],
        }
    ]
    review = ctx.get("review", [])
    if review:
        paragraphs.append(
            _(
                "Superuser accounts due for a human decision (never anonymised "
                "automatically): %(accounts)s."
            )
            % {"accounts": ", ".join(review)}
        )
    return {"subject": _("Accounts without sign-in"), "paragraphs": paragraphs}


CONTENT = {
    "embargo_notice": _embargo_notice,
    "embargo_lifted": _embargo_lifted,
    "workflow_notice": _workflow_notice,
    "workflow_cleaned": _workflow_cleaned,
    "invitation": _invitation,
    "anonymisation_notice": _anonymisation_notice,
    "anonymisation_summary": _anonymisation_summary,
}


def _sections(kind, context, name, summary):
    """The mail's body once per language, English first."""
    sections = []
    for language in LANGUAGES:
        with translation.override(language):
            content = CONTENT[kind](context)
            paragraphs = list(content["paragraphs"])
            if summary:
                paragraphs.insert(
                    0,
                    _(
                        "Copy for the administrators of the notice sent to "
                        "the people concerned."
                    ),
                )
            sections.append(
                {
                    "language": language,
                    "subject": content["subject"],
                    "greeting": (
                        _("Hello %(name)s,") % {"name": name} if name else _("Hello,")
                    ),
                    "paragraphs": paragraphs,
                    "items": content.get("items", []),
                    "paragraphs_after": content.get("paragraphs_after", []),
                    "items_after": content.get("items_after", []),
                    "link": content.get("link", ""),
                    "button": content.get("button", ""),
                    "contact_email": getattr(settings, "CONTACT_EMAIL", "")
                    or settings.DEFAULT_FROM_EMAIL,
                    "footnote": _(
                        "This is a service notice about your account or your data, so it "
                        "has no unsubscribe link. Questions:"
                    ),
                }
            )
    return sections


def build_message(sections, to):
    """One `EmailMultiAlternatives` with its text and HTML parts and the category header."""
    context = {
        "sections": sections,
        "site_url": settings.PUBLIC_SERVER_ADDRESS.rstrip("/"),
    }
    message = EmailMultiAlternatives(
        subject=SUBJECT_PREFIX
        + " / ".join(dict.fromkeys(s["subject"] for s in sections)),
        body=render_to_string("email/account_notice.txt", context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to],
        headers={CATEGORY_HEADER: CATEGORY},
    )
    message.attach_alternative(
        render_to_string("email/account_notice.htm", context), "text/html"
    )
    return message


def deliver(kind, message):
    """Send *message*, count the outcome and return it; never raises."""
    try:
        message.send(fail_silently=False)
    except Exception as exc:
        logger.warning("Account mail %s failed: %s", kind, type(exc).__name__)
        outcome = FAILED
    else:
        outcome = SENT
    metrics.ACCOUNT_MAILS.labels(
        kind=metrics.bounded(kind, metrics.ACCOUNT_MAIL_KINDS), outcome=outcome
    ).inc()
    return outcome


def _skip(kind):
    metrics.ACCOUNT_MAILS.labels(
        kind=metrics.bounded(kind, metrics.ACCOUNT_MAIL_KINDS), outcome=SKIPPED
    ).inc()
    return SKIPPED


def send_account_mail(user, kind, context, *, allow_inactive=False):
    """Write one notice to *user*; returns `sent`, `failed` or `skipped`.

    An absent, inactive or address-less account is skipped; *allow_inactive*
    keeps a deactivated account that still has an address.
    """
    if kind not in KINDS or not KINDS[kind].to_user or kind not in CONTENT:
        raise ValueError(f"Not an account-mail kind: {kind!r}")
    if (
        user is None
        or not (user.is_active or allow_inactive)
        or not (user.email or "").strip()
    ):
        return _skip(kind)
    sections = _sections(
        kind, context, user.get_full_name() or user.get_username(), False
    )
    return deliver(kind, build_message(sections, user.email.strip()))


def send_summary_mail(kind, context):
    """Write the administrators' copy of a notice, one mail per address.

    Returns the list of outcomes; empty when no recipient is configured.
    """
    if kind not in KINDS or not KINDS[kind].summary:
        raise ValueError(f"No administrator summary for: {kind!r}")
    outcomes = []
    for address in getattr(settings, "ACCOUNT_SUMMARY_RECIPIENTS", []):
        sections = _sections(kind, context, "", KINDS[kind].to_user)
        outcomes.append(deliver(kind, build_message(sections, address)))
    return outcomes


class AccountPasswordResetForm(PasswordResetForm):
    """Arches' reset form (through `PasswordResetView.form_class`) with the account category.

    Replaces `send_mail` of Django's form (django 5.2): same subject and
    templates, plus the prefix, the header and the counter. A failed send is
    counted and swallowed so the answer never tells whether the address exists.
    """

    def send_mail(
        self,
        subject_template_name,
        email_template_name,
        context,
        from_email,
        to_email,
        html_email_template_name=None,
    ):
        subject = "".join(render_to_string(subject_template_name, context).splitlines())
        message = EmailMultiAlternatives(
            subject=SUBJECT_PREFIX + subject,
            body=render_to_string(email_template_name, context),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to_email],
            headers={CATEGORY_HEADER: CATEGORY},
        )
        if html_email_template_name:
            message.attach_alternative(
                render_to_string(html_email_template_name, context), "text/html"
            )
        deliver("password_reset", message)
