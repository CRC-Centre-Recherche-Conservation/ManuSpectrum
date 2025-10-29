from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns
from django.urls import include, path

from manuspectrum.views.iiif_annotation import IIIFAnnotationCollectionView, IIIFAnnotationPageView, IIIFAnnotationView

urlpatterns = [
    path("reports/", include("arches_templating.urls")),
    #path("", include("arches_controlled_lists.urls")),
    path("", include("arches_component_lab.urls")),
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


### Manuspectrum URL

urlpatterns.append(path('iiif/annotation-collection/<uuid:resource_id>',
         IIIFAnnotationCollectionView.as_view(),
         name='iiif-annotation-collection'))

urlpatterns.append(path('iiif/annotation/<uuid:resource_id>',
         IIIFAnnotationView.as_view(),
         name='iiif-annotation'))

urlpatterns.append(path('iiif/annotation-collection/<uuid:resource_id>/page-<int:page_num>',
         IIIFAnnotationPageView.as_view(),
         name='iiif-annotation-page'))