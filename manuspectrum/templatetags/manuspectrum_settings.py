from django import template
from django.conf import settings
from django.urls import translate_url

register = template.Library()


@register.simple_tag(takes_context=True)
def translated_page_url(context, lang_code):
    """Absolute URL of the current page in *lang_code*.

    Feeds the hreflang alternates and the header language switcher. Uses
    django.urls.translate_url, which understands i18n_patterns (including
    prefix_default_language=False, where 'en' URLs carry no prefix). Query
    strings are dropped on purpose — alternates must mirror the canonical.
    """
    request = context.get("request")
    if request is None:
        return ""
    return translate_url(request.build_absolute_uri(request.path), lang_code)


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
