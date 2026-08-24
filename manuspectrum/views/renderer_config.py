#################################
# Arches for Science
# GPL-3.0 license
# https://github.com/archesproject/arches-for-science
#################################


import logging
from django.utils.decorators import method_decorator
from arches.app.utils.decorators import group_required
from arches.app.views.api import APIBase
from manuspectrum.models import RendererConfig
from manuspectrum.views.permissions import EDITOR_GROUPS
from manuspectrum.constants.xy_presets import is_seeded_preset
from arches.app.models import models
from arches.app.utils.response import JSONResponse
from django.http import HttpResponseNotFound
from django.db.models import Q
from django.utils.translation import gettext as _
from arches.app.utils.betterJSONSerializer import JSONSerializer, JSONDeserializer

logger = logging.getLogger(__name__)


class RendererView(APIBase):
    def get(self, request, renderer_id=None):
        renderer = {}
        if renderer_id is None:
            return JSONResponse(
                []
            )  # this should be fixed later to return all renderers; not currently used.
        else:
            renderer_config = RendererConfig.objects.filter(rendererid=renderer_id)

            if renderer_config:
                # `protected` drives the lock in the configuration list. The
                # real barrier is server-side, below; this only spares a curator
                # a click that was always going to be refused.
                renderer["configs"] = [
                    {**config, "protected": is_seeded_preset(config["configid"])}
                    for config in renderer_config.values()
                ]
                return JSONResponse(renderer)
            else:
                return HttpResponseNotFound(_("<h1>Renderers do not exist</h1>"))


def in_use_query(config_id, file_nodes):
    """Build the lookup for "some stored file still points at this config".

    ``file_nodes`` is an iterable of ``(node_id, nodegroup_id)`` pairs. Kept
    separate from the query's execution so the two regressions this replaces
    stay locked by a test that needs no database:

    * it asked a single hard-coded nodegroup id inherited from Arches for
      Science, present in no ManuSpectrum graph;
    * it only looked at entry ``0``, while a measurement tile can hold an
      instrument's original next to its CSV derivative.
    """
    query = Q()
    for node_id, nodegroup_id in file_nodes:
        query |= Q(
            nodegroup_id=nodegroup_id,
            # JSONB containment: matches an entry carrying this configuration
            # anywhere in the array, whatever its position.
            **{f"data__{node_id}__contains": [{"rendererConfig": str(config_id)}]},
        )
    return query


def configuration_is_in_use(config_id):
    """True when any stored file still points at this renderer configuration."""
    file_nodes = list(
        models.Node.objects.filter(datatype="file-list")
        .values_list("nodeid", "nodegroup_id")
        .distinct()
    )
    if not file_nodes:
        return False
    return models.TileModel.objects.filter(in_use_query(config_id, file_nodes)).exists()


class RendererConfigView(APIBase):
    def get(self, request, renderer_config_id=None):
        if renderer_config_id is None:
            return JSONResponse(RendererConfig.objects.all().values())

        else:
            renderer_config = RendererConfig.objects.filter(configid=renderer_config_id)

            if renderer_config:
                return JSONResponse(renderer_config.values())
            else:
                return HttpResponseNotFound(
                    _("<h1>Renderers config does not exist</h1>")
                )

    @method_decorator(group_required(*EDITOR_GROUPS, raise_exception=True))
    def post(self, request, renderer_config_id=None):
        body = JSONDeserializer().deserialize(request.body)
        if renderer_config_id:
            # The seeded presets are the shared baseline every technique-derived
            # configuration points at. One edit reaches every analysis using that
            # technique, across every user — so it takes a superuser.
            if is_seeded_preset(renderer_config_id) and not request.user.is_superuser:
                return JSONResponse(
                    {
                        "saved": False,
                        "reason": "protected",
                        "message": _(
                            "This configuration is part of the shared baseline "
                            "and can only be edited by an administrator. "
                            "Duplicate it to make your own."
                        ),
                    },
                    status=403,
                )
            renderer_config = RendererConfig.objects.get(configid=renderer_config_id)
            renderer_config.rendererid = body["rendererId"]
            renderer_config.name = body["name"]
            renderer_config.description = body["description"]
            body.pop("rendererId")
            body.pop("name")
            body.pop("description")
            renderer_config.config = body
            renderer_config.save()
        else:
            renderer_config = RendererConfig.objects.create(
                rendererid=body["rendererId"], name=body["name"], config=body
            )

        response_dict = JSONSerializer().serialize(renderer_config)

        return JSONResponse(response_dict)

    @method_decorator(group_required(*EDITOR_GROUPS, raise_exception=True))
    def delete(self, request, renderer_config_id):
        # Not even for a superuser: a migration re-creates these on every deploy,
        # so deleting one only orphans the files pointing at it until the next
        # migrate silently brings it back. Edit it, or stop using it.
        if is_seeded_preset(renderer_config_id):
            return JSONResponse(
                {
                    "deleted": False,
                    "reason": "protected",
                    "message": _(
                        "This configuration is part of the shared baseline "
                        "and cannot be deleted."
                    ),
                },
                status=403,
            )

        renderer_config = RendererConfig.objects.get(configid=renderer_config_id)
        renderer_used = configuration_is_in_use(renderer_config_id)
        if not renderer_used:
            renderer_config.delete()
            response_dict = {"deleted": JSONSerializer().serialize(renderer_config)}
        else:
            response_dict = {"deleted": False}

        return JSONResponse(response_dict)
