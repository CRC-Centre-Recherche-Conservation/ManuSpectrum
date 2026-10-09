from urllib.parse import urlsplit

from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView


@method_decorator(never_cache, name="dispatch")
class AnalysisExplorerPageView(TemplateView):
    """Public shell of the Analysis Explorer (``/{lang}/discover``).

    Renders no resource data: the Vue application reads everything from the
    permission-checked explorer API. The page is sent ``private, no-store``
    (``never_cache``), because the header reads the user. A URL carrying a
    query is marked noindex; the canonical never carries one.
    ``explorer_mirador_url`` is the ``EXPLORER_MIRADOR_URL`` viewer, only
    when it is an absolute http(s) address.
    """

    template_name = "views/pages/analysis-explorer.htm"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["robots_noindex"] = bool(self.request.GET)
        context["explorer_mirador_url"] = _web_address(settings.EXPLORER_MIRADOR_URL)
        return context


def _web_address(value):
    """*value* when it is an absolute http(s) URL, else an empty string."""
    parts = urlsplit(value or "")
    return value if parts.scheme in ("http", "https") and parts.netloc else ""
