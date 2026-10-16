from django import template
from django.conf import settings
from django.core.exceptions import DisallowedHost
from django.urls import translate_url

register = template.Library()


@register.simple_tag(takes_context=True)
def translated_page_url(context, lang_code):
    """Absolute URL of the current page in *lang_code*.

    Feeds the hreflang alternates and the header language switcher. Uses
    django.urls.translate_url, which understands i18n_patterns and swaps one
    language prefix for another. Query strings are dropped on purpose —
    alternates must mirror the canonical.

    SECURITY (open redirect): do NOT pass a request path to
    build_absolute_uri() as its `location` arg. A path beginning with
    "//evil.com/…" (WSGI keeps the double slash, RFC 3986) makes
    build_absolute_uri resolve `evil.com` as the netloc — the switcher/hreflang
    then point off-site. Two guards:
      1. resolver_match is None on any unrouted URL — which is exactly the 404
         page that renders this tag. Returning "" there means only genuinely
         routed paths, which cannot carry a "//host" segment, are ever
         reflected.
      2. Build the absolute URL from scheme+host explicitly and only translate
         the (routed) path, so the host can never come from the path.
    """
    request = context.get("request")
    if request is None or request.resolver_match is None:
        return ""
    path = translate_url(request.path, lang_code)
    return f"{request.scheme}://{request.get_host()}{path}"


@register.simple_tag(takes_context=True)
def site_origin(context):
    """scheme://host of the current request, or "" when its Host is not allowed.

    The 400 page renders for a request whose Host failed ALLOWED_HOSTS
    (DisallowedHost raised by CommonMiddleware): calling request.get_host()
    again while rendering it raises once more and turns the 400 into a 500.
    """
    request = context.get("request")
    if request is None:
        return ""
    try:
        return f"{request.scheme}://{request.get_host()}"
    except DisallowedHost:
        return ""


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
