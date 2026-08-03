from django.conf import settings
from django.conf.urls.static import static
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

urlpatterns = [
    # SEO: Arches serves the homepage at both "/" and "/index.htm" (names
    # `root` and `home`) — duplicate content. Project templates only link
    # `root`; anything still hitting /index.htm gets a permanent redirect.
    # MUST stay above the app includes: arches_querysets re-includes
    # arches.urls, so the first arches `^index.htm` pattern appears as early
    # as that include.
    path(
        "index.htm",
        RedirectView.as_view(pattern_name="root", permanent=True, query_string=True),
    ),
    # path("", include("arches_controlled_lists.urls")),
    # Override password reset to send branded HTML email
    path(
        "password_reset/",
        PasswordResetView.as_view(
            html_email_template_name="registration/password_reset_email_html.html",
        ),
        name="password_reset",
    ),
    re_path(
        r"^renderer/(?P<renderer_id>[^\/]+)", RendererView.as_view(), name="renderer"
    ),
    re_path(
        r"^renderer_config/(?P<renderer_config_id>[^\/]+)",
        RendererConfigView.as_view(),
        name="renderer_config",
    ),
    re_path(r"^renderer_config/", RendererConfigView.as_view(), name="renderer_config"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Adds URL pattern to serve media files during development
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns.append(path("", include("arches_querysets.urls")))

handler400 = "arches.app.views.main.custom_400"
handler403 = "arches.app.views.main.custom_403"
handler404 = "arches.app.views.main.custom_404"
handler500 = "arches.app.views.main.custom_500"

# Ensure Arches core urls are superseded by project-level urls
urlpatterns.append(path("", include("arches.urls")))

### Manuspectrum URL — public About pages. Registered BEFORE the i18n wrap so
### they get language-prefixed routes (/fr/about/team) like the rest of the UI.
### API endpoints, robots.txt and sitemap.xml stay below the wrap on purpose:
### they are language-neutral URLs.
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
### (/api/model-graph = EN, /fr/api/model-graph = FR). With
### prefix_default_language=False Django forces the default language on any
### unprefixed URL — a cookie can never select FR outside the wrap, so the
### language MUST live in the path. Templates reverse {% url 'model-graph' %}
### per request language, so consumers pick the right one for free.
urlpatterns.append(
    path("api/model-graph", ModelGraphView.as_view(), name="model-graph")
)

if settings.ROOT_URLCONF == __name__:
    # set_language must live INSIDE i18n_patterns: Django's view calls
    # translate_url() with the REQUEST's active language, and with
    # prefix_default_language=False an unprefixed /i18n/setlang request is
    # forced to English — resolve('/fr/…') then Resolver404s inside
    # translate_url and switching back to English silently no-ops (the
    # switcher bounced users back to the French page). Wrapped, the Arches
    # switcher posts to /fr/i18n/setlang from French pages and the request
    # carries its language.
    urlpatterns.append(path("i18n/", include("django.conf.urls.i18n")))

    if settings.SHOW_LANGUAGE_SWITCH is True:
        # prefix_default_language=False: English keeps its historical
        # unprefixed URLs (/, /about/team — already indexed and linked),
        # French gets /fr/…. LocaleMiddleware 302s a fr-cookie visitor from
        # an unprefixed URL to its /fr/ twin.
        #
        # ┌───────────────────────────────────────────────────────────────────┐
        # │ OPS / SECURITY — verify BEFORE deploying with French enabled.      │
        # │ Wrapping ALL routes means every Arches path now also resolves      │
        # │ under /fr/ : /fr/admin/, /fr/rdm/, /fr/graph/, /fr/plugins/ …      │
        # │ Django auth is INTACT (these still 302 to the login), so this is   │
        # │ NOT an app-level bypass. BUT if the edge (nginx / WAF / reverse    │
        # │ proxy) restricts admin or internal tooling by PATH PREFIX          │
        # │ — e.g. `location /admin/ { allow 10.0.0.0/8; deny all; }` —        │
        # │ the /fr/ twins slip past that rule.                               │
        # │ Action: make the edge ACLs match the language prefix too, e.g.     │
        # │   location ~ ^/(fr/)?admin/  { … }                                 │
        # │ (regex, or duplicate the location blocks). Tracked as GH issue.    │
        # └───────────────────────────────────────────────────────────────────┘
        urlpatterns = i18n_patterns(*urlpatterns, prefix_default_language=False)

# ============================================================================
# LANGUAGE BOUNDARY — everything appended BELOW this line sits OUTSIDE
# i18n_patterns and is therefore language-NEUTRAL (one URL, no /fr/ twin,
# active language forced to English by prefix_default_language=False).
# Correct for machine endpoints: Biblissima proxy, IIIF, robots.txt,
# sitemap.xml. Anything a HUMAN reads in a language (pages, or APIs whose
# payload is localised like model-graph) must be registered ABOVE the wrap.
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
