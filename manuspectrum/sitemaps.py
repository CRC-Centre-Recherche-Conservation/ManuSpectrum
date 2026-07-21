from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from arches.app.models.resource import Resource

# Document graph UUID
DOCUMENT_GRAPH_ID = "0c8226c1-11a9-4c48-9601-a7a0c6f2df6b"


class StaticSitemap(Sitemap):
    """Homepage and the public About pages.

    `home` (/index.htm) is deliberately absent: it duplicates `root` and now
    301-redirects to it (see urls.py).
    """

    def items(self):
        return ["root", "about-model", "about-explorer", "about-team", "about-contact"]

    def location(self, item):
        return reverse(item)

    def priority(self, item):
        return 1.0 if item == "root" else 0.8

    def changefreq(self, item):
        return "weekly" if item == "root" else "monthly"


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
