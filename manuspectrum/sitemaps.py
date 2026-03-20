from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from arches.app.models.resource import Resource

# Document graph UUID
DOCUMENT_GRAPH_ID = "0c8226c1-11a9-4c48-9601-a7a0c6f2df6b"


class StaticSitemap(Sitemap):
    """Homepage and other static pages."""

    priority = 1.0
    changefreq = "weekly"

    def items(self):
        return ["root", "home"]

    def location(self, item):
        return reverse(item)


class DocumentSitemap(Sitemap):
    """Public Document resource reports."""

    priority = 0.7
    changefreq = "monthly"

    def items(self):
        return Resource.objects.filter(graph_id=DOCUMENT_GRAPH_ID).values_list(
            "resourceinstanceid", flat=True
        )

    def location(self, resourceid):
        return reverse("resource_report", kwargs={"resourceid": resourceid})
