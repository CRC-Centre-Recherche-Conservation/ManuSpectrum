"""Image Service Manager writes, limited to Resource Editor and Resource Reviewer.

Subclass of ``arches.app.views.manifest_manager.ManifestManagerView``
(Arches 8.1.5; identical on dev/8.2.x and dev/9.0.x). ``post`` and
``delete`` pass ``group_required`` first, as Arches' ``TileData`` guards its
own writes; ``get`` and the bodies are the core view's. The page itself may
be open more widely (its ``view_plugin`` grants, deploy/ADMIN.md);
tests/test_manifest_manager_view.py pins the write groups.

Remove this module, its entry in ``urls.py`` and the routing tests once the
installed Arches guards these writes itself: ``CoreGuardCanaryTests`` in the
test module fails at that release.
"""

from django.utils.decorators import method_decorator

from arches.app.utils.decorators import group_required
from arches.app.views.manifest_manager import (
    ManifestManagerView as CoreManifestManagerView,
)


@method_decorator(
    group_required("Resource Editor", "Resource Reviewer", raise_exception=True),
    name="post",
)
@method_decorator(
    group_required("Resource Editor", "Resource Reviewer", raise_exception=True),
    name="delete",
)
class ManifestManagerView(CoreManifestManagerView):
    """``ManifestManagerView`` whose writes require Resource Editor or Resource Reviewer."""
