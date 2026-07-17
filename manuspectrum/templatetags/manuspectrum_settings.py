from django import template
from django.conf import settings

register = template.Library()


@register.simple_tag
def contact_email():
    """Resolved public contact address, or '' when none is configured yet.

    Mirrors the biblissima_settings tag pattern. Prefers CONTACT_EMAIL, then
    DEFAULT_FROM_EMAIL. Returns '' (never None) so templates render cleanly and
    the contact JS can detect "no address yet".
    """
    return (
        getattr(settings, "CONTACT_EMAIL", "")
        or getattr(settings, "DEFAULT_FROM_EMAIL", "")
        or ""
    )
