from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path, re_path
from django.views.generic import RedirectView, TemplateView

from arches.app.views.auth import PasswordResetView

from manuspectrum.sitemaps import DocumentSitemap, StaticSitemap
from manuspectrum.views.renderer_config import RendererConfigView, RendererView
from manuspectrum.views.biblissima_proxy import (
    BiblissimaAddAltNameView,
    BiblissimaCheckDuplicatesView,
    BiblissimaCreateAllView,
    BiblissimaCreateResourceView,
    BiblissimaEntityView,
    BiblissimaIlluminationDetailView,
    BiblissimaLinkToProjectView,
    BiblissimaManuscriptIlluminationsView,
    BiblissimaSearchManuscriptsView,
    BiblissimaSearchView,
    BiblissimaStatsView,
    BiblissimaSuggestView,
)
from manuspectrum.views.iiif_annotation import (
    IIIFAnnotationCollectionView,
    IIIFAnnotationPageView,
    IIIFAnnotationView,
    IIIFAnnotationCollectionViewV2,
    IIIFAnnotationPageViewV2,
    IIIFAnnotationViewV2,
)
from manuspectrum.views.model_graph import ModelGraphView
from manuspectrum.views.thumbnail import CachedThumbnailView

urlpatterns = [
    # SEO: Arches serves the homepage at both "/" and "/index.htm" (names
    # `root` and `home`) — duplicate content. Project templates only link
    # `root`; anything still hitting /index.htm gets a permanent redirect.
    # MUST stay above the app includes: arches_querysets and
    # arches_controlled_lists each re-include arches.urls, so the first arches
    # `^index.htm` pattern appears as early as those includes.
    path(
        "index.htm",
        RedirectView.as_view(pattern_name="root", permanent=True, query_string=True),
    ),
    # Override password reset to send branded HTML email
    path(
        "password_reset/",
        PasswordResetView.as_view(
            html_email_template_name="registration/password_reset_email_html.html",
        ),
        name="password_reset",
    ),
    # Search thumbnails: the Arches route, answered by the caching subclass.
    # Registered before the app includes so it wins both resolution and
    # {% url 'thumbnail' %}. That is also why it sits above the language
    # boundary although its bytes are language-neutral: the core route it
    # supersedes is itself inside the wrap, and a language-neutral
    # registration would not win the reversal the templates use.
    re_path(
        r"^thumbnail/(?P<resource_id>%s)$" % settings.UUID_REGEX,
        CachedThumbnailView.as_view(),
        name="thumbnail",
    ),
]

# NOTE: media is NOT served from this URLconf, at this or any other point.
# MEDIA_URL is "/files/", the same prefix as Arches' own ``file_access`` route
# (files/<uuid>), and django.conf.urls.static.static() registers a catch-all
# "^files/(?P<path>.*)$" rooted at MEDIA_ROOT. Mounted above the Arches
# include it shadows that route entirely — every /files/<uuid> download becomes
# a 404 on a file literally named <uuid>.
#
# Not mounting it here does not remove the catch-all: arches_controlled_lists
# (urls.py:106) registers the same one under DEBUG, and MEDIA_ROOT is still the
# Python package — see the KNOWN EXPOSURE note in settings.py. Arches serves
# media through files/<uuid>, which resolves the path from the database and
# honours RESTRICT_MEDIA_ACCESS; a front-end alias bypasses both.

urlpatterns.append(path("", include("arches_querysets.urls")))
# arches_controlled_lists ships the Controlled List Manager plugin and the
# reference-datatype APIs; arches_vue_components serves the Vue widgets they
# render with. The latter is namespaced (app_name), the former re-includes
# arches.urls — hence its position below the project's own routes.
urlpatterns.append(path("", include("arches_controlled_lists.urls")))
urlpatterns.append(path("", include("arches_vue_components.urls")))

handler400 = "arches.app.views.main.custom_400"
handler403 = "arches.app.views.main.custom_403"
handler404 = "arches.app.views.main.custom_404"
handler500 = "arches.app.views.main.custom_500"

# Ensure Arches core urls are superseded by project-level urls
urlpatterns.append(path("", include("arches.urls")))

### Manuspectrum URL — public About pages. Registered BEFORE the i18n wrap so
### they get language-prefixed routes (/en/about/team, /fr/about/team) like the
### rest of the UI. API endpoints, robots.txt and sitemap.xml stay below the
### wrap on purpose: they are language-neutral URLs.
for _slug, _name, _tpl in [
    ("about/model", "about-model", "views/pages/conceptual-model.htm"),
    ("about/explorer", "about-explorer", "views/pages/graph-explorer.htm"),
    ("about/team", "about-team", "views/pages/team.htm"),
    ("about/contact", "about-contact", "views/pages/contact.htm"),
]:
    urlpatterns.append(
        path(_slug, TemplateView.as_view(template_name=_tpl), name=_name)
    )

### Model-graph API: wrapped too, so the URL carries the language
### (/en/api/model-graph, /fr/api/model-graph). Its payload is localised, so
### the language belongs in the path rather than in per-request negotiation —
### two languages, two cache keys, two URLs. Templates reverse
### {% url 'model-graph' %} per request language, so consumers pick the right
### one for free.
urlpatterns.append(
    path("api/model-graph", ModelGraphView.as_view(), name="model-graph")
)

if settings.ROOT_URLCONF == __name__:
    # set_language must live INSIDE i18n_patterns: Django's view calls
    # translate_url() with the REQUEST's active language, so the request has to
    # carry the language it is switching AWAY from. Wrapped, the Arches
    # switcher posts to /fr/i18n/setlang from French pages and to
    # /en/i18n/setlang from English ones.
    urlpatterns.append(path("i18n/", include("django.conf.urls.i18n")))

    if settings.SHOW_LANGUAGE_SWITCH is True:
        # Every URL under the wrap carries its language: /en/about/team,
        # /fr/about/team, and no bare twin. An unprefixed path 404s inside the
        # wrap; LocaleMiddleware then redirects it to the prefixed URL for the
        # language it negotiates — the django_language cookie first, then the
        # Accept-Language header, then LANGUAGE_CODE. A prefix already in the
        # path always wins, so a shared link keeps its language.
        #
        # That redirect is a 302 and must stay one: its target depends on the
        # request, which is why Django patches Vary: Accept-Language, Cookie
        # onto it. A 301 is cached by the browser for good, so a visitor who
        # once arrived with a French browser would keep landing on /fr/ after
        # switching the site to English — the request would never reach the
        # server again.
        #
        # ┌───────────────────────────────────────────────────────────────────┐
        # │ OPS / SECURITY — verify BEFORE deploying with French enabled.      │
        # │ Wrapping ALL routes means every Arches path resolves ONLY under a  │
        # │ language prefix: /en/admin/, /fr/admin/, /en/rdm/, /fr/graph/ …    │
        # │ Django auth is INTACT (these still 302 to the login), so this is   │
        # │ NOT an app-level bypass. BUT if the edge (nginx / WAF / reverse    │
        # │ proxy) restricts admin or internal tooling by PATH PREFIX          │
        # │ — e.g. `location /admin/ { allow 10.0.0.0/8; deny all; }` —        │
        # │ that rule now matches NOTHING and guards nothing.                  │
        # │ Action: make the edge ACLs match the language prefix, e.g.         │
        # │   location ~ ^/(en|fr)/admin/  { … }                               │
        # │ (regex, or duplicate the location blocks). Tracked as GH issue.    │
        # └───────────────────────────────────────────────────────────────────┘
        urlpatterns = i18n_patterns(*urlpatterns, prefix_default_language=True)

# ============================================================================
# LANGUAGE BOUNDARY — everything appended BELOW this line sits OUTSIDE
# i18n_patterns and is therefore language-NEUTRAL: one URL, no /en/ or /fr/
# twin, and no redirect either — the path resolves, so LocaleMiddleware never
# sees the 404 it would rewrite. Correct for machine endpoints: Biblissima
# proxy, IIIF, robots.txt, sitemap.xml. Anything a HUMAN reads in a language
# (pages, or APIs whose payload is localised like model-graph) must be
# registered ABOVE the wrap.
# ============================================================================

### Manuspectrum URL - Biblissima proxy

urlpatterns.append(
    path(
        "api/biblissima/suggest",
        BiblissimaSuggestView.as_view(),
        name="biblissima-suggest",
    )
)
urlpatterns.append(
    path(
        "api/biblissima/entity/<str:qid>",
        BiblissimaEntityView.as_view(),
        name="biblissima-entity",
    )
)
urlpatterns.append(
    path(
        "api/biblissima/search",
        BiblissimaSearchView.as_view(),
        name="biblissima-search",
    )
)
urlpatterns.append(
    path(
        "api/biblissima/search-manuscripts",
        BiblissimaSearchManuscriptsView.as_view(),
        name="biblissima-search-manuscripts",
    )
)
urlpatterns.append(
    path(
        "api/biblissima/check-duplicates",
        BiblissimaCheckDuplicatesView.as_view(),
        name="biblissima-check-duplicates",
    )
)
urlpatterns.append(
    path(
        "api/biblissima/manuscript-illuminations",
        BiblissimaManuscriptIlluminationsView.as_view(),
        name="biblissima-manuscript-illuminations",
    )
)
urlpatterns.append(
    path(
        "api/biblissima/illumination/<str:ifdata_hash>",
        BiblissimaIlluminationDetailView.as_view(),
        name="biblissima-illumination-detail",
    )
)
urlpatterns.append(
    path(
        "api/biblissima/create-resource",
        BiblissimaCreateResourceView.as_view(),
        name="biblissima-create-resource",
    )
)
urlpatterns.append(
    path(
        "api/biblissima/create-all",
        BiblissimaCreateAllView.as_view(),
        name="biblissima-create-all",
    )
)
urlpatterns.append(
    path(
        "api/biblissima/add-alt-name",
        BiblissimaAddAltNameView.as_view(),
        name="biblissima-add-alt-name",
    )
)
urlpatterns.append(
    path(
        "api/biblissima/stats",
        BiblissimaStatsView.as_view(),
        name="biblissima-stats",
    )
)
urlpatterns.append(
    path(
        "api/biblissima/link-to-project",
        BiblissimaLinkToProjectView.as_view(),
        name="biblissima-link-to-project",
    )
)

### Manuspectrum URL - IIIF Annotations

# V3 endpoints (IIIF Presentation API 3.0 / Web Annotation)
urlpatterns.append(
    path(
        "iiif/v3/annotation-collection/<uuid:resource_id>",
        IIIFAnnotationCollectionView.as_view(),
        name="iiif-v3-annotation-collection",
    )
)

urlpatterns.append(
    path(
        "iiif/v3/annotation/<uuid:resource_id>",
        IIIFAnnotationView.as_view(),
        name="iiif-v3-annotation",
    )
)

urlpatterns.append(
    path(
        "iiif/v3/annotation-collection/<uuid:resource_id>/page-<int:page_num>",
        IIIFAnnotationPageView.as_view(),
        name="iiif-v3-annotation-page",
    )
)

# V2 endpoints (IIIF Presentation API 2.0 / Open Annotation)
urlpatterns.append(
    path(
        "iiif/v2/annotation-collection/<uuid:resource_id>",
        IIIFAnnotationCollectionViewV2.as_view(),
        name="iiif-v2-annotation-collection",
    )
)

urlpatterns.append(
    path(
        "iiif/v2/annotation/<uuid:resource_id>",
        IIIFAnnotationViewV2.as_view(),
        name="iiif-v2-annotation",
    )
)

urlpatterns.append(
    path(
        "iiif/v2/annotation-collection/<uuid:resource_id>/page-<int:page_num>",
        IIIFAnnotationPageViewV2.as_view(),
        name="iiif-v2-annotation-page",
    )
)

### Renderer metadata and XY renderer configuration.
###
### Language-neutral: nothing here is cached, and the only translated strings
### are error messages, which LocaleMiddleware still resolves from the cookie
### or the Accept-Language header on an unprefixed path. Above the wrap these
### take POST and DELETE, and a bare write would be answered with a redirect
### that a browser replays as a GET — a silent no-op instead of a 403.
### Localised payloads that ARE cached, like model-graph, stay above the wrap
### so the language keys the cache.
urlpatterns += [
    re_path(
        r"^renderer/(?P<renderer_id>[^\/]+)", RendererView.as_view(), name="renderer"
    ),
    # A UUID converter, not a catch-all segment. The two protections on a
    # seeded preset are decided by comparing the captured value against
    # canonical ids, while the row it names is resolved by a UUIDField that
    # also accepts uppercase, hyphen-free, braced and urn:-prefixed spellings.
    # A permissive pattern let those two disagree, and "7A1C…" skipped the
    # guard while deleting the row it protects. Django's converter admits the
    # canonical form only; anything else is a 404 before the view is reached.
    # The frontend only ever echoes server-returned ids, so no client changes.
    path(
        "renderer_config/<uuid:renderer_config_id>",
        RendererConfigView.as_view(),
        name="renderer_config",
    ),
    # Anchored: without the ``$`` this pattern also swallowed every id the
    # converter above rejects, so a malformed one fell through to the create
    # branch and silently made a new configuration instead of failing.
    re_path(
        r"^renderer_config/$", RendererConfigView.as_view(), name="renderer_config"
    ),
]


### SEO — robots.txt & sitemap.xml

sitemaps = {
    "static": StaticSitemap,
    "documents": DocumentSitemap,
}

urlpatterns.append(
    path(
        "robots.txt",
        TemplateView.as_view(template_name="robots.txt", content_type="text/plain"),
        name="robots",
    )
)
urlpatterns.append(
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    )
)
