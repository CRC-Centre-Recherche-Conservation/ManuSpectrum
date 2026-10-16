import json
from urllib.parse import quote

from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views import View
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator

TERM_MAX_LENGTH = 200


def term_filter_url(search_url, term):
    """*search_url* narrowed to one string ``term-filter``, the parameters the Arches search page reads.

    A blank *term* gives *search_url* itself.
    """
    term = (term or "").strip()[:TERM_MAX_LENGTH].strip()
    if not term:
        return search_url
    term_filter = json.dumps(
        [
            {
                "inverted": False,
                "type": "string",
                "context": "",
                "context_label": "",
                "id": term,
                "text": term,
                "value": term,
            }
        ],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return f"{search_url}?paging-filter=1&term-filter={quote(term_filter, safe='!' + chr(39) + '()*')}"


@method_decorator(never_cache, name="dispatch")
class SearchTermRedirectView(View):
    """``GET /{lang}/search-term?q=<term>``: a redirect to the Arches search page filtered on the term.

    The homepage search form submits here, with or without JavaScript, because
    the Arches search page ignores ``q``. The target is always the
    ``search_home`` route of the request language; the term is trimmed and cut
    to ``TERM_MAX_LENGTH`` characters, and a blank one opens the unfiltered
    page.
    """

    def get(self, request):
        return HttpResponseRedirect(
            term_filter_url(reverse("search_home"), request.GET.get("q"))
        )
