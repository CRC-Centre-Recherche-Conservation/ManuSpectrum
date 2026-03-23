import logging
import re
import uuid
from functools import lru_cache
from html import unescape

import requests
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import cache_page

from arches.app.models.models import ResourceInstance, Value
from arches.app.models.tile import Tile

logger = logging.getLogger(__name__)

BIBLISSIMA_WIKIBASE = "https://data.biblissima.fr/w/api.php"
BIBLISSIMA_IIIF_MANIFEST = "https://portail.biblissima.fr/iiif/manifest"

REQUEST_TIMEOUT = 10

# Wikibase property IDs
P2 = "P2"  # nature de l'élément
P129 = "P129"  # identifiant Portail Biblissima
P194 = "P194"  # collection (institution)
P195 = "P195"  # cote (shelfmark)
P196 = "P196"  # manifeste IIIF
P197 = "P197"  # numérisation URL
P270 = "P270"  # identifiant Mandragore
P354 = "P354"  # auteur

# Arches graph UUIDs
DOCUMENT_GRAPH_ID = "0c8226c1-11a9-4c48-9601-a7a0c6f2df6b"
COMPONENT_GRAPH_ID = "d47595b4-f8a6-419c-8f33-b388206280c4"
PROJECT_GRAPH_ID = "87a4319d-3ca5-43f6-88cc-a7379fba67f6"
PLACE_GRAPH_ID = "3f2b036a-b65d-474d-b692-0b21903655c5"
PERSON_GRAPH_ID = "5bf45c85-84cd-4a76-b64a-3ffe86eea1b8"
GROUP_GRAPH_ID = "4f447dca-dbb3-48d0-bc90-3f2935db8b8c"

# --- Document nodegroups & nodes ---
DOC_NAME_NG = "3e132cfd-7038-11ef-8753-0575b5bada34"
DOC_NAME_LABEL = "3e132d00-7038-11ef-8753-0575b5bada34"
DOC_NAME_LANGUAGE = "3e132cff-7038-11ef-8753-0575b5bada34"
DOC_NAME_TYPE = "3e132d01-7038-11ef-8753-0575b5bada34"

DOC_IDENTIFIER_NG = "413fd755-7038-11ef-8753-0575b5bada34"
DOC_IDENTIFIER_VALUE = "413fd757-7038-11ef-8753-0575b5bada34"
DOC_IDENTIFIER_SOURCE = "413fd758-7038-11ef-8753-0575b5bada34"
DOC_IDENTIFIER_TYPE = "413fd759-7038-11ef-8753-0575b5bada34"

DOC_TYPE_NG = "9d757c50-7041-11ef-8753-0575b5bada34"
DOC_TYPE_NODE = "9d757c50-7041-11ef-8753-0575b5bada34"

DOC_STATEMENT_NG = "44a2e1a3-7038-11ef-8753-0575b5bada34"
DOC_STATEMENT_CONTENT = "44a2e1a7-7038-11ef-8753-0575b5bada34"
DOC_STATEMENT_LANGUAGE = "44a2e1aa-7038-11ef-8753-0575b5bada34"
DOC_STATEMENT_SOURCE = "44a2e1ad-7038-11ef-8753-0575b5bada34"
DOC_STATEMENT_TYPE = "44a2e1ac-7038-11ef-8753-0575b5bada34"

DOC_FACSIMILES_NG = "76cb5191-e4e4-4fd4-8d1d-f040292290b4"
DOC_FACSIMILES_NODE = "76cb5191-e4e4-4fd4-8d1d-f040292290b4"

DOC_LOCATION_NG = "a53152c8-703e-11ef-8753-0575b5bada34"
DOC_LOCATION_NODE = "a53152c8-703e-11ef-8753-0575b5bada34"
DOC_LOCATION_LITERAL = "c764ad5c-d1b6-11ef-8532-495867ec2258"

DOC_OWNER_NG = "ce94a73c-703e-11ef-8753-0575b5bada34"
DOC_OWNER_NODE = "ce94a73c-703e-11ef-8753-0575b5bada34"

DOC_PRODUCTION_NG = "fb5d903b-7052-11ef-8753-0575b5bada34"
DOC_PROD_ACTORS = "fb5d904d-7052-11ef-8753-0575b5bada34"
DOC_PROD_MOTIVATED = "fb5d904a-7052-11ef-8753-0575b5bada34"
DOC_PROD_PLACE = "fb5d904f-7052-11ef-8753-0575b5bada34"
DOC_PROD_INFLUENCES = "fb5d9045-7052-11ef-8753-0575b5bada34"
DOC_PROD_DATE_START = "fb5d9050-7052-11ef-8753-0575b5bada34"
DOC_PROD_DATE_END = "fb5d904c-7052-11ef-8753-0575b5bada34"
DOC_PROD_TIME_TYPE = "fb5d9042-7052-11ef-8753-0575b5bada34"
DOC_PROD_CULTURAL = "5b462970-edfe-11ef-9a8f-89acc4447d22"
DOC_PROD_TECHNIQUES = "2577f662-d1b0-11ef-8532-495867ec2258"

DOC_PERIOD_NG = "ee5666f5-edf3-11ef-9a8f-89acc4447d22"
DOC_PERIOD_ABSOLUTE = "ee5666fc-edf3-11ef-9a8f-89acc4447d22"
DOC_PERIOD_PRODUCTION = "ee5666f5-edf3-11ef-9a8f-89acc4447d22"

DOC_DIMENSION_NG = "dd725542-7039-11ef-8753-0575b5bada34"
DOC_DIMENSION_TYPE = "66351560-703d-11ef-8753-0575b5bada34"
DOC_DIMENSION_UNIT = "f0f2f252-7039-11ef-8753-0575b5bada34"
DOC_DIMENSION_VALUE = "1dc76d80-703a-11ef-8753-0575b5bada34"

DOC_COMPOSED_NG = "e3bfe85e-703b-11ef-8753-0575b5bada34"
DOC_COMPOSED_TYPE = "7153adc2-704f-11ef-8753-0575b5bada34"
DOC_COMPOSED_UNIT = "7153adc3-704f-11ef-8753-0575b5bada34"
DOC_COMPOSED_VALUE = "7153adc1-704f-11ef-8753-0575b5bada34"

DOC_PART_OF_NG = "e4166b5c-d1b1-11ef-8532-495867ec2258"
DOC_PART_OF_NODE = "e4166b5c-d1b1-11ef-8532-495867ec2258"

# Project studied objects
PROJECT_STUDIED_OBJECTS_NG = "a8fb3c9e-bbc4-11ef-bd5f-ed806b645d76"
PROJECT_STUDIED_OBJECTS_NODE = "a8fb3c9e-bbc4-11ef-bd5f-ed806b645d76"

# --- Component nodegroups & nodes ---
COMP_TYPE_NG = "0474f0de-711e-11ef-be19-21cc18cdd2a8"
COMP_TYPE_NODE = "0474f0de-711e-11ef-be19-21cc18cdd2a8"

COMP_PARENT_DOC_NG = "26524186-710d-11ef-be19-21cc18cdd2a8"
COMP_PARENT_DOC_NODE = "e0bd205a-711b-11ef-be19-21cc18cdd2a8"

COMP_ICONOGRAPHIC_NG = "56018940-ee09-11ef-9a8f-89acc4447d22"
COMP_ICONOGRAPHIC_NODE = "56018940-ee09-11ef-9a8f-89acc4447d22"

COMP_NAME_NG = "96e53203-710b-11ef-be19-21cc18cdd2a8"
COMP_NAME_LABEL = "96e53206-710b-11ef-be19-21cc18cdd2a8"
COMP_NAME_LANGUAGE = "96e53205-710b-11ef-be19-21cc18cdd2a8"
COMP_NAME_TYPE = "96e53207-710b-11ef-be19-21cc18cdd2a8"

COMP_CONTEXT_NG = "96ef1746-711e-11ef-be19-21cc18cdd2a8"
COMP_CONTEXT_NODE = "96ef1746-711e-11ef-be19-21cc18cdd2a8"

COMP_IDENTIFIER_NG = "a9c93cbb-710b-11ef-be19-21cc18cdd2a8"
COMP_IDENTIFIER_VALUE = "a9c93cbd-710b-11ef-be19-21cc18cdd2a8"
COMP_IDENTIFIER_SOURCE = "a9c93cbe-710b-11ef-be19-21cc18cdd2a8"
COMP_IDENTIFIER_TYPE = "a9c93cbf-710b-11ef-be19-21cc18cdd2a8"

COMP_STATEMENT_NG = "b6dfa2e1-710b-11ef-be19-21cc18cdd2a8"
COMP_STATEMENT_CONTENT = "b6dfa2e5-710b-11ef-be19-21cc18cdd2a8"
COMP_STATEMENT_LANGUAGE = "b6dfa2e8-710b-11ef-be19-21cc18cdd2a8"
COMP_STATEMENT_SOURCE = "b6dfa2eb-710b-11ef-be19-21cc18cdd2a8"
COMP_STATEMENT_TYPE = "b6dfa2ea-710b-11ef-be19-21cc18cdd2a8"

COMP_PRODUCTION_NG = "c31205b9-71b4-11ef-bb52-6361ac5a97ee"
COMP_PROD_ACTORS = "c31205cb-71b4-11ef-bb52-6361ac5a97ee"
COMP_PROD_MOTIVATED = "c31205c8-71b4-11ef-bb52-6361ac5a97ee"
COMP_PROD_PLACE = "c31205cd-71b4-11ef-bb52-6361ac5a97ee"
COMP_PROD_INFLUENCES = "c31205c3-71b4-11ef-bb52-6361ac5a97ee"
COMP_PROD_DATE_START = "c31205ce-71b4-11ef-bb52-6361ac5a97ee"
COMP_PROD_DATE_END = "c31205ca-71b4-11ef-bb52-6361ac5a97ee"
COMP_PROD_TIME_TYPE = "c31205c0-71b4-11ef-bb52-6361ac5a97ee"

COMP_PERIOD_NG = "e67686af-edf2-11ef-9a8f-89acc4447d22"
COMP_PERIOD_ABSOLUTE = "e67686b6-edf2-11ef-9a8f-89acc4447d22"
COMP_PERIOD_PRODUCTION = "e67686af-edf2-11ef-9a8f-89acc4447d22"

COMP_LOCATION_DOC_NG = "fa5cc926-e889-11ef-9bfc-0debd0685137"
COMP_LOCATION_DOC_NODE = "fa5cc926-e889-11ef-9bfc-0debd0685137"
COMP_LOCATION_APPELLATION = "f0dcdbf0-e88b-11ef-9bfc-0debd0685137"

# --- Concept defaults ---
CONCEPT_FRENCH = "a1d82c77-ebd6-4215-ab85-2c0b6a68a0e8"
CONCEPT_PREFERRED_TERMS = "5f400d39-3b6b-4b8a-939b-4e49787c7444"
CONCEPT_PERSISTENT_ID = "5b292232-52ac-4e71-ba6c-fe4dd6ff02fa"
CONCEPT_RECORD_ID = "e10752d3-d8fa-47cb-92f9-dd7277dfc97a"
CONCEPT_SOURCE_BIBLISSIMA = "39124989-dfb1-4e2a-9d1a-4bff0827ed71"
CONCEPT_SOURCE_MANDRAGORE = "3b78627a-c751-43df-b427-73e1dd11ec38"
CONCEPT_DESCRIPTION = "9a51d30b-48e8-4f94-9344-cd2bb1d4b33a"
CONCEPT_MANUSCRIT = "56c61151-3bc5-45b4-957e-3cccde26abe7"
CONCEPT_DECOR = "c19f3196-d1e9-4f08-9917-4d627e61e153"
CONCEPT_SHELF_MARKS = "2cbf15b4-aa04-4b5b-bf4a-2594bbeb72ca"
CONCEPT_MEDIEVAL = "f8101404-1570-35cf-ac70-1a18a84072ca"

# Century mapping: "13e siècle" → concept UUID
CENTURY_MAPPING = {
    "1": "82f4c4ef-1ca8-3721-8ee0-fc9bfdd4d2e7",
    "2": "8130e10c-175c-36bd-b16f-a3f19e3bab2c",
    "3": "aa2f7cf8-216a-3b3d-8b93-d85f24d12bc5",
    "4": "a8e9c250-2c00-3eba-a26d-652621ba4e1f",
    "5": "f208e4bb-e67a-3ca4-87ac-18d6974d85e2",
    "6": "cb813afa-b776-3597-a474-e06788bc0a83",
    "7": "6aceda91-36e6-3471-9a17-155cbdb7e84d",
    "8": "9618da23-9cd1-3f39-918b-b4f72b1ea10c",
    "9": "e7b0401b-69f6-3790-b3aa-b19b96513987",
    "10": "a9856744-3b8a-397e-a6da-82f35ced1423",
    "11": "e869b370-57bf-37a6-9f28-16f2f51292ec",
    "12": "97d12923-2a27-326f-92ed-0ddb0d83bafc",
    "13": "58b33dfa-7337-368b-8272-ed5b7953493a",
    "14": "831aeae8-3c26-3c3c-a2e6-d605a5f2b09d",
    "15": "04db53cd-8a0a-3e1a-90e3-2d2ac158c29d",
    "16": "5252cc19-b82f-33bb-93c2-05d5cac9652c",
    "17": "47e91572-82f6-35a3-882c-d20a2631b9db",
    "18": "f28e962b-5441-32a9-aef3-670fb896e4f3",
    "19": "3ff0aafb-1afb-362c-b228-7a5d704ae924",
    "20": "95e228f8-2434-3e84-9092-289b3c2fac87",
    "21": "1b45307f-a121-3aef-8fe2-9d7a3535be89",
}

RELATIONSHIP_CONCEPT = "ac41d9be-79db-4256-b368-2f4559cfbe55"

_ARK_RE = re.compile(r'ark:/43093/(\w+)')
_CENTURY_RE = re.compile(r'(\d+)e\s+si[eè]cle', re.IGNORECASE)
_HTML_TAG_RE = re.compile(r'<[^>]+>')


def _strip_html(text):
    """Remove HTML tags and unescape entities."""
    if not text:
        return text
    if isinstance(text, list):
        return [_strip_html(t) for t in text]
    return unescape(_HTML_TAG_RE.sub("", str(text)))


def _extract_ark(html_value):
    """Extract ARK identifier from an HTML link."""
    if not html_value:
        return None
    text = html_value if isinstance(html_value, str) else str(html_value)
    match = _ARK_RE.search(text)
    return f"ark:/43093/{match.group(1)}" if match else None


def _extract_href(html_value):
    """Extract the first href URL from an HTML link."""
    if not html_value:
        return None
    text = html_value if isinstance(html_value, str) else str(html_value)
    match = re.search(r'href="([^"]+)"', text)
    return match.group(1) if match else None


def _parse_century(date_str):
    """Parse a century string like '13e siècle' and return the concept UUID."""
    if not date_str:
        return None
    match = _CENTURY_RE.search(str(date_str))
    if match:
        century_num = match.group(1)
        return CENTURY_MAPPING.get(century_num)
    return None


def _get_wikibase_entity(qid, session=None):
    """Fetch a Wikibase entity and extract relevant properties."""
    s = session or requests
    try:
        resp = s.get(
            BIBLISSIMA_WIKIBASE,
            params={
                "action": "wbgetentities",
                "ids": qid,
                "format": "json",
                "languages": "fr|en",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        entity = data.get("entities", {}).get(qid, {})
    except Exception:
        logger.warning("Failed to fetch Wikibase entity %s", qid)
        return None

    claims = entity.get("claims", {})

    def _get_string(prop):
        claim_list = claims.get(prop, [])
        if claim_list:
            val = claim_list[0].get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(val, str):
                return val
        return None

    def _get_entity_id(prop):
        claim_list = claims.get(prop, [])
        if claim_list:
            val = claim_list[0].get("mainsnak", {}).get("datavalue", {}).get("value", {})
            if isinstance(val, dict):
                return val.get("id")
        return None

    labels = entity.get("labels", {})
    label = (
        labels.get("fr", {}).get("value")
        or labels.get("en", {}).get("value")
        or ""
    )

    return {
        "qid": qid,
        "label": label,
        "portalHash": _get_string(P129),
        "manifestUrl": _get_string(P196),
        "digitizationUrl": _get_string(P197),
        "shelfmark": _get_string(P195),
        "collection": _get_entity_id(P194),
        "author": _get_entity_id(P354),
        "mandragoreId": _get_string(P270),
    }


def _parse_iiif_canvases(manifest_json):
    """Parse IIIF v2 manifest and extract canvas data."""
    results = []
    sequences = manifest_json.get("sequences", [])
    if not sequences:
        return results

    canvases = sequences[0].get("canvases", [])
    for canvas in canvases:
        metadata = {}
        for m in canvas.get("metadata", []):
            metadata[m.get("label", "")] = m.get("value")

        # Extract thumbnail
        thumbnail = None
        thumb_obj = canvas.get("thumbnail")
        if isinstance(thumb_obj, dict):
            thumbnail = thumb_obj.get("@id")
        elif isinstance(thumb_obj, str):
            thumbnail = thumb_obj

        # Extract image URL
        image_url = None
        images = canvas.get("images", [])
        if images:
            resource = images[0].get("resource", {})
            service = resource.get("service", {})
            image_url = service.get("@id") if isinstance(service, dict) else None

        # Extract ARK identifiers
        portal_link = metadata.get("Sur le portail Biblissima", "")
        item_ark = _extract_ark(portal_link)
        portal_url = _extract_href(portal_link)

        manuscript_link = metadata.get("Manuscrit", "")
        manuscript_ark = _extract_ark(manuscript_link)
        manuscript_label = _strip_html(manuscript_link)
        if isinstance(manuscript_label, str):
            manuscript_label = manuscript_label.strip()

        # Extract descriptors
        descriptors_raw = metadata.get("Descripteurs", [])
        if isinstance(descriptors_raw, str):
            descriptors_raw = [descriptors_raw]
        descriptors = [_strip_html(d) for d in descriptors_raw]

        # Location
        location_raw = metadata.get("Lieu de fabrication", "")
        if isinstance(location_raw, list):
            location = ", ".join(_strip_html(location_raw))
        else:
            location = _strip_html(location_raw)

        results.append(
            {
                "canvasId": canvas.get("@id", ""),
                "arkId": item_ark,
                "label": _strip_html(canvas.get("label", "")),
                "thumbnail": thumbnail,
                "imageUrl": image_url,
                "manuscript": manuscript_label,
                "manuscriptArk": manuscript_ark,
                "folio": metadata.get("Feuillet / page", ""),
                "legend": _strip_html(metadata.get("Légende", "")),
                "date": metadata.get("Date", ""),
                "location": location,
                "descriptors": descriptors,
                "portalUrl": portal_url,
            }
        )
    return results


class BiblissimaSuggestView(View):
    """Proxy for Biblissima Wikibase entity search (autocomplete).

    Combines prefix match (wbsearchentities) and full-text search
    (CirrusSearch) for flexible matching regardless of word order.
    """

    @method_decorator(cache_page(300))
    def get(self, request):
        query = request.GET.get("q", "").strip()
        if len(query) < 2:
            return JsonResponse({"results": []})

        lang = request.GET.get("lang", "fr")
        limit = int(request.GET.get("limit", 10))
        seen_ids = set()
        results = []

        session = requests.Session()

        # 1. Prefix match (fast, good for exact starts)
        try:
            resp = session.get(
                BIBLISSIMA_WIKIBASE,
                params={
                    "action": "wbsearchentities",
                    "search": query,
                    "language": lang,
                    "format": "json",
                    "limit": limit,
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            for item in resp.json().get("search", []):
                if item["id"] not in seen_ids:
                    seen_ids.add(item["id"])
                    results.append(
                        {
                            "id": item["id"],
                            "label": item.get("label", ""),
                            "description": item.get("description", ""),
                        }
                    )
        except Exception:
            logger.warning("wbsearchentities failed for query=%s", query)

        # 2. Full-text search (flexible word order, partial matches)
        if len(results) < limit:
            try:
                resp = session.get(
                    BIBLISSIMA_WIKIBASE,
                    params={
                        "action": "query",
                        "list": "search",
                        "srsearch": query,
                        "srnamespace": 120,  # Item namespace
                        "format": "json",
                        "srlimit": limit,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                search_results = resp.json().get("query", {}).get("search", [])
                qids_to_fetch = [
                    r["title"].replace("Item:", "")
                    for r in search_results
                    if r["title"].replace("Item:", "") not in seen_ids
                ]

                # Batch fetch labels for full-text results
                if qids_to_fetch:
                    resp = session.get(
                        BIBLISSIMA_WIKIBASE,
                        params={
                            "action": "wbgetentities",
                            "ids": "|".join(qids_to_fetch[: limit - len(results)]),
                            "format": "json",
                            "languages": f"{lang}|en",
                            "props": "labels|descriptions",
                        },
                        timeout=REQUEST_TIMEOUT,
                    )
                    resp.raise_for_status()
                    entities = resp.json().get("entities", {})
                    for qid in qids_to_fetch:
                        if len(results) >= limit:
                            break
                        entity = entities.get(qid, {})
                        labels = entity.get("labels", {})
                        label = (
                            labels.get(lang, {}).get("value")
                            or labels.get("en", {}).get("value")
                            or ""
                        )
                        descs = entity.get("descriptions", {})
                        desc = (
                            descs.get(lang, {}).get("value")
                            or descs.get("en", {}).get("value")
                            or ""
                        )
                        if label:
                            seen_ids.add(qid)
                            results.append(
                                {"id": qid, "label": label, "description": desc}
                            )
            except Exception:
                logger.warning("CirrusSearch failed for query=%s", query)

        session.close()
        return JsonResponse({"results": results})


class BiblissimaEntityView(View):
    """Proxy for fetching a single Wikibase entity with extracted properties."""

    @method_decorator(cache_page(600))
    def get(self, request, qid):
        entity = _get_wikibase_entity(qid)
        if entity is None:
            return JsonResponse({"error": "Entity not found"}, status=404)

        # If author is a QID, resolve its label
        if entity.get("author"):
            author_entity = _get_wikibase_entity(entity["author"])
            if author_entity:
                entity["authorLabel"] = author_entity["label"]
                entity["authorQid"] = entity["author"]

        # If collection is a QID, resolve its label
        if entity.get("collection"):
            coll_entity = _get_wikibase_entity(entity["collection"])
            if coll_entity:
                entity["collectionLabel"] = coll_entity["label"]
                entity["collectionQid"] = entity["collection"]

        return JsonResponse(entity)


class BiblissimaSearchView(View):
    """Search Biblissima via IIIF manifest by iconographic descriptors."""

    def get(self, request):
        descriptors = request.GET.get("descriptors", "").strip()
        if not descriptors:
            return JsonResponse({"error": "descriptors parameter required"}, status=400)

        date_filter = request.GET.get("date", "")
        page = max(1, int(request.GET.get("page", 1)))
        page_size = min(50, max(1, int(request.GET.get("page_size", 20))))

        # Build descriptor query for Biblissima
        descriptor_parts = ",".join(f"AND|{h.strip()}" for h in descriptors.split(",") if h.strip())
        params = {"descriptors": descriptor_parts}
        if date_filter:
            params["date"] = f"OR|{date_filter}"

        try:
            resp = requests.get(
                BIBLISSIMA_IIIF_MANIFEST,
                params=params,
                timeout=REQUEST_TIMEOUT * 2,
            )
            resp.raise_for_status()
            manifest_json = resp.json()
        except Exception:
            logger.exception("Biblissima IIIF search failed")
            return JsonResponse({"error": "Biblissima search failed"}, status=502)

        all_canvases = _parse_iiif_canvases(manifest_json)
        total = len(all_canvases)

        # Paginate
        start = (page - 1) * page_size
        end = start + page_size
        page_canvases = all_canvases[start:end]

        # Enrich with Wikibase data per unique manuscript (cached within request)
        manuscript_cache = {}
        session = requests.Session()

        for canvas in page_canvases:
            ms_ark = canvas.get("manuscriptArk")
            if not ms_ark or ms_ark in manuscript_cache:
                if ms_ark and ms_ark in manuscript_cache:
                    ms_data = manuscript_cache[ms_ark]
                    canvas["manifestUrl"] = ms_data.get("manifestUrl")
                    canvas["authorLabel"] = ms_data.get("authorLabel")
                    canvas["authorQid"] = ms_data.get("authorQid")
                    canvas["biblissimaQid"] = ms_data.get("qid")
                    canvas["shelfmark"] = ms_data.get("shelfmark")
                    canvas["mandragoreId"] = ms_data.get("mandragoreId")
                continue

            # Search Wikibase for this manuscript by its portal hash
            ark_hash = ms_ark.replace("ark:/43093/", "")
            try:
                search_resp = session.get(
                    BIBLISSIMA_WIKIBASE,
                    params={
                        "action": "wbsearchentities",
                        "search": canvas.get("manuscript", ""),
                        "language": "fr",
                        "format": "json",
                        "limit": 5,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                search_resp.raise_for_status()
                search_data = search_resp.json()

                ms_data = {}
                for item in search_data.get("search", []):
                    entity = _get_wikibase_entity(item["id"], session=session)
                    if entity and entity.get("portalHash") == ark_hash:
                        ms_data = entity
                        # Resolve author label
                        if ms_data.get("author"):
                            author = _get_wikibase_entity(ms_data["author"], session=session)
                            if author:
                                ms_data["authorLabel"] = author["label"]
                                ms_data["authorQid"] = ms_data["author"]
                        break
                manuscript_cache[ms_ark] = ms_data

                canvas["manifestUrl"] = ms_data.get("manifestUrl")
                canvas["authorLabel"] = ms_data.get("authorLabel")
                canvas["authorQid"] = ms_data.get("authorQid")
                canvas["biblissimaQid"] = ms_data.get("qid")
                canvas["shelfmark"] = ms_data.get("shelfmark")
                canvas["mandragoreId"] = ms_data.get("mandragoreId")
            except Exception:
                logger.warning("Failed to enrich manuscript %s", ms_ark)
                manuscript_cache[ms_ark] = {}

        session.close()

        return JsonResponse(
            {
                "total": total,
                "page": page,
                "pageSize": page_size,
                "totalPages": (total + page_size - 1) // page_size,
                "results": page_canvases,
            }
        )


class BiblissimaCheckDuplicatesView(View):
    """Check if resources with given identifiers already exist in Arches."""

    def get(self, request):
        identifiers = request.GET.get("identifiers", "").split(",")
        graph_id = request.GET.get("graphId", DOCUMENT_GRAPH_ID)
        identifiers = [i.strip() for i in identifiers if i.strip()]

        if not identifiers:
            return JsonResponse({"results": {}})

        results = {}
        for identifier in identifiers:
            # Search for tiles with matching identifier value
            matching_tiles = Tile.objects.filter(
                nodegroup_id__in=[DOC_IDENTIFIER_NG, COMP_IDENTIFIER_NG],
                resourceinstance__graph_id=graph_id,
            )
            found = None
            for tile in matching_tiles:
                val_node = (
                    DOC_IDENTIFIER_VALUE
                    if str(tile.nodegroup_id) == DOC_IDENTIFIER_NG
                    else COMP_IDENTIFIER_VALUE
                )
                tile_value = tile.data.get(val_node)
                if tile_value and str(tile_value).strip() == identifier:
                    found = str(tile.resourceinstance_id)
                    break
            results[identifier] = found

        return JsonResponse({"results": results})


class BiblissimaCreateResourceView(View):
    """Create a Document or Component resource from Biblissima data."""

    def post(self, request):
        import json

        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON body"}, status=400)

        resource_type = body.get("resourceType", "Document")
        transaction_id = body.get("transactionId")
        bbma_data = body.get("biblissimaData", {})
        dependencies = body.get("dependencies", {})
        concept_mappings = body.get("conceptMappings", {})

        if resource_type == "Document":
            graph_id = DOCUMENT_GRAPH_ID
        elif resource_type == "Component":
            graph_id = COMPONENT_GRAPH_ID
        else:
            return JsonResponse({"error": f"Unknown resourceType: {resource_type}"}, status=400)

        try:
            resource_id, created_deps = self._create_resource(
                graph_id=graph_id,
                resource_type=resource_type,
                transaction_id=transaction_id,
                bbma_data=bbma_data,
                dependencies=dependencies,
                concept_mappings=concept_mappings,
                user=request.user,
            )
        except Exception:
            logger.exception("Failed to create resource from Biblissima data")
            return JsonResponse({"error": "Resource creation failed"}, status=500)

        return JsonResponse(
            {
                "resourceId": str(resource_id),
                "createdDependencies": created_deps,
            }
        )

    def _create_resource(
        self, graph_id, resource_type, transaction_id, bbma_data, dependencies, concept_mappings, user
    ):
        """Create a resource with all its tiles from Biblissima data."""
        created_deps = {"places": {}, "persons": {}, "groups": {}}
        resource_instance = ResourceInstance(graph_id=graph_id)
        resource_instance.save()
        resource_id = resource_instance.resourceinstanceid

        if resource_type == "Document":
            self._create_document_tiles(
                resource_id, transaction_id, bbma_data, dependencies, concept_mappings, created_deps
            )
        else:
            self._create_component_tiles(
                resource_id, transaction_id, bbma_data, dependencies, concept_mappings, created_deps
            )

        # Link to project if specified
        project_id = dependencies.get("project")
        if project_id:
            self._link_to_project(resource_id, project_id, transaction_id)

        return resource_id, created_deps

    def _create_tile(self, nodegroup_id, resource_id, data, transaction_id=None):
        """Create a single tile."""
        tile = Tile(
            tileid=uuid.uuid4(),
            nodegroup_id=nodegroup_id,
            resourceinstance_id=resource_id,
            data=data,
            sortorder=0,
        )
        if transaction_id:
            tile.transaction_id = transaction_id
        tile.save()
        return tile

    def _create_document_tiles(self, resource_id, transaction_id, bbma_data, deps, concepts, created_deps):
        """Create all tiles for a Document resource."""
        # Name
        label = bbma_data.get("label", "Untitled")
        self._create_tile(
            DOC_NAME_NG,
            resource_id,
            {
                DOC_NAME_LABEL: label,
                DOC_NAME_LANGUAGE: [CONCEPT_FRENCH],
                DOC_NAME_TYPE: [CONCEPT_PREFERRED_TERMS],
            },
            transaction_id,
        )

        # Second name tile for shelfmark if available
        shelfmark = bbma_data.get("shelfmark")
        if shelfmark:
            from arches.app.models.models import Value as ConceptValue
            self._create_tile(
                DOC_NAME_NG,
                resource_id,
                {
                    DOC_NAME_LABEL: shelfmark,
                    DOC_NAME_LANGUAGE: [CONCEPT_FRENCH],
                    DOC_NAME_TYPE: ["7cca3482-44b5-42ea-a1d7-120cd732b350"],  # alternate titles
                },
                transaction_id,
            )

        # Type
        doc_type = concepts.get("type", CONCEPT_MANUSCRIT)
        self._create_tile(
            DOC_TYPE_NG,
            resource_id,
            {DOC_TYPE_NODE: doc_type},
            transaction_id,
        )

        # Identifiers
        ark_id = bbma_data.get("arkId")
        if ark_id:
            self._create_tile(
                DOC_IDENTIFIER_NG,
                resource_id,
                {
                    DOC_IDENTIFIER_VALUE: ark_id,
                    DOC_IDENTIFIER_TYPE: [CONCEPT_PERSISTENT_ID],
                    DOC_IDENTIFIER_SOURCE: [CONCEPT_SOURCE_BIBLISSIMA],
                },
                transaction_id,
            )

        qid = bbma_data.get("biblissimaQid")
        if qid:
            self._create_tile(
                DOC_IDENTIFIER_NG,
                resource_id,
                {
                    DOC_IDENTIFIER_VALUE: qid,
                    DOC_IDENTIFIER_TYPE: [CONCEPT_RECORD_ID],
                    DOC_IDENTIFIER_SOURCE: [CONCEPT_SOURCE_BIBLISSIMA],
                },
                transaction_id,
            )

        mandragore_id = bbma_data.get("mandragoreId")
        if mandragore_id:
            self._create_tile(
                DOC_IDENTIFIER_NG,
                resource_id,
                {
                    DOC_IDENTIFIER_VALUE: mandragore_id,
                    DOC_IDENTIFIER_TYPE: [CONCEPT_RECORD_ID],
                    DOC_IDENTIFIER_SOURCE: [CONCEPT_SOURCE_MANDRAGORE],
                },
                transaction_id,
            )

        # Statement (description)
        legend = bbma_data.get("legend") or bbma_data.get("label", "")
        portal_url = bbma_data.get("portalUrl", "")
        if legend:
            self._create_tile(
                DOC_STATEMENT_NG,
                resource_id,
                {
                    DOC_STATEMENT_CONTENT: legend,
                    DOC_STATEMENT_TYPE: [CONCEPT_DESCRIPTION],
                    DOC_STATEMENT_LANGUAGE: [CONCEPT_FRENCH],
                    DOC_STATEMENT_SOURCE: portal_url or None,
                },
                transaction_id,
            )

        # Facsimiles (IIIF manifest)
        manifest_url = bbma_data.get("manifestUrl")
        if manifest_url:
            self._create_tile(
                DOC_FACSIMILES_NG,
                resource_id,
                {DOC_FACSIMILES_NODE: manifest_url},
                transaction_id,
            )

        # Period
        date_str = bbma_data.get("date", "")
        century_concept = _parse_century(date_str)
        if century_concept:
            self._create_tile(
                DOC_PERIOD_NG,
                resource_id,
                {
                    DOC_PERIOD_ABSOLUTE: [century_concept],
                    DOC_PERIOD_PRODUCTION: [CONCEPT_MEDIEVAL],
                },
                transaction_id,
            )

        # Production
        prod_data = {DOC_PROD_TIME_TYPE: False}

        # Date
        if date_str:
            prod_data[DOC_PROD_DATE_START] = self._century_to_date(date_str)

        # Place
        place_id = deps.get("productionPlace")
        if place_id:
            prod_data[DOC_PROD_PLACE] = self._resource_instance_list(place_id)

        # Actors
        actor_ids = deps.get("productionActors", [])
        if actor_ids:
            prod_data[DOC_PROD_ACTORS] = self._resource_instance_list(actor_ids)

        if any(k != DOC_PROD_TIME_TYPE for k in prod_data):
            self._create_tile(
                DOC_PRODUCTION_NG,
                resource_id,
                prod_data,
                transaction_id,
            )

        # Current location
        location_id = deps.get("currentLocation")
        if location_id:
            self._create_tile(
                DOC_LOCATION_NG,
                resource_id,
                {
                    DOC_LOCATION_NODE: self._resource_instance_ref(location_id),
                    DOC_LOCATION_LITERAL: None,
                },
                transaction_id,
            )

        # Current owner
        owner_ids = deps.get("currentOwner", [])
        if owner_ids:
            self._create_tile(
                DOC_OWNER_NG,
                resource_id,
                {DOC_OWNER_NODE: self._resource_instance_list(owner_ids)},
                transaction_id,
            )

        # Part of
        parent_doc_id = deps.get("partOf")
        if parent_doc_id:
            self._create_tile(
                DOC_PART_OF_NG,
                resource_id,
                {DOC_PART_OF_NODE: self._resource_instance_list(parent_doc_id)},
                transaction_id,
            )

    def _create_component_tiles(self, resource_id, transaction_id, bbma_data, deps, concepts, created_deps):
        """Create all tiles for a Component resource."""
        # Name
        label = bbma_data.get("legend") or bbma_data.get("label", "Untitled")
        self._create_tile(
            COMP_NAME_NG,
            resource_id,
            {
                COMP_NAME_LABEL: label,
                COMP_NAME_LANGUAGE: [CONCEPT_FRENCH],
                COMP_NAME_TYPE: [CONCEPT_PREFERRED_TERMS],
            },
            transaction_id,
        )

        # Type
        comp_type = concepts.get("type", CONCEPT_DECOR)
        self._create_tile(
            COMP_TYPE_NG,
            resource_id,
            {COMP_TYPE_NODE: [comp_type]},
            transaction_id,
        )

        # Parent Document (required)
        parent_doc_id = deps.get("parentDocument")
        if parent_doc_id:
            self._create_tile(
                COMP_PARENT_DOC_NG,
                resource_id,
                {
                    COMP_PARENT_DOC_NODE: self._resource_instance_ref(parent_doc_id),
                },
                transaction_id,
            )

        # Identifiers
        ark_id = bbma_data.get("arkId")
        if ark_id:
            self._create_tile(
                COMP_IDENTIFIER_NG,
                resource_id,
                {
                    COMP_IDENTIFIER_VALUE: ark_id,
                    COMP_IDENTIFIER_TYPE: [CONCEPT_PERSISTENT_ID],
                    COMP_IDENTIFIER_SOURCE: [CONCEPT_SOURCE_BIBLISSIMA],
                },
                transaction_id,
            )

        # Statement
        legend = bbma_data.get("label", "")
        portal_url = bbma_data.get("portalUrl", "")
        if legend:
            self._create_tile(
                COMP_STATEMENT_NG,
                resource_id,
                {
                    COMP_STATEMENT_CONTENT: legend,
                    COMP_STATEMENT_TYPE: [CONCEPT_DESCRIPTION],
                    COMP_STATEMENT_LANGUAGE: [CONCEPT_FRENCH],
                    COMP_STATEMENT_SOURCE: portal_url or None,
                },
                transaction_id,
            )

        # Iconographic representation
        thumbnail = bbma_data.get("thumbnail") or bbma_data.get("imageUrl")
        if thumbnail:
            self._create_tile(
                COMP_ICONOGRAPHIC_NG,
                resource_id,
                {COMP_ICONOGRAPHIC_NODE: thumbnail},
                transaction_id,
            )

        # Context (folio)
        folio = bbma_data.get("folio")
        if folio:
            self._create_tile(
                COMP_CONTEXT_NG,
                resource_id,
                {COMP_CONTEXT_NODE: folio},
                transaction_id,
            )

        # Period
        date_str = bbma_data.get("date", "")
        century_concept = _parse_century(date_str)
        if century_concept:
            self._create_tile(
                COMP_PERIOD_NG,
                resource_id,
                {
                    COMP_PERIOD_ABSOLUTE: [century_concept],
                    COMP_PERIOD_PRODUCTION: [CONCEPT_MEDIEVAL],
                },
                transaction_id,
            )

        # Production
        prod_data = {COMP_PROD_TIME_TYPE: False}

        if date_str:
            prod_data[COMP_PROD_DATE_START] = self._century_to_date(date_str)

        place_id = deps.get("productionPlace")
        if place_id:
            prod_data[COMP_PROD_PLACE] = self._resource_instance_list(place_id)

        actor_ids = deps.get("productionActors", [])
        if actor_ids:
            prod_data[COMP_PROD_ACTORS] = self._resource_instance_list(actor_ids)

        if any(k != COMP_PROD_TIME_TYPE for k in prod_data):
            self._create_tile(
                COMP_PRODUCTION_NG,
                resource_id,
                prod_data,
                transaction_id,
            )

        # Location in Document (annotation)
        canvas_url = bbma_data.get("canvasId") or bbma_data.get("imageUrl")
        manifest_url = bbma_data.get("manifestUrl")
        if canvas_url and manifest_url:
            annotation_data = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "id": str(uuid.uuid4()),
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [0, 0],
                        },
                        "properties": {
                            "canvas": canvas_url,
                            "manifest": manifest_url,
                            "nodeId": COMP_LOCATION_DOC_NODE,
                            "color": "#3388ff",
                            "radius": 10,
                            "weight": 3,
                            "opacity": 1,
                            "fillColor": "#3388ff",
                            "fillOpacity": 0.2,
                        },
                    }
                ],
            }
            appellation_data = {"en": {"value": folio or "", "direction": "ltr"}}
            self._create_tile(
                COMP_LOCATION_DOC_NG,
                resource_id,
                {
                    COMP_LOCATION_DOC_NODE: annotation_data,
                    COMP_LOCATION_APPELLATION: appellation_data,
                },
                transaction_id,
            )

    def _link_to_project(self, resource_id, project_id, transaction_id):
        """Add the created resource to the project's Studied Objects."""
        # Find existing tile or create new one
        existing = Tile.objects.filter(
            nodegroup_id=PROJECT_STUDIED_OBJECTS_NG,
            resourceinstance_id=project_id,
        ).first()

        new_ref = {
            "resourceId": str(resource_id),
            "ontologyProperty": "",
            "inverseOntologyProperty": "",
            "resourceXresourceId": "",
        }

        if existing:
            current_data = existing.data.get(PROJECT_STUDIED_OBJECTS_NODE, []) or []
            current_data.append(new_ref)
            existing.data[PROJECT_STUDIED_OBJECTS_NODE] = current_data
            existing.save()
        else:
            self._create_tile(
                PROJECT_STUDIED_OBJECTS_NG,
                project_id,
                {PROJECT_STUDIED_OBJECTS_NODE: [new_ref]},
                transaction_id,
            )

    def _resource_instance_ref(self, resource_id):
        """Build a resource-instance reference for a single resource."""
        if isinstance(resource_id, list):
            resource_id = resource_id[0] if resource_id else None
        if not resource_id:
            return None
        return [
            {
                "resourceId": str(resource_id),
                "ontologyProperty": "",
                "inverseOntologyProperty": "",
                "resourceXresourceId": "",
            }
        ]

    def _resource_instance_list(self, resource_ids):
        """Build a resource-instance-list reference."""
        if isinstance(resource_ids, str):
            resource_ids = [resource_ids]
        return [
            {
                "resourceId": str(rid),
                "ontologyProperty": "",
                "inverseOntologyProperty": "",
                "resourceXresourceId": "",
            }
            for rid in resource_ids
            if rid
        ]

    def _century_to_date(self, date_str):
        """Convert a century string to an approximate start date."""
        match = _CENTURY_RE.search(str(date_str))
        if match:
            century = int(match.group(1))
            year = (century - 1) * 100 + 1
            return f"{year:04d}-01-01"
        return None
