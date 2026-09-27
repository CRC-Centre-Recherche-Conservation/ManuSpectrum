"""The ``xyReading`` extension, version 1: its JSON-LD context, its JSON Schema and its documentation page.

The context (``application/ld+json``) and the schema (served verbatim) carry
the IIIF CORS headers; the documentation page is HTML in the language
LocaleMiddleware negotiates. All three are ``public, max-age=86400``.
"""

from pathlib import Path

import orjson
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View

from manuspectrum.constants.xy_presets import XY_PRESETS
from manuspectrum.iiif import ids, xy_reading
from manuspectrum.views.iiif.cors import iiif_cors

LONG_CACHE = "public, max-age=86400"
SCHEMA = Path(xy_reading.__file__).parent / "schemas" / "xy-reading-1.schema.json"


def _long(response):
    response["Cache-Control"] = LONG_CACHE
    return response


@method_decorator(iiif_cors, name="dispatch")
class XYReadingContextView(View):
    http_method_names = ["get", "head", "options"]

    def get(self, request):
        return _long(
            HttpResponse(
                orjson.dumps(xy_reading.context_document()),
                content_type="application/ld+json",
            )
        )


@method_decorator(iiif_cors, name="dispatch")
class XYReadingSchemaView(View):
    http_method_names = ["get", "head", "options"]

    def get(self, request):
        return _long(
            HttpResponse(SCHEMA.read_bytes(), content_type="application/schema+json")
        )


class XYReadingDocView(View):
    http_method_names = ["get", "head"]

    def get(self, request):
        example = {
            "id": ids.data_series("0f3a9c2d-0000-4000-8000-0000000000c7"),
            "type": "Dataset",
            "format": "text/csv",
            "xyReading": xy_reading.xy_reading(
                xy_reading.RawFile(
                    id="0f3a9c2d-0000-4000-8000-0000000000c7",
                    name="GRE76-FORS-0004.csv",
                    media_type="text/csv",
                    path="",
                ),
                XY_PRESETS["fors"]["config"],
            ),
        }
        return _long(
            render(
                request,
                "iiif/xy_reading_1.htm",
                {
                    "context_url": ids.xy_context(),
                    "schema_url": ids.xy_schema(),
                    "login_url": ids.auth_login(),
                    "token1_url": ids.auth_token(1),
                    "token2_url": ids.auth_token(2),
                    "logout_url": ids.auth_logout(),
                    "token_minutes": settings.IIIF_AUTH_TOKEN_TTL // 60,
                    "cookie_hours": settings.IIIF_AUTH_COOKIE_TTL // 3600,
                    "example": orjson.dumps(
                        example, option=orjson.OPT_INDENT_2
                    ).decode(),
                },
            )
        )
