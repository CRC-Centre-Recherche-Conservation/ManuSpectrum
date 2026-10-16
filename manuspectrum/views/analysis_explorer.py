import re
from urllib.parse import urlsplit

from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView

from manuspectrum.views.explorer.service import FACET_KEYS, parse_filters

APP_VIEWS = ("map", "compare")

# The ``validate`` of the ``uuid`` npm package (``store/url.ts`` ``uuidOrNull``).
DOCUMENT_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
    r"|00000000-0000-0000-0000-000000000000|ffffffff-ffff-ffff-ffff-ffffffffffff"
)


@method_decorator(never_cache, name="dispatch")
class AnalysisExplorerPageView(TemplateView):
    """Public shell of the Analysis Explorer (``/{lang}/discover``).

    Renders no resource data: the Vue application reads everything from the
    permission-checked explorer API. The page is sent ``private, no-store``
    (``never_cache``), because the header reads the user. A URL carrying a
    query is marked noindex; the canonical never carries one.
    ``explorer_mirador_url`` is the ``EXPLORER_MIRADOR_URL`` viewer, only
    when it is an absolute http(s) address. ``initial_screen`` is
    :func:`initial_screen` of the query.
    """

    template_name = "views/pages/analysis-explorer.htm"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["robots_noindex"] = bool(self.request.GET)
        context["explorer_mirador_url"] = _web_address(settings.EXPLORER_MIRADOR_URL)
        context["initial_screen"] = initial_screen(self.request.GET)
        return context


def initial_screen(query):
    """The screen the address opens on, for the page's first paint: ``home``,
    ``results``, ``document``, ``map`` or ``compare``.

    A hint for the server-rendered intro and loading skeleton only: once
    mounted, the application writes ``body[data-explorer-screen]`` from its
    own reading of the address (``screen`` in ``AnalysisExplorer.vue``,
    ``fromQuery`` in ``store/url.ts``), which wins. Active filters are those
    of :func:`parse_filters`: a list facet, ``q`` or ``period``.
    """
    view = query.get("view")
    if view in APP_VIEWS:
        return view
    if DOCUMENT_ID.fullmatch(query.get("doc", "").strip().lower()):
        return "document"
    if query.get("screen") == "results":
        return "results"
    filters, _ = parse_filters(query)
    if filters["q"] or filters["period"] or any(filters[key] for key in FACET_KEYS):
        return "results"
    return "home"


def _web_address(value):
    """*value* when it is an absolute http(s) URL, else an empty string."""
    parts = urlsplit(value or "")
    return value if parts.scheme in ("http", "https") and parts.netloc else ""
