"""Plugin pages, with a 404 for a plugin that does not exist.

Subclass of ``arches.app.views.plugin.PluginView`` (Arches 8.1.5), which looks
the plugin up with ``Plugin.objects.get``, by slug when the URL has one and by
id otherwise, and lets ``Plugin.DoesNotExist`` escape as a 500. Everything
else is the core view.
"""

from django.http import Http404

from arches.app.models import models
from arches.app.views.plugin import PluginView as CorePluginView


class PluginView(CorePluginView):
    """``PluginView`` answering 404 for an unknown slug or id.

    Only ``Plugin.DoesNotExist`` is caught: a missing object of any other
    model inside the core view is a fault, and stays one.
    """

    def get(self, request, pluginid=None, slug=None, path=None):
        try:
            return super().get(request, pluginid=pluginid, slug=slug, path=path)
        except models.Plugin.DoesNotExist:
            raise Http404
