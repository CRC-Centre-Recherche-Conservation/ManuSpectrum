from django.conf import settings

from manuspectrum.accounts.mailed_links import ROUTES as MAILED_LINK_ROUTES


def language_switch(request):
    """Expose the language-switch flag to every template.

    Arches core only sets this from its own views (BaseManagerView,
    main.index) — plain TemplateViews (the public About pages) never got it.
    The variable name keeps Arches' historical typo ("swtich") on purpose:
    templates shared with core must read the same key.
    """
    return {"show_language_swtich": settings.SHOW_LANGUAGE_SWITCH}


def personal_link(request):
    """Tell every template whether the page's own path can hold a mailed token.

    True on the routes of `accounts.mailed_links`, whatever answers them: the
    « Continue » page, but also the page of a refused CSRF check or of a link
    that is not valid. `ms_base.htm` then writes no canonical link, no
    hreflang alternate and no `og:url`, which would copy the token.
    """
    match = getattr(request, "resolver_match", None)
    return {"personal_link": match is not None and match.url_name in MAILED_LINK_ROUTES}
