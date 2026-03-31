import logging
import re
import uuid
from html import unescape

import requests
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import cache_page

from arches.app.models.models import ResourceInstance
from arches.app.models.models import Value  # used in _concept_valueid
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
P201 = "P201"  # localisation (place)
P169 = "P169"  # partie de (parent institution)
P123 = "P123"  # identifiant Geonames

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


def _resolve_collection(collection_qid, session=None):
    """Resolve a Biblissima collection entity into owner + location data.

    Follows the chain: collection → P201 (localisation) → place with Geonames ID
                        collection → P169 (partie de) → parent institution
    Returns dict with ownerLabel, ownerQid, locationLabel, locationQid, geonamesId.
    """
    if not collection_qid:
        return {}

    coll = _get_wikibase_entity(collection_qid, session=session)
    if not coll:
        return {}

    result = {
        "ownerLabel": coll.get("label", ""),
        "ownerQid": collection_qid,
    }

    s = session or requests
    coll_claims = {}
    try:
        resp = s.get(
            BIBLISSIMA_WIKIBASE,
            params={
                "action": "wbgetentities",
                "ids": collection_qid,
                "format": "json",
                "languages": "fr|en",
                "props": "claims",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        entity = resp.json().get("entities", {}).get(collection_qid, {})
        coll_claims = entity.get("claims", {})
    except Exception:
        logger.warning("Failed to fetch collection claims for %s", collection_qid)
        return result

    # P201 = localisation (place)
    loc_claims = coll_claims.get(P201, [])
    if loc_claims:
        loc_qid = loc_claims[0].get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
        if loc_qid:
            loc_entity = _get_wikibase_entity(loc_qid, session=session)
            if loc_entity:
                result["locationLabel"] = loc_entity.get("label", "")
                result["locationQid"] = loc_qid

                # Get Geonames ID from the place entity
                try:
                    loc_resp = s.get(
                        BIBLISSIMA_WIKIBASE,
                        params={
                            "action": "wbgetentities",
                            "ids": loc_qid,
                            "format": "json",
                            "props": "claims",
                        },
                        timeout=REQUEST_TIMEOUT,
                    )
                    loc_resp.raise_for_status()
                    loc_data = loc_resp.json().get("entities", {}).get(loc_qid, {})
                    geo_claims = loc_data.get("claims", {}).get(P123, [])
                    if geo_claims:
                        geo_val = geo_claims[0].get("mainsnak", {}).get("datavalue", {}).get("value")
                        if geo_val:
                            result["geonamesId"] = str(geo_val)
                except Exception:
                    pass

    # P169 = partie de (parent institution) — for the top-level owner
    parent_claims = coll_claims.get(P169, [])
    if parent_claims:
        parent_qid = parent_claims[0].get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
        if parent_qid:
            parent_entity = _get_wikibase_entity(parent_qid, session=session)
            if parent_entity:
                result["parentInstitutionLabel"] = parent_entity.get("label", "")
                result["parentInstitutionQid"] = parent_qid

    return result


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
                # Fields expected by the frontend template (populated during enrichment)
                "shelfmark": "",
                "collectionLabel": "",
                "manifestUrl": "",
                "authorLabel": "",
                "authorQid": "",
                "biblissimaQid": "",
                "mandragoreId": "",
                "digitizationUrl": "",
                "locationLabel": "",
                "locationQid": "",
                "geonamesId": "",
                "parentInstitutionLabel": "",
                "parentInstitutionQid": "",
            }
        )
    return results


class BiblissimaSuggestView(View):
    """Proxy for Biblissima Wikibase entity search (autocomplete).

    Combines prefix match (wbsearchentities) and full-text search
    (CirrusSearch) for flexible matching regardless of word order.
    """

    # Wikibase type QIDs for filtering
    TYPE_FILTERS = {
        "manuscript": "Q32810",
        "descriptor": "Q304387",
    }

    @method_decorator(cache_page(300))
    def get(self, request):
        query = request.GET.get("q", "").strip()
        if len(query) < 2:
            return JsonResponse({"results": []})

        lang = request.GET.get("lang", "fr")
        limit = int(request.GET.get("limit", 10))
        type_filter = request.GET.get("type", "")  # "manuscript" or "descriptor"
        type_qid = self.TYPE_FILTERS.get(type_filter, "")
        seen_ids = set()
        results = []

        session = requests.Session()

        # 1. Prefix match (fast, good for exact starts)
        # wbsearchentities doesn't support type filtering, so we fetch more
        # and filter by checking P2 claims afterwards
        try:
            fetch_limit = limit * 3 if type_qid else limit
            resp = session.get(
                BIBLISSIMA_WIKIBASE,
                params={
                    "action": "wbsearchentities",
                    "search": query,
                    "language": lang,
                    "format": "json",
                    "limit": fetch_limit,
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            prefix_items = resp.json().get("search", [])

            if type_qid and prefix_items:
                # Batch fetch P2 claims to filter by type
                batch_ids = [item["id"] for item in prefix_items]
                type_resp = session.get(
                    BIBLISSIMA_WIKIBASE,
                    params={
                        "action": "wbgetentities",
                        "ids": "|".join(batch_ids),
                        "format": "json",
                        "props": "claims",
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                type_resp.raise_for_status()
                entities = type_resp.json().get("entities", {})
                valid_ids = set()
                for qid, entity in entities.items():
                    for claim in entity.get("claims", {}).get(P2, []):
                        val = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
                        if isinstance(val, dict) and val.get("id") == type_qid:
                            valid_ids.add(qid)
                            break

                for item in prefix_items:
                    if item["id"] in valid_ids and item["id"] not in seen_ids:
                        seen_ids.add(item["id"])
                        results.append({
                            "id": item["id"],
                            "label": item.get("label", ""),
                            "description": item.get("description", ""),
                        })
                        if len(results) >= limit:
                            break
            else:
                for item in prefix_items:
                    if item["id"] not in seen_ids:
                        seen_ids.add(item["id"])
                        results.append({
                            "id": item["id"],
                            "label": item.get("label", ""),
                            "description": item.get("description", ""),
                        })
        except Exception:
            logger.warning("wbsearchentities failed for query=%s", query)

        # 2. Full-text search (flexible word order, partial matches)
        # CirrusSearch supports haswbstatement for native type filtering
        if len(results) < limit:
            try:
                srsearch = query
                if type_qid:
                    srsearch = f"{query} haswbstatement:P2={type_qid}"

                resp = session.get(
                    BIBLISSIMA_WIKIBASE,
                    params={
                        "action": "query",
                        "list": "search",
                        "srsearch": srsearch,
                        "srnamespace": 120,
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

        # If collection is a QID, resolve full collection data (owner + location)
        if entity.get("collection"):
            coll_data = _resolve_collection(entity["collection"])
            entity["collectionLabel"] = coll_data.get("ownerLabel", "")
            entity["collectionQid"] = entity["collection"]
            entity["locationLabel"] = coll_data.get("locationLabel", "")
            entity["locationQid"] = coll_data.get("locationQid", "")
            entity["geonamesId"] = coll_data.get("geonamesId", "")
            entity["parentInstitutionLabel"] = coll_data.get("parentInstitutionLabel", "")
            entity["parentInstitutionQid"] = coll_data.get("parentInstitutionQid", "")

        return JsonResponse(entity)


class BiblissimaSearchView(View):
    """Search Biblissima via IIIF manifest by iconographic descriptors."""

    def get(self, request):
        descriptors = request.GET.get("descriptors", "").strip()
        if not descriptors:
            return JsonResponse({"error": "descriptors parameter required"}, status=400)

        date_filter = request.GET.get("date", "")

        # Build descriptor query for Biblissima
        hash_list = [h.strip() for h in descriptors.split(",") if h.strip()]

        # Ensure all hashes use "desc" prefix for IIIF API compatibility
        _KNOWN_PREFIXES = ("pdata", "mdata", "oedata", "cdata", "ldata", "ifdata")
        desc_hashes = []
        for h in hash_list:
            if h.startswith("desc"):
                desc_hashes.append(h)
            else:
                # Replace known prefix with desc, keep the base hash intact
                base = h
                for prefix in _KNOWN_PREFIXES:
                    if h.startswith(prefix):
                        base = h[len(prefix):]
                        break
                desc_hashes.append(f"desc{base}")

        headers = {"Accept": "application/ld+json, application/json"}

        try:
            if len(desc_hashes) == 1:
                # Single descriptor: use ARK-based URL
                url = f"{BIBLISSIMA_IIIF_MANIFEST}/ark:/43093/{desc_hashes[0]}"
                resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT * 2)
            else:
                # Multiple descriptors: use query param format (AND combination)
                descriptor_parts = ",".join(f"AND|{h}" for h in desc_hashes)
                params = {"descriptors": descriptor_parts}
                if date_filter:
                    params["date"] = f"OR|{date_filter}"
                resp = requests.get(BIBLISSIMA_IIIF_MANIFEST, params=params, headers=headers, timeout=REQUEST_TIMEOUT * 2)

            resp.raise_for_status()
            manifest_json = resp.json()
        except Exception:
            logger.exception("Biblissima IIIF search failed")
            return JsonResponse({"error": "Biblissima search failed"}, status=502)

        all_canvases = _parse_iiif_canvases(manifest_json)
        total = len(all_canvases)

        # Enrich with Wikibase data per unique manuscript (cached within request)
        manuscript_cache = {}
        session = requests.Session()

        for canvas in all_canvases:
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

        return JsonResponse({"total": total, "results": all_canvases})


class BiblissimaCheckDuplicatesView(View):
    """Find potential duplicate resources in Arches using flexible matching.

    For each item, runs multiple search strategies and returns ranked suggestions.
    The user decides whether a match is a true duplicate or not.
    """

    def post(self, request):
        import json

        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        items = body.get("items", [])
        graph_id = body.get("graphId", DOCUMENT_GRAPH_ID)

        if not items:
            return JsonResponse({"results": []})

        from arches.app.search.search_engine_factory import SearchEngineInstance

        se = SearchEngineInstance
        results = []

        for idx, item in enumerate(items):
            ark_id = item.get("arkId", "")
            label = item.get("label", "")
            shelfmark = item.get("shelfmark", "")
            qid = item.get("biblissimaQid", "")

            suggestions = []
            seen_ids = set()

            # Strategy 1: Search by identifiers in tiles
            # Build all possible search tokens from Biblissima data
            search_tokens = set()
            if ark_id:
                search_tokens.add(ark_id)
                # Hash without ark: prefix
                ark_hash = ark_id.replace("ark:/43093/", "")
                if ark_hash != ark_id:
                    search_tokens.add(ark_hash)
            if qid:
                search_tokens.add(qid)
                # Also match full URL form used in Arches identifiers
                search_tokens.add(f"https://data.biblissima.fr/entity/{qid}")

            portal_hash = item.get("portalHash", "")
            if portal_hash:
                search_tokens.add(portal_hash)
                search_tokens.add(f"ark:/43093/{portal_hash}")

            manifest_url = item.get("manifestUrl", "")
            if manifest_url:
                search_tokens.add(manifest_url)

            if search_tokens:
                id_ng = DOC_IDENTIFIER_NG if graph_id == DOCUMENT_GRAPH_ID else COMP_IDENTIFIER_NG
                id_node = DOC_IDENTIFIER_VALUE if graph_id == DOCUMENT_GRAPH_ID else COMP_IDENTIFIER_VALUE
                try:
                    matching_tiles = Tile.objects.filter(
                        nodegroup_id=id_ng,
                        resourceinstance__graph_id=graph_id,
                    )
                    for tile in matching_tiles:
                        raw_value = tile.data.get(id_node, "")
                        # Handle i18n dict format
                        if isinstance(raw_value, dict):
                            tile_value = ""
                            for lang in ("en", "fr", "de", "es", "it"):
                                v = raw_value.get(lang, {})
                                if isinstance(v, dict) and v.get("value"):
                                    tile_value = v["value"].strip()
                                    break
                        else:
                            tile_value = str(raw_value).strip() if raw_value else ""

                        if not tile_value:
                            continue

                        # Check if tile value matches any search token
                        # or if any search token is contained in the tile value
                        matched = False
                        for token in search_tokens:
                            if token == tile_value or token in tile_value or tile_value in token:
                                matched = True
                                break

                        if matched:
                            rid = str(tile.resourceinstance_id)
                            if rid not in seen_ids:
                                seen_ids.add(rid)
                                dn = self._get_resource_name(rid)
                                suggestions.append({
                                    "resourceId": rid,
                                    "displayname": dn,
                                    "matchType": "identifier",
                                    "matchValue": tile_value,
                                    "confidence": "high",
                                })
                except Exception:
                    logger.warning("Tile identifier search failed for item %d", idx)

            # Strategy 2: ES search by shelfmark (nested strings.string field)
            if shelfmark:
                self._es_string_search(
                    se, graph_id, shelfmark, "shelfmark", seen_ids, suggestions
                )

            # Strategy 3: ES search by label/displayname
            if label and len(suggestions) < 3:
                self._es_string_search(
                    se, graph_id, label, "displayname", seen_ids, suggestions
                )

            results.append({
                "index": idx,
                "key": ark_id or label,
                "suggestions": suggestions[:5],
            })

        return JsonResponse({"results": results})


    @staticmethod
    def _get_resource_name(resource_id):
        """Get the display name for a resource."""
        try:
            ri = ResourceInstance.objects.get(resourceinstanceid=resource_id)
            return str(ri.name) if ri.name else str(ri)
        except ResourceInstance.DoesNotExist:
            return ""

    @staticmethod
    def _extract_es_displayname(hit):
        """Extract display name from an ES hit."""
        dn = hit.get("_source", {}).get("displayname", [])
        if isinstance(dn, list) and dn:
            return dn[0].get("value", "") if isinstance(dn[0], dict) else str(dn[0])
        if isinstance(dn, str):
            return dn
        return ""

    def _es_string_search(self, se, graph_id, search_term, match_type, seen_ids, suggestions):
        """Search ES using nested strings.string field (analyzed text)."""
        try:
            query = {
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"graph_id": graph_id}},
                            {
                                "nested": {
                                    "path": "strings",
                                    "query": {
                                        "bool": {
                                            "should": [
                                                {
                                                    "match_phrase": {
                                                        "strings.string": {
                                                            "query": search_term,
                                                            "boost": 3,
                                                        }
                                                    }
                                                },
                                                {
                                                    "match": {
                                                        "strings.string": {
                                                            "query": search_term,
                                                            "operator": "and",
                                                        }
                                                    }
                                                },
                                            ],
                                            "minimum_should_match": 1,
                                        }
                                    },
                                }
                            },
                        ],
                    }
                },
                "_source": ["displayname"],
                "size": 3,
            }
            es_results = se.search(index="resources", body=query)
            for hit in es_results.get("hits", {}).get("hits", []):
                rid = hit["_id"]
                if rid not in seen_ids:
                    score = hit.get("_score", 0)
                    seen_ids.add(rid)
                    suggestions.append({
                        "resourceId": rid,
                        "displayname": self._extract_es_displayname(hit),
                        "matchType": match_type,
                        "matchValue": search_term,
                        "confidence": "high" if score > 8 else "medium" if score > 3 else "low",
                    })
        except Exception:
            logger.debug("ES %s search no results for: %s", match_type, search_term)


BIBLISSIMA_PORTAL = "https://portail.biblissima.fr/fr/ark:/43093"

# Map Biblissima illumination type/typologie/descriptor strings to Arches Type of Component valueids.
# Keys are lowercase. Matching is done with startswith() to handle variants like "initiale ornée (1)".
BIBLISSIMA_TYPE_MAPPING = {
    "initiale ornée": "31158e76-817a-447d-a40c-3963731296a8",      # lettrine/initial
    "initiale filigranée": "31158e76-817a-447d-a40c-3963731296a8",  # lettrine/initial
    "initiale historiée": "31158e76-817a-447d-a40c-3963731296a8",   # lettrine/initial
    "initiale animée": "31158e76-817a-447d-a40c-3963731296a8",      # lettrine/initial
    "initiale zoomorphe": "31158e76-817a-447d-a40c-3963731296a8",   # lettrine/initial
    "initiale anthropomorphe": "31158e76-817a-447d-a40c-3963731296a8",
    "initiale de couleur": "31158e76-817a-447d-a40c-3963731296a8",
    "initiale": "31158e76-817a-447d-a40c-3963731296a8",
    "lettrine": "31158e76-817a-447d-a40c-3963731296a8",
    "lettre ornée": "2f5df709-4f32-40b4-8858-d0d54ba25d61",        # decorated letter
    "lettre cadelée": "2f5df709-4f32-40b4-8858-d0d54ba25d61",
    "lettre or": "2f5df709-4f32-40b4-8858-d0d54ba25d61",
    "miniature": "63bc98e3-57de-48fc-a656-8d6f9a9acf40",           # miniature
    "page décorée": "4063b4aa-c50b-4101-947c-d8094eed6e25",        # Decoration
    "décor": "4063b4aa-c50b-4101-947c-d8094eed6e25",
    "bordure": "4063b4aa-c50b-4101-947c-d8094eed6e25",
    "bandeau": "4063b4aa-c50b-4101-947c-d8094eed6e25",
    "encadrement": "4063b4aa-c50b-4101-947c-d8094eed6e25",
    "frontispice": "0805a584-1395-48df-8e84-4ae4b25cdeae",         # frontispiece
    "vignette": "29167061-2645-4d86-8f30-9206c1f83297",            # vignette
    "photographie": "85e458af-0292-4ecb-84b9-5715071d45e1",        # photography
    "filigrane": "c3168cc7-23d3-4ddb-9eac-38383b852f5a",           # watermark
    "planche": "36a20d43-f316-4d0f-bf58-ec8a2cb71d0a",             # board
    "enluminure": "3ecd8040-7c4b-4b1d-88f7-379297358f66",          # illumination (default)
}

# Default fallback when no type mapping matches
BIBLISSIMA_TYPE_DEFAULT = "3ecd8040-7c4b-4b1d-88f7-379297358f66"  # illumination


def _resolve_biblissima_type(typologie="", descriptor="", type_field=""):
    """Resolve a Biblissima illumination to an Arches Type of Component valueid.

    Priority: typologie > descriptor > type_field > default.
    Uses startswith matching for variants (e.g. "initiale ornée (1)").
    """
    for term in (typologie, descriptor, type_field):
        if not term:
            continue
        normalized = term.lower().strip()
        # Remove trailing numbering like "(1)", "(2)"
        normalized = re.sub(r'\s*\(\d+\)\s*$', '', normalized)
        # Try exact match first
        if normalized in BIBLISSIMA_TYPE_MAPPING:
            return BIBLISSIMA_TYPE_MAPPING[normalized]
        # Try startswith match
        for key, valueid in BIBLISSIMA_TYPE_MAPPING.items():
            if normalized.startswith(key):
                return valueid
    return BIBLISSIMA_TYPE_DEFAULT


class BiblissimaManuscriptIlluminationsView(View):
    """Scrape Biblissima portal page for a manuscript to list its illuminations."""

    @method_decorator(cache_page(60))
    def get(self, request):
        portal_hash = request.GET.get("portalHash", "").strip()
        if not portal_hash:
            return JsonResponse({"error": "portalHash required"}, status=400)

        try:
            resp = requests.get(
                f"{BIBLISSIMA_PORTAL}/{portal_hash}",
                timeout=REQUEST_TIMEOUT * 2,
            )
            resp.raise_for_status()
            html = resp.text
        except Exception:
            logger.warning("Failed to fetch portal page for %s", portal_hash)
            return JsonResponse({"error": "Failed to fetch portal page"}, status=502)

        results = []
        # Detect which ifdata entries have a digitization icon
        has_image_set = set(re.findall(r'fa-picture-o.*?ark:/43093/(ifdata\w+)', html))

        # Parse all ifdata links
        for match in re.finditer(
            r'<a\s+href="[^"]*ark:/43093/(ifdata\w+)"[^>]*>([^<]+)</a>', html
        ):
            ifdata_hash = match.group(1)
            label = match.group(2).strip()

            # Descriptor = text before first "("
            desc_match = re.match(r'^([^(]+)', label)
            descriptor = desc_match.group(1).strip() if desc_match else label

            # Folio = f.NNN pattern at end
            folio_match = re.search(r'\bf\.?\s*(\d+\w*)\)?$', label)
            folio = folio_match.group(1) if folio_match else ""

            # Resolve type from descriptor
            type_valueid = _resolve_biblissima_type(descriptor=descriptor)

            results.append({
                "ifdataHash": ifdata_hash,
                "arkId": f"ark:/43093/{ifdata_hash}",
                "label": label,
                "descriptor": descriptor,
                "folio": folio,
                "hasImage": ifdata_hash in has_image_set,
                "portalUrl": f"{BIBLISSIMA_PORTAL}/{ifdata_hash}",
                "typeValueId": type_valueid,
            })

        return JsonResponse({"total": len(results), "results": results})


class BiblissimaIlluminationDetailView(View):
    """Scrape a single illumination page from the Biblissima portal."""

    @method_decorator(cache_page(60))
    def get(self, request, ifdata_hash):
        try:
            resp = requests.get(
                f"{BIBLISSIMA_PORTAL}/{ifdata_hash}",
                timeout=REQUEST_TIMEOUT * 2,
            )
            resp.raise_for_status()
            html = resp.text
        except Exception:
            logger.warning("Failed to fetch illumination page %s", ifdata_hash)
            return JsonResponse({"error": "Failed to fetch page"}, status=502)

        result = {
            "ifdataHash": ifdata_hash,
            "arkId": f"ark:/43093/{ifdata_hash}",
            "portalUrl": f"{BIBLISSIMA_PORTAL}/{ifdata_hash}",
        }

        # Parse presentation section (key: value pairs on alternating lines)
        pres_match = re.search(r'id="presentation">(.*?)</section>', html, re.DOTALL)
        if pres_match:
            text = re.sub(r'<[^>]+>', '\n', pres_match.group(1))
            lines = [l.strip() for l in text.split('\n') if l.strip()]

            if lines:
                result["label"] = lines[0]

            field_map = {
                "Type": "type",
                "Feuillet / page": "folio",
                "Typologie": "typologie",
                "Technique": "technique",
                "Date de fabrication": "date",
                "Manuscrit": "manuscript",
                "Texte": "text",
                "Lieu de fabrication": "location",
            }
            # Collect descriptors (multi-value, comma-separated across lines)
            in_descriptors = False
            descriptor_parts = []

            for i, line in enumerate(lines):
                if line == "Descripteurs :":
                    in_descriptors = True
                    continue
                if in_descriptors:
                    if line == ",":
                        continue
                    if any(line.startswith(f"{k}") for k in field_map) or line.endswith(":"):
                        in_descriptors = False
                    else:
                        descriptor_parts.append(line)
                        continue

                for key, field in field_map.items():
                    if line.startswith(key) and ":" in line and i + 1 < len(lines):
                        result[field] = lines[i + 1]
                        break

            if descriptor_parts:
                result["descriptors"] = descriptor_parts

        # Resolve type: typologie > descriptor from label > type field
        typologie = result.get("typologie", "")
        descriptor = ""
        if result.get("label"):
            desc_match = re.match(r'^([^(]+)', result["label"])
            if desc_match:
                descriptor = desc_match.group(1).strip()
        type_field = result.get("type", "")
        result["typeValueId"] = _resolve_biblissima_type(typologie, descriptor, type_field)

        # Manuscript ARK
        ms_match = re.search(r'ark:/43093/(mdata\w+)', html)
        if ms_match:
            result["manuscriptHash"] = ms_match.group(1)
            result["manuscriptArk"] = f"ark:/43093/{ms_match.group(1)}"

        # Gallica image URL
        gallica_image = re.search(
            r'(https://gallica\.bnf\.fr/ark:/12148/\w+/f\d+\.image)', html
        )
        if gallica_image:
            result["imageUrl"] = gallica_image.group(1)
            result["thumbnail"] = gallica_image.group(1).replace(".image", ".thumbnail")

        # Gallica IIIF info (for canvas in annotation)
        gallica_iiif = re.search(
            r'(https://gallica\.bnf\.fr/iiif/ark:/12148/\w+/f\d+/info\.json)', html
        )
        if gallica_iiif:
            result["iiifInfoUrl"] = gallica_iiif.group(1)
            result["canvasUrl"] = gallica_iiif.group(1).replace("/info.json", "")

        # Gallica manifest
        gallica_manifest = re.search(
            r'(https://gallica\.bnf\.fr/iiif/ark:/12148/\w+/manifest\.json)', html
        )
        if gallica_manifest:
            result["manifestUrl"] = gallica_manifest.group(1)

        # Mandragore ARK
        mandragore = re.search(r'mandragore\.bnf\.fr/ark:/12148/(\w+)', html)
        if mandragore:
            result["mandragoreArk"] = f"ark:/12148/{mandragore.group(1)}"

        return JsonResponse(result)


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
        """Create a resource with all its tiles from Biblissima data.

        Wrapped in a DB transaction — if anything fails, everything rolls back.
        Elasticsearch indexing is deferred until after all DB writes succeed,
        so a rollback leaves no orphan documents in ES.
        """
        from django.db import transaction
        from arches.app.models.resource import Resource

        with transaction.atomic():
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

        # DB transaction succeeded — now index into Elasticsearch
        try:
            resource = Resource.objects.get(resourceinstanceid=resource_id)
            resource.index()
        except Exception:
            logger.warning("ES indexing failed for resource %s (DB is committed)", resource_id)

        return resource_id, created_deps

    def _create_tile(self, nodegroup_id, resource_id, data, transaction_id=None):
        """Create a single tile without ES indexing (deferred to after commit)."""
        tile = Tile(
            tileid=uuid.uuid4(),
            nodegroup_id=nodegroup_id,
            resourceinstance_id=resource_id,
            data=data,
            sortorder=0,
        )
        if transaction_id:
            tile.transaction_id = transaction_id
        tile.save(index=False)
        return tile

    @staticmethod
    def _i18n_string(value, lang="en"):
        """Format a string as Arches i18n dict."""
        return {lang: {"value": str(value), "direction": "ltr"}}

    @staticmethod
    def _concept_valueid(concept_id):
        """Get the prefLabel valueid for a concept ID.

        Prefers English, falls back to any language.
        """
        try:
            # Try English first
            val = Value.objects.filter(
                concept_id=concept_id, valuetype="prefLabel",
            ).filter(language__in=["en", "en-US", "en-UK", "English"]).first()
            if val:
                return str(val.valueid)
            # Fallback to any language
            val = Value.objects.filter(
                concept_id=concept_id, valuetype="prefLabel",
            ).first()
            return str(val.valueid) if val else concept_id
        except Exception:
            return concept_id

    def _concept_list(self, concept_ids):
        """Convert a list of concept IDs to a list of valueids."""
        if isinstance(concept_ids, str):
            concept_ids = [concept_ids]
        return [self._concept_valueid(cid) for cid in concept_ids]

    def _create_document_tiles(self, resource_id, transaction_id, bbma_data, deps, concepts, created_deps):
        """Create all tiles for a Document resource."""
        i18n = self._i18n_string
        clist = self._concept_list

        # Name
        label = bbma_data.get("label", "Untitled")
        self._create_tile(
            DOC_NAME_NG, resource_id,
            {
                DOC_NAME_LABEL: i18n(label),
                DOC_NAME_LANGUAGE: clist([CONCEPT_FRENCH]),
                DOC_NAME_TYPE: clist([CONCEPT_PREFERRED_TERMS]),
            },
            transaction_id,
        )

        # Second name tile for shelfmark if available
        shelfmark = bbma_data.get("shelfmark")
        if shelfmark:
            self._create_tile(
                DOC_NAME_NG, resource_id,
                {
                    DOC_NAME_LABEL: i18n(shelfmark),
                    DOC_NAME_LANGUAGE: clist([CONCEPT_FRENCH]),
                    DOC_NAME_TYPE: clist(["7cca3482-44b5-42ea-a1d7-120cd732b350"]),
                },
                transaction_id,
            )

        # Type (concept node, single valueid string)
        doc_type = concepts.get("type")
        if doc_type:
            # doc_type from frontend is already a valueid (selected via concept-select-widget)
            self._create_tile(
                DOC_TYPE_NG, resource_id,
                {DOC_TYPE_NODE: doc_type},
                transaction_id,
            )

        # Identifiers
        ark_id = bbma_data.get("arkId")
        if ark_id:
            self._create_tile(
                DOC_IDENTIFIER_NG, resource_id,
                {
                    DOC_IDENTIFIER_VALUE: i18n(ark_id),
                    DOC_IDENTIFIER_TYPE: clist([CONCEPT_PERSISTENT_ID]),
                    DOC_IDENTIFIER_SOURCE: clist([CONCEPT_SOURCE_BIBLISSIMA]),
                },
                transaction_id,
            )

        qid = bbma_data.get("biblissimaQid")
        if qid:
            self._create_tile(
                DOC_IDENTIFIER_NG, resource_id,
                {
                    DOC_IDENTIFIER_VALUE: i18n(f"https://data.biblissima.fr/entity/{qid}"),
                    DOC_IDENTIFIER_TYPE: clist([CONCEPT_RECORD_ID]),
                    DOC_IDENTIFIER_SOURCE: clist([CONCEPT_SOURCE_BIBLISSIMA]),
                },
                transaction_id,
            )

        mandragore_id = bbma_data.get("mandragoreId")
        if mandragore_id:
            self._create_tile(
                DOC_IDENTIFIER_NG, resource_id,
                {
                    DOC_IDENTIFIER_VALUE: i18n(mandragore_id),
                    DOC_IDENTIFIER_TYPE: clist([CONCEPT_RECORD_ID]),
                    DOC_IDENTIFIER_SOURCE: clist([CONCEPT_SOURCE_MANDRAGORE]),
                },
                transaction_id,
            )

        # Statement (description)
        legend = bbma_data.get("legend") or bbma_data.get("label", "")
        portal_url = bbma_data.get("portalUrl", "")
        if legend:
            self._create_tile(
                DOC_STATEMENT_NG, resource_id,
                {
                    DOC_STATEMENT_CONTENT: i18n(legend),
                    DOC_STATEMENT_TYPE: clist([CONCEPT_DESCRIPTION]),
                    DOC_STATEMENT_LANGUAGE: clist([CONCEPT_FRENCH]),
                    DOC_STATEMENT_SOURCE: {"url": portal_url, "url_label": ""} if portal_url else None,
                },
                transaction_id,
            )

        # Facsimiles (IIIF manifest) - manifest datatype accepts URL string directly
        manifest_url = bbma_data.get("manifestUrl")
        if manifest_url:
            self._create_tile(
                DOC_FACSIMILES_NG, resource_id,
                {DOC_FACSIMILES_NODE: manifest_url},
                transaction_id,
            )

        # Period
        date_str = bbma_data.get("date", "")
        century_concept = _parse_century(date_str)
        if century_concept:
            self._create_tile(
                DOC_PERIOD_NG, resource_id,
                {
                    DOC_PERIOD_ABSOLUTE: clist([century_concept]),
                    DOC_PERIOD_PRODUCTION: clist([CONCEPT_MEDIEVAL]),
                },
                transaction_id,
            )

        # Production
        prod_data = {DOC_PROD_TIME_TYPE: False}

        if date_str:
            prod_data[DOC_PROD_DATE_START] = self._century_to_date(date_str)

        place_id = deps.get("productionPlace")
        if place_id:
            prod_data[DOC_PROD_PLACE] = self._resource_instance_list(place_id)

        actor_ids = deps.get("productionActors", [])
        if actor_ids:
            prod_data[DOC_PROD_ACTORS] = self._resource_instance_list(actor_ids)

        if len(prod_data) > 1:
            self._create_tile(
                DOC_PRODUCTION_NG, resource_id,
                prod_data,
                transaction_id,
            )

        # Current location
        location_id = deps.get("currentLocation")
        if location_id:
            self._create_tile(
                DOC_LOCATION_NG, resource_id,
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
                DOC_OWNER_NG, resource_id,
                {DOC_OWNER_NODE: self._resource_instance_list(owner_ids)},
                transaction_id,
            )

        # Part of
        parent_doc_id = deps.get("partOf")
        if parent_doc_id:
            self._create_tile(
                DOC_PART_OF_NG, resource_id,
                {DOC_PART_OF_NODE: self._resource_instance_list(parent_doc_id)},
                transaction_id,
            )

    def _create_component_tiles(self, resource_id, transaction_id, bbma_data, deps, concepts, created_deps):
        """Create all tiles for a Component resource."""
        i18n = self._i18n_string
        clist = self._concept_list

        # Name
        label = bbma_data.get("legend") or bbma_data.get("label", "Untitled")
        self._create_tile(
            COMP_NAME_NG, resource_id,
            {
                COMP_NAME_LABEL: i18n(label),
                COMP_NAME_LANGUAGE: clist([CONCEPT_FRENCH]),
                COMP_NAME_TYPE: clist([CONCEPT_PREFERRED_TERMS]),
            },
            transaction_id,
        )

        # Type (concept-list node, expects list of valueids)
        comp_type = concepts.get("type")
        if comp_type:
            # comp_type from frontend is already a valueid
            self._create_tile(
                COMP_TYPE_NG, resource_id,
                {COMP_TYPE_NODE: [comp_type]},
                transaction_id,
            )

        # Parent Document (required)
        parent_doc_id = deps.get("parentDocument")
        if parent_doc_id:
            self._create_tile(
                COMP_PARENT_DOC_NG, resource_id,
                {COMP_PARENT_DOC_NODE: self._resource_instance_ref(parent_doc_id)},
                transaction_id,
            )

        # Identifiers
        ark_id = bbma_data.get("arkId")
        if ark_id:
            self._create_tile(
                COMP_IDENTIFIER_NG, resource_id,
                {
                    COMP_IDENTIFIER_VALUE: i18n(ark_id),
                    COMP_IDENTIFIER_TYPE: clist([CONCEPT_PERSISTENT_ID]),
                    COMP_IDENTIFIER_SOURCE: clist([CONCEPT_SOURCE_BIBLISSIMA]),
                },
                transaction_id,
            )

        # Statement
        legend = bbma_data.get("label", "")
        portal_url = bbma_data.get("portalUrl", "")
        if legend:
            self._create_tile(
                COMP_STATEMENT_NG, resource_id,
                {
                    COMP_STATEMENT_CONTENT: i18n(legend),
                    COMP_STATEMENT_TYPE: clist([CONCEPT_DESCRIPTION]),
                    COMP_STATEMENT_LANGUAGE: clist([CONCEPT_FRENCH]),
                    COMP_STATEMENT_SOURCE: {"url": portal_url, "url_label": ""} if portal_url else None,
                },
                transaction_id,
            )

        # Iconographic representation (URL datatype, plain string)
        thumbnail = bbma_data.get("thumbnail") or bbma_data.get("imageUrl")
        if thumbnail:
            self._create_tile(
                COMP_ICONOGRAPHIC_NG, resource_id,
                {COMP_ICONOGRAPHIC_NODE: thumbnail},
                transaction_id,
            )

        # Context (string datatype, i18n format)
        folio = bbma_data.get("folio")
        if folio:
            self._create_tile(
                COMP_CONTEXT_NG, resource_id,
                {COMP_CONTEXT_NODE: i18n(folio)},
                transaction_id,
            )

        # Period
        date_str = bbma_data.get("date", "")
        century_concept = _parse_century(date_str)
        if century_concept:
            self._create_tile(
                COMP_PERIOD_NG, resource_id,
                {
                    COMP_PERIOD_ABSOLUTE: clist([century_concept]),
                    COMP_PERIOD_PRODUCTION: clist([CONCEPT_MEDIEVAL]),
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

        if len(prod_data) > 1:
            self._create_tile(
                COMP_PRODUCTION_NG, resource_id,
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
        # Validate project_id is a proper UUID
        try:
            project_uuid = uuid.UUID(str(project_id))
        except (ValueError, AttributeError):
            logger.warning("Invalid project_id for linking: %r", project_id)
            return

        project_id = str(project_uuid)

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
