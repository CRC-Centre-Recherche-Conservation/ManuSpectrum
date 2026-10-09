"""``GET /api/explorer/events.csv`` and ``events.geojson``: the map's kept events as files (spec 2026-10-09 §3.4).

Below the language boundary; the language is ``lang`` (``export_language``).
Same filters and event types as the events route (``kept_events``), the
visitor's view (D59), one row per (event, material) in the CSV, one feature per
event in the GeoJSON (no geometry when the place is unmapped). The territories
grid is a client model and is never exported. Answers are ``private, no-store``
and never gzipped.
"""

import datetime
import csv
import hashlib
from urllib.parse import urlencode

import orjson
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest, StreamingHttpResponse
from django.urls import reverse
from django.utils import translation
from django.utils.http import content_disposition_header
from django.utils.translation import gettext as _
from django.views import View

from manuspectrum.utils.public_visibility import anonymous_user
from manuspectrum.views.explorer import memo as explorer_memo
from manuspectrum.views.explorer.citations import Home, citation_entry
from manuspectrum.views.explorer.events import kept_events
from manuspectrum.views.explorer.scopes import ScopeError, export_language
from manuspectrum.views.explorer.series import _comment, _Line, neutralise
from manuspectrum.views.explorer.service import cited_analysis, corpus_bundle

HEADER = (
    "event",
    "type",
    "carrier",
    "carrier_model",
    "carrier_name",
    "document",
    "document_name",
    "component",
    "component_name",
    "place",
    "place_name",
    "longitude",
    "latitude",
    "geometry_kind",
    "place_source",
    "date_start",
    "date_end",
    "approximate",
    "material",
    "material_name",
    "material_family",
    "reliability",
    "characterization",
    "analyses",
)
ROWS_PER_CHUNK = 500


def _query_text(query):
    return urlencode(
        sorted((k, v) for k in query for v in query.getlist(k) if k != "lang"),
        safe=":,",
    )


def _digest(text):
    return hashlib.sha1(text.encode(), usedforsecurity=False).hexdigest()[:12]


def _resolve(request):
    language = export_language(request.GET)
    reader = anonymous_user()
    with translation.override(language):
        bundle = corpus_bundle(reader, language, explorer_memo.ticket(reader, language))
        events, _keep, _filters = kept_events(bundle, request.GET)
    return language, bundle, events


def _citation(bundle, events, language, query_text):
    analyses = sorted(
        {a for e in events for a in e["analyses"]}, key=bundle.order.__getitem__
    )
    if not analyses:
        return None
    with translation.override(language):
        page = reverse("analysis-explorer").lstrip("/")
        name = _("%(site)s, map and timeline of the analyses") % {
            "site": settings.APP_TITLE
        }
    link = f"{settings.PUBLIC_SERVER_ADDRESS}{page}?view=map" + (
        f"&{query_text}" if query_text else ""
    )
    cited = [cited_analysis(bundle.by_id[a], None, {}, [], [], {}) for a in analyses]
    home = Home(id=f"explorer-map:{_digest(query_text)}", name=name, permalink=link)
    return citation_entry(
        None,
        cited,
        licences=[],
        language=language,
        accessed=datetime.date.today(),
        home=home,
        link=link,
    )["recommended"]


def _levels(bundle):
    return {
        level["id"]: level["label"]["value"]
        for level in (bundle.certainty or {}).get("levels", [])
    }


def csv_lines(language, bundle, events, query_text):
    """The CSV body: comment lines (title, day, filters, citation, reading of the fields), the header, then the rows."""
    places, materials, levels = (
        bundle.event_places,
        bundle.event_materials,
        _levels(bundle),
    )
    writer = csv.writer(_Line(), lineterminator="\r\n")
    with translation.override(language):
        head = [
            _("%(site)s: events of the map and timeline")
            % {"site": settings.APP_TITLE},
            _("Generated on %(date)s") % {"date": datetime.date.today().isoformat()},
            _("Filters: %(filters)s") % {"filters": query_text or _("none")},
        ]
        citation = _citation(bundle, events, language, query_text)
        if citation:
            head.append(_("Cite as: %(citation)s") % {"citation": citation})
        head.append(
            _(
                "Dates are intervals in years; approximate = dated « circa »; place_source: own = the record's own location, place = the linked place, parent = a broader place it belongs to."
            )
        )
    yield "".join(_comment(line) for line in head)
    yield writer.writerow(HEADER)
    chunk = []
    for event in events:
        place = places.get(event["place"]) if event["place"] else None
        lng_lat = place["lngLat"] if place else None
        component = event["component"] or {}
        date = event["date"]
        base = [
            event["id"],
            event["type"],
            event["carrier"]["id"],
            event["carrier"]["model"],
            neutralise(event["carrier"]["name"]["value"]),
            event["document"]["id"],
            neutralise(event["document"]["name"]["value"]),
            component.get("id", ""),
            neutralise(component.get("name", {}).get("value", "")),
            event["place"] or "",
            neutralise(place["name"]["value"]) if place else "",
            f"{lng_lat[0]:.6f}" if lng_lat else "",
            f"{lng_lat[1]:.6f}" if lng_lat else "",
            place["geometryKind"] if place else "",
            event["placeSource"] or "",
            date["start"] if date["start"] is not None else "",
            date["end"] if date["end"] is not None else "",
            "true" if date["approximate"] else "false",
        ]
        for material in event["materials"] or [None]:
            tail = (
                [
                    material["id"],
                    neutralise(material["name"]["value"]),
                    materials.get(material["id"], {}).get("family", ""),
                    neutralise(levels.get(material["reliability"], "")),
                    material["characterization"],
                ]
                if material
                else ["", "", "", "", ""]
            )
            chunk.append(writer.writerow([*base, *tail, " ".join(event["analyses"])]))
        if len(chunk) >= ROWS_PER_CHUNK:
            yield "".join(chunk)
            chunk = []
    if chunk:
        yield "".join(chunk)


def geojson_body(language, bundle, events, query_text):
    """The GeoJSON body: one Feature per event, its place as a Point (None when unmapped), a ``citation`` member."""
    places, materials, levels = (
        bundle.event_places,
        bundle.event_materials,
        _levels(bundle),
    )
    features = []
    for event in events:
        place = places.get(event["place"]) if event["place"] else None
        features.append(
            {
                "type": "Feature",
                "id": event["id"],
                "geometry": (
                    {"type": "Point", "coordinates": place["lngLat"]}
                    if place and place["lngLat"]
                    else None
                ),
                "properties": {
                    "type": event["type"],
                    "carrier": event["carrier"],
                    "document": event["document"],
                    "component": event["component"],
                    "place": (
                        {
                            "id": place["id"],
                            "name": place["name"],
                            "geometryKind": place["geometryKind"],
                            "extentKm": place["extentKm"],
                            "source": event["placeSource"],
                        }
                        if place
                        else None
                    ),
                    "date": event["date"],
                    "materials": [
                        {
                            **m,
                            "family": materials.get(m["id"], {}).get("family"),
                            "reliabilityLabel": levels.get(m["reliability"]),
                        }
                        for m in event["materials"]
                    ],
                    "analyses": event["analyses"],
                },
            }
        )
    return orjson.dumps(
        {
            "type": "FeatureCollection",
            "generated": datetime.date.today().isoformat(),
            "filters": query_text,
            "citation": _citation(bundle, events, language, query_text),
            "features": features,
        }
    )


class ExplorerEventsCsvView(View):
    """``GET /api/explorer/events.csv?<filters>&lang=``: the kept events, a private streamed download; unknown language → bodyless 400."""

    def get(self, request):
        try:
            language, bundle, events = _resolve(request)
        except ScopeError:
            return HttpResponseBadRequest()
        query_text = _query_text(request.GET)
        response = StreamingHttpResponse(
            csv_lines(language, bundle, events, query_text),
            content_type="text/csv; charset=utf-8",
        )
        response["Content-Disposition"] = content_disposition_header(
            True, f"manuspectrum-events-{_digest(query_text)}.csv"
        )
        response["Cache-Control"] = "private, no-store"
        return response


class ExplorerEventsGeoJsonView(View):
    """``GET /api/explorer/events.geojson?<filters>&lang=``: the kept events as a GeoJSON download; unknown language → bodyless 400."""

    def get(self, request):
        try:
            language, bundle, events = _resolve(request)
        except ScopeError:
            return HttpResponseBadRequest()
        query_text = _query_text(request.GET)
        response = HttpResponse(
            geojson_body(language, bundle, events, query_text),
            content_type="application/geo+json",
        )
        response["Content-Disposition"] = content_disposition_header(
            True, f"manuspectrum-events-{_digest(query_text)}.geojson"
        )
        response["Cache-Control"] = "private, no-store"
        return response
