from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns
from django.urls import include, path, re_path

from manuspectrum.views.renderer_config import RendererConfigView, RendererView
from manuspectrum.views.iiif_annotation import (
    IIIFAnnotationCollectionView,
    IIIFAnnotationPageView,
    IIIFAnnotationView,
    IIIFAnnotationCollectionViewV2,
    IIIFAnnotationPageViewV2,
    IIIFAnnotationViewV2,
)


urlpatterns = [
    #path("", include("arches_controlled_lists.urls")),
    path("", include("arches_component_lab.urls")),
    re_path(r"^renderer/(?P<renderer_id>[^\/]+)", RendererView.as_view(), name="renderer"),
    re_path(r"^renderer_config/(?P<renderer_config_id>[^\/]+)", RendererConfigView.as_view(),
                          name="renderer_config"),
    re_path(r"^renderer_config/", RendererConfigView.as_view(), name="renderer_config"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Adds URL pattern to serve media files during development
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns.append(path("", include("arches_querysets.urls")))
urlpatterns.append(path("", include("arches_modular_reports.urls")))

handler400 = "arches.app.views.main.custom_400"
handler403 = "arches.app.views.main.custom_403"
handler404 = "arches.app.views.main.custom_404"
handler500 = "arches.app.views.main.custom_500"

# Ensure Arches core urls are superseded by project-level urls
urlpatterns.append(path('', include('arches.urls')))

# Only handle i18n routing in active project. This will still handle the routes provided by Arches core and Arches applications,
# but handling i18n routes in multiple places causes application errors.
if settings.ROOT_URLCONF == __name__:
    if settings.SHOW_LANGUAGE_SWITCH is True:
        urlpatterns = i18n_patterns(*urlpatterns)

    urlpatterns.append(path("i18n/", include("django.conf.urls.i18n")))


### Manuspectrum URL - IIIF Annotations

# V3 endpoints (IIIF Presentation API 3.0 / Web Annotation)
urlpatterns.append(path('iiif/v3/annotation-collection/<uuid:resource_id>',
         IIIFAnnotationCollectionView.as_view(),
         name='iiif-v3-annotation-collection'))

urlpatterns.append(path('iiif/v3/annotation/<uuid:resource_id>',
         IIIFAnnotationView.as_view(),
         name='iiif-v3-annotation'))

urlpatterns.append(path('iiif/v3/annotation-collection/<uuid:resource_id>/page-<int:page_num>',
         IIIFAnnotationPageView.as_view(),
         name='iiif-v3-annotation-page'))

# V2 endpoints (IIIF Presentation API 2.0 / Open Annotation)
urlpatterns.append(path('iiif/v2/annotation-collection/<uuid:resource_id>',
         IIIFAnnotationCollectionViewV2.as_view(),
         name='iiif-v2-annotation-collection'))

urlpatterns.append(path('iiif/v2/annotation/<uuid:resource_id>',
         IIIFAnnotationViewV2.as_view(),
         name='iiif-v2-annotation'))

urlpatterns.append(path('iiif/v2/annotation-collection/<uuid:resource_id>/page-<int:page_num>',
         IIIFAnnotationPageViewV2.as_view(),
         name='iiif-v2-annotation-page'))