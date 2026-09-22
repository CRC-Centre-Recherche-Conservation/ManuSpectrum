"""Read and write one resource model's summary configuration.

The configuration form in the designer is a Vue application, and Arches passes
nothing from Knockout into it: it loads the configuration here and saves it
here. The "Save" button of the function manager plays no part for this
function, so the round trip never goes through ``after_function_save`` — the
same normaliser runs on both sides instead.

What is stored is always the cleaned configuration: invalid entries are dropped
rather than kept for a later repair, and the problems travel back in the
response so the form can show them next to the fields that caused them. A write
therefore answers 200 with warnings, never 400 — emptying a configuration is a
legitimate curator action, and one of those warnings is what says it happened.
"""

import json

from django.core.cache import cache
from django.http import Http404, JsonResponse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views import View

from arches.app.models import models
from arches.app.models.system_settings import settings as system_settings
from arches.app.utils.decorators import group_required

from manuspectrum.functions.resource_summary import (
    SUMMARY_FUNCTION_ID,
    bump_config_stamp,
    config_cache_key,
    details,
    normalize_config,
)
from manuspectrum.views.graph_nodes import CONFIG_GROUPS


@method_decorator(group_required(*CONFIG_GROUPS, raise_exception=True), name="dispatch")
class SummaryConfigView(View):
    """``GET|PUT /<lang>/api/summary-config/<graphid>``.

    Answers 404 for anything that is not a published resource model, so a PUT
    can never attach the function to a branch, a draft or an unknown id.
    """

    def get(self, request, graphid):
        graphid = self.resource_model_id(graphid)
        attachment = self.attachment(graphid)
        stored = attachment.config if attachment else details["defaultconfig"]
        config, warnings = normalize_config(stored)
        return JsonResponse(
            {
                "graphid": graphid,
                "config": config,
                "warnings": warnings,
                "attached": attachment is not None,
            }
        )

    def put(self, request, graphid):
        graphid = self.resource_model_id(graphid)
        try:
            body = json.loads(request.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return JsonResponse({"error": _("Malformed JSON body")}, status=400)
        if not isinstance(body, dict):
            return JsonResponse({"error": _("Expected a JSON object")}, status=400)

        stored = self.attachment(graphid)
        config, warnings = normalize_config(body.get("config"))
        if not _holds_entries(config) and _holds_entries(stored and stored.config):
            warnings.append(_("config: an empty configuration replaces the stored one"))
        models.FunctionXGraph.objects.update_or_create(
            function_id=SUMMARY_FUNCTION_ID,
            graph_id=graphid,
            defaults={"config": config},
        )
        cache.delete(config_cache_key(graphid))
        bump_config_stamp()
        return JsonResponse(
            {
                "graphid": graphid,
                "config": config,
                "warnings": warnings,
                "attached": True,
            }
        )

    def resource_model_id(self, graphid):
        """Canonical id of the published resource model, or 404."""
        graphid = str(graphid)
        exists = (
            models.GraphModel.objects.filter(
                graphid=graphid, isresource=True, source_identifier__isnull=True
            )
            .exclude(graphid=system_settings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID)
            .exists()
        )
        if not exists:
            raise Http404("Unknown resource model")
        return graphid

    def attachment(self, graphid):
        return models.FunctionXGraph.objects.filter(
            function_id=SUMMARY_FUNCTION_ID, graph_id=graphid
        ).first()


def _holds_entries(config):
    """Whether a configuration shows anything: one field or one rollup."""
    if not isinstance(config, dict):
        return False
    return bool(config.get("fields") or config.get("rollups"))
