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

Every answer carries the ETag of the stored row; a write naming another version
in ``If-Match`` is refused with 412, so two curators editing one model cannot
overwrite each other silently. ``DELETE`` detaches the function; the receiver in
``signals.py`` drops the cached configuration and the stamp on commit.
"""

import hashlib
import json

import orjson
from django.db import transaction
from django.http import Http404, JsonResponse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views import View

from arches.app.models import models
from arches.app.models.system_settings import settings as system_settings
from arches.app.utils.decorators import group_required

from manuspectrum.functions.resource_summary import (
    SUMMARY_FUNCTION_ID,
    details,
    forget_config,
    normalize_config,
)
from manuspectrum.utils.cache import if_match_allows
from manuspectrum.views.graph_nodes import CONFIG_GROUPS


def config_etag(attachment):
    """Strong validator of what is stored for one model: the row, or its absence."""
    state = {
        "attached": attachment is not None,
        "config": attachment.config if attachment else None,
    }
    digest = hashlib.md5(
        orjson.dumps(state, option=orjson.OPT_SORT_KEYS), usedforsecurity=False
    ).hexdigest()
    return f'"{digest}"'


@method_decorator(group_required(*CONFIG_GROUPS, raise_exception=True), name="dispatch")
class SummaryConfigView(View):
    """``GET|PUT|DELETE /<lang>/api/summary-config/<graphid>``.

    Answers 404 for anything that is not a published resource model, so a PUT
    can never attach the function to a branch, a draft or an unknown id.
    ``If-Match`` is optional on a write: without it the write is unconditional.
    """

    def get(self, request, graphid):
        graphid = self.resource_model_id(graphid)
        return self.answer(graphid, self.attachment(graphid))

    def put(self, request, graphid):
        graphid = self.resource_model_id(graphid)
        try:
            body = json.loads(request.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return JsonResponse({"error": _("Malformed JSON body")}, status=400)
        if not isinstance(body, dict):
            return JsonResponse({"error": _("Expected a JSON object")}, status=400)

        with transaction.atomic():
            self.lock(graphid)
            stored = self.attachment(graphid)
            if not if_match_allows(request, config_etag(stored)):
                return self.conflict(stored)
            config, warnings = normalize_config(body.get("config"))
            if not _holds_entries(config) and _holds_entries(stored and stored.config):
                warnings.append(
                    _("config: an empty configuration replaces the stored one")
                )
            attachment, _created = models.FunctionXGraph.objects.update_or_create(
                function_id=SUMMARY_FUNCTION_ID,
                graph_id=graphid,
                defaults={"config": config},
            )
            transaction.on_commit(lambda: forget_config(graphid))
        return self.answer(graphid, attachment, config=config, warnings=warnings)

    def delete(self, request, graphid):
        """Detach the function; detaching an unattached model answers 200."""
        graphid = self.resource_model_id(graphid)
        with transaction.atomic():
            self.lock(graphid)
            stored = self.attachment(graphid)
            if not if_match_allows(request, config_etag(stored)):
                return self.conflict(stored)
            models.FunctionXGraph.objects.filter(
                function_id=SUMMARY_FUNCTION_ID, graph_id=graphid
            ).delete()
        return self.answer(graphid, None)

    def answer(self, graphid, attachment, config=None, warnings=None):
        """The stored state of one model, as the form reads it, with its ETag."""
        if config is None:
            stored = attachment.config if attachment else details["defaultconfig"]
            config, warnings = normalize_config(stored)
        response = JsonResponse(
            {
                "graphid": graphid,
                "config": config,
                "warnings": warnings,
                "attached": attachment is not None,
            }
        )
        response["ETag"] = config_etag(attachment)
        return response

    def conflict(self, stored):
        """412 carrying the ETag of what is stored now."""
        response = JsonResponse(
            {
                "error": _(
                    "This configuration was changed by someone else since it was "
                    "loaded. Reload it before saving."
                )
            },
            status=412,
        )
        response["ETag"] = config_etag(stored)
        return response

    @staticmethod
    def lock(graphid):
        """Serialise writers of one model, whether or not it is attached yet."""
        models.GraphModel.objects.select_for_update().filter(graphid=graphid).exists()

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
