from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView

from manuspectrum.utils.public_visibility import is_connected


@method_decorator(never_cache, name="dispatch")
class AnalysisExplorerPageView(TemplateView):
    """Public shell of the Analysis Explorer (``/{lang}/discover``).

    Renders no resource data: the Vue application reads everything from the
    permission-checked explorer API. The page is sent ``private, no-store``
    (``never_cache``), because the header reads the user. A URL carrying a
    query is marked noindex; the canonical never carries one.
    ``explorer_connected`` hands the application the server's own
    ``is_connected`` answer for the reader.
    """

    template_name = "views/pages/analysis-explorer.htm"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["robots_noindex"] = bool(self.request.GET)
        context["explorer_connected"] = is_connected(self.request.user)
        return context
