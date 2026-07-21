from django.conf import settings


def language_switch(request):
    """Expose the language-switch flag to every template.

    Arches core only sets this from its own views (BaseManagerView,
    main.index) — plain TemplateViews (the public About pages) never got it.
    The variable name keeps Arches' historical typo ("swtich") on purpose:
    templates shared with core must read the same key.
    """
    return {"show_language_swtich": settings.SHOW_LANGUAGE_SWITCH}
