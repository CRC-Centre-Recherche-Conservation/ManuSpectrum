"""Biblissima import workflow — module-level constants.

Mapping / graph / node-id constants used by ``biblissima_proxy.py``
(Wikibase property IDs, Arches graph/nodegroup/node UUIDs, concept value
ids, type/document-nature mappings, cache key templates) live here so the
proxy module keeps its focus on request handling and tile creation logic.

Runtime/network configuration (URLs, HTTP timeouts, concurrency limit,
cache TTL) lives in Django settings instead — see the BIBLISSIMA_* entries
in ``manuspectrum/settings.py``. They are tunable per-environment via
``settings_local.py``.

Imported in bulk from ``biblissima_proxy.py`` via a star import; tests
reach the same names via ``manuspectrum.views.biblissima_proxy`` because
they're re-exposed in that module's namespace.
"""

import re

# ---------------------------------------------------------------------------
# Cache key templates (the TTL itself lives in
# ``settings.BIBLISSIMA_CACHE_TTL``).
# ---------------------------------------------------------------------------
_BIBLISSIMA_ENTITY_CACHE_KEY = "biblissima:wikibase:entity:{qid}"
_BIBLISSIMA_MANUSCRIPT_CACHE_KEY = "biblissima:wikibase:manuscript:{ark_hash}"


# ---------------------------------------------------------------------------
# Wikibase property IDs
# ---------------------------------------------------------------------------
P2 = "P2"  # nature de l'élément
P129 = "P129"  # identifiant Portail Biblissima
P194 = "P194"  # collection (institution)
P195 = "P195"  # cote (shelfmark)
P196 = "P196"  # manifeste IIIF
P197 = "P197"  # numérisation URL
P198 = "P198"  # identifiant BnF Archives et Manuscrits (AeM)
P270 = "P270"  # identifiant Mandragore
P354 = "P354"  # auteur
P201 = "P201"  # localisation (place)
P169 = "P169"  # partie de (parent institution)
P123 = "P123"  # identifiant Geonames


# ---------------------------------------------------------------------------
# Arches graph UUIDs
# ---------------------------------------------------------------------------
DOCUMENT_GRAPH_ID = "0c8226c1-11a9-4c48-9601-a7a0c6f2df6b"
COMPONENT_GRAPH_ID = "d47595b4-f8a6-419c-8f33-b388206280c4"
PROJECT_GRAPH_ID = "87a4319d-3ca5-43f6-88cc-a7379fba67f6"
PLACE_GRAPH_ID = "3f2b036a-b65d-474d-b692-0b21903655c5"
PERSON_GRAPH_ID = "5bf45c85-84cd-4a76-b64a-3ffe86eea1b8"
GROUP_GRAPH_ID = "4f447dca-dbb3-48d0-bc90-3f2935db8b8c"


# ---------------------------------------------------------------------------
# Document — nodegroups & nodes
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Project — nodegroups & nodes
# ---------------------------------------------------------------------------
PROJECT_STUDIED_OBJECTS_NG = "a8fb3c9e-bbc4-11ef-bd5f-ed806b645d76"
PROJECT_STUDIED_OBJECTS_NODE = "a8fb3c9e-bbc4-11ef-bd5f-ed806b645d76"


# ---------------------------------------------------------------------------
# Component — nodegroups & nodes
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Place — nodegroups & nodes
# ---------------------------------------------------------------------------
PLACE_NAME_NG = "e4513853-7024-11ef-8753-0575b5bada34"
PLACE_NAME_LABEL = "e4513856-7024-11ef-8753-0575b5bada34"
PLACE_NAME_LANGUAGE = "e4513855-7024-11ef-8753-0575b5bada34"
PLACE_NAME_TYPE = "e4513857-7024-11ef-8753-0575b5bada34"

PLACE_IDENTIFIER_NG = "e7bf9151-7024-11ef-8753-0575b5bada34"
PLACE_IDENTIFIER_VALUE = "e7bf9153-7024-11ef-8753-0575b5bada34"
PLACE_IDENTIFIER_SOURCE = "e7bf9154-7024-11ef-8753-0575b5bada34"
PLACE_IDENTIFIER_TYPE = "e7bf9155-7024-11ef-8753-0575b5bada34"


# ---------------------------------------------------------------------------
# Group — nodegroups & nodes
# ---------------------------------------------------------------------------
GROUP_NAME_NG = "e69cbd41-7018-11ef-8753-0575b5bada34"
GROUP_NAME_LABEL = "e69cbd44-7018-11ef-8753-0575b5bada34"
GROUP_NAME_LANGUAGE = "e69cbd43-7018-11ef-8753-0575b5bada34"
GROUP_NAME_TYPE = "e69cbd45-7018-11ef-8753-0575b5bada34"

GROUP_IDENTIFIER_NG = "eda9eee7-7018-11ef-8753-0575b5bada34"
GROUP_IDENTIFIER_VALUE = "eda9eee9-7018-11ef-8753-0575b5bada34"
GROUP_IDENTIFIER_SOURCE = "eda9eeea-7018-11ef-8753-0575b5bada34"
GROUP_IDENTIFIER_TYPE = "eda9eeeb-7018-11ef-8753-0575b5bada34"

GROUP_MEMBER_OF_NG = "86e02cce-7019-11ef-8753-0575b5bada34"
GROUP_MEMBER_OF_NODE = "86e02cce-7019-11ef-8753-0575b5bada34"

GROUP_LOCATION_NG = "636b1b3e-ae2e-11ef-8dd2-3b6c98a10134"
GROUP_LOCATION_NODE = "636b1b3e-ae2e-11ef-8dd2-3b6c98a10134"


# ---------------------------------------------------------------------------
# Person — nodegroups & nodes
# ---------------------------------------------------------------------------
PERSON_NAME_NG = "8e97f1a7-701c-11ef-8753-0575b5bada34"
PERSON_NAME_LABEL = "8e97f1aa-701c-11ef-8753-0575b5bada34"
PERSON_NAME_LANGUAGE = "8e97f1a9-701c-11ef-8753-0575b5bada34"
PERSON_NAME_TYPE = "8e97f1ab-701c-11ef-8753-0575b5bada34"

PERSON_IDENTIFIER_NG = "943a2c65-701c-11ef-8753-0575b5bada34"
PERSON_IDENTIFIER_VALUE = "943a2c67-701c-11ef-8753-0575b5bada34"
PERSON_IDENTIFIER_SOURCE = "943a2c68-701c-11ef-8753-0575b5bada34"
PERSON_IDENTIFIER_TYPE = "943a2c69-701c-11ef-8753-0575b5bada34"


# ---------------------------------------------------------------------------
# Dependency name nodegroup lookup by graph id (used to upsert Place / Group /
# Person Name tiles when creating dependencies).
# ---------------------------------------------------------------------------
DEP_NAME_CONFIG = {
    PLACE_GRAPH_ID: {
        "ng": PLACE_NAME_NG,
        "label": PLACE_NAME_LABEL,
        "language": PLACE_NAME_LANGUAGE,
        "type": PLACE_NAME_TYPE,
    },
    GROUP_GRAPH_ID: {
        "ng": GROUP_NAME_NG,
        "label": GROUP_NAME_LABEL,
        "language": GROUP_NAME_LANGUAGE,
        "type": GROUP_NAME_TYPE,
    },
    PERSON_GRAPH_ID: {
        "ng": PERSON_NAME_NG,
        "label": PERSON_NAME_LABEL,
        "language": PERSON_NAME_LANGUAGE,
        "type": PERSON_NAME_TYPE,
    },
}


# ---------------------------------------------------------------------------
# Concept defaults
# ---------------------------------------------------------------------------
CONCEPT_ALTERNATE_TITLES = "7cca3482-44b5-42ea-a1d7-120cd732b350"
CONCEPT_FRENCH = "a1d82c77-ebd6-4215-ab85-2c0b6a68a0e8"
CONCEPT_PREFERRED_TERMS = "5f400d39-3b6b-4b8a-939b-4e49787c7444"
CONCEPT_PERSISTENT_ID = "5b292232-52ac-4e71-ba6c-fe4dd6ff02fa"
CONCEPT_RECORD_ID = "e10752d3-d8fa-47cb-92f9-dd7277dfc97a"
CONCEPT_SOURCE_BIBLISSIMA = "39124989-dfb1-4e2a-9d1a-4bff0827ed71"
CONCEPT_SOURCE_MANDRAGORE = "3b78627a-c751-43df-b427-73e1dd11ec38"
CONCEPT_SOURCE_BNF = "bd1fa4c5-c7e7-45d2-b58c-e5f54a1da34d"
CONCEPT_DESCRIPTION = "9a51d30b-48e8-4f94-9344-cd2bb1d4b33a"
# Statement type for "Texte" (work).
CONCEPT_IDENTIFICATION = "d2a8104a-312a-4f1d-acb7-3ecb1335e2fc"
# Statement type for "Rubrique".
CONCEPT_INSCRIPTIONS = "9076a3e5-06f5-4ed7-91e4-985914c7178b"
CONCEPT_MANUSCRIT = "56c61151-3bc5-45b4-957e-3cccde26abe7"
CONCEPT_DECOR = "c19f3196-d1e9-4f08-9917-4d627e61e153"
CONCEPT_SHELF_MARKS = "2cbf15b4-aa04-4b5b-bf4a-2594bbeb72ca"
CONCEPT_MEDIEVAL = "f8101404-1570-35cf-ac70-1a18a84072ca"

RELATIONSHIP_CONCEPT = "ac41d9be-79db-4256-b368-2f4559cfbe55"


# ---------------------------------------------------------------------------
# Component Type mapping — Biblissima illumination type/typologie/descriptor
# strings → Arches Type-of-Component valueid. Keys are lowercase; matching
# uses ``startswith`` to handle variants like "initiale ornée (1)".
# ---------------------------------------------------------------------------
BIBLISSIMA_TYPE_MAPPING = {
    "initiale ornée": "31158e76-817a-447d-a40c-3963731296a8",  # lettrine/initial
    "initiale filigranée": "31158e76-817a-447d-a40c-3963731296a8",
    "initiale historiée": "31158e76-817a-447d-a40c-3963731296a8",
    "initiale animée": "31158e76-817a-447d-a40c-3963731296a8",
    "initiale zoomorphe": "31158e76-817a-447d-a40c-3963731296a8",
    "initiale anthropomorphe": "31158e76-817a-447d-a40c-3963731296a8",
    "initiale de couleur": "31158e76-817a-447d-a40c-3963731296a8",
    "initiale": "31158e76-817a-447d-a40c-3963731296a8",
    "lettrine": "31158e76-817a-447d-a40c-3963731296a8",
    "lettre ornée": "2f5df709-4f32-40b4-8858-d0d54ba25d61",  # decorated letter
    "lettre cadelée": "2f5df709-4f32-40b4-8858-d0d54ba25d61",
    "lettre or": "2f5df709-4f32-40b4-8858-d0d54ba25d61",
    "miniature": "63bc98e3-57de-48fc-a656-8d6f9a9acf40",  # miniature
    "page décorée": "4063b4aa-c50b-4101-947c-d8094eed6e25",  # Decoration
    "décor": "4063b4aa-c50b-4101-947c-d8094eed6e25",
    "bordure": "4063b4aa-c50b-4101-947c-d8094eed6e25",
    "bandeau": "4063b4aa-c50b-4101-947c-d8094eed6e25",
    "encadrement": "4063b4aa-c50b-4101-947c-d8094eed6e25",
    "frontispice": "0805a584-1395-48df-8e84-4ae4b25cdeae",  # frontispiece
    "vignette": "29167061-2645-4d86-8f30-9206c1f83297",  # vignette
    "photographie": "85e458af-0292-4ecb-84b9-5715071d45e1",  # photography
    "filigrane": "c3168cc7-23d3-4ddb-9eac-38383b852f5a",  # watermark
    "planche": "36a20d43-f316-4d0f-bf58-ec8a2cb71d0a",  # board
    "enluminure": "3ecd8040-7c4b-4b1d-88f7-379297358f66",  # illumination (default)
}

# Default fallback when no Component type mapping matches.
BIBLISSIMA_TYPE_DEFAULT = "3ecd8040-7c4b-4b1d-88f7-379297358f66"  # illumination

# Human-readable labels for each Component target valueid (FR; matches the
# concept collection language).
BIBLISSIMA_TYPE_VALUEID_LABELS = {
    "31158e76-817a-447d-a40c-3963731296a8": "Lettrine",
    "2f5df709-4f32-40b4-8858-d0d54ba25d61": "Lettre ornée",
    "63bc98e3-57de-48fc-a656-8d6f9a9acf40": "Miniature",
    "4063b4aa-c50b-4101-947c-d8094eed6e25": "Décor",
    "0805a584-1395-48df-8e84-4ae4b25cdeae": "Frontispice",
    "29167061-2645-4d86-8f30-9206c1f83297": "Vignette",
    "85e458af-0292-4ecb-84b9-5715071d45e1": "Photographie",
    "c3168cc7-23d3-4ddb-9eac-38383b852f5a": "Filigrane",
    "36a20d43-f316-4d0f-bf58-ec8a2cb71d0a": "Planche",
    "3ecd8040-7c4b-4b1d-88f7-379297358f66": "Enluminure",
}


# ---------------------------------------------------------------------------
# Document Type mapping — Biblissima 'nature de l'élément' (P2 label) →
# Arches Document Type valueid. Sample of 1500 random Biblissima items
# shows ~96% are some flavour of 'manuscrit' and ~7.5% are 'imprimé'; the
# remainder (<1%, e.g. estampe) falls through to the default and the UI
# shows a "needs review" badge so the analyst can correct the type inline.
# Keyed by lowercase canonical label, not QID, for two reasons:
#   • robust if Biblissima reorganises entities under different QIDs
#   • mirrors _resolve_biblissima_type (Component) which also keys on labels
# ---------------------------------------------------------------------------
VALUEID_MANUSCRIT = "30931466-b4e0-4527-ac93-b7290e80084c"
VALUEID_TEXTE_IMPRIME = "feff36de-e9d0-4723-b00b-142dc19df8ed"

BIBLISSIMA_DOCUMENT_NATURE_MAP = {
    "manuscrit": VALUEID_MANUSCRIT,
    "manuscrits en plusieurs volumes": VALUEID_MANUSCRIT,
    "unité codicologique": VALUEID_MANUSCRIT,
    "imprimé": VALUEID_TEXTE_IMPRIME,
    "texte imprimé": VALUEID_TEXTE_IMPRIME,
}

DOCUMENT_NATURE_DEFAULT = VALUEID_MANUSCRIT  # 96% Biblissima is manuscrit

# Human-readable labels for the resolved valueids — used by the badge UI
# (mirrors BIBLISSIMA_TYPE_VALUEID_LABELS for Components).
BIBLISSIMA_DOCUMENT_TYPE_VALUEID_LABELS = {
    VALUEID_MANUSCRIT: "Manuscrit",
    VALUEID_TEXTE_IMPRIME: "Texte imprimé",
}


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
# Compiled regex used by ``_extract_ark`` to pull the hash component out
# of a ``ark:/43093/<hash>`` ARK identifier wherever it appears in HTML
# fragments scraped from Biblissima.
_ARK_RE = re.compile(r"ark:/43093/(\w+)")


__all__ = [
    # Cache key templates (TTL is in Django settings)
    "_BIBLISSIMA_ENTITY_CACHE_KEY",
    "_BIBLISSIMA_MANUSCRIPT_CACHE_KEY",
    # Wikibase property IDs
    "P2",
    "P129",
    "P194",
    "P195",
    "P196",
    "P197",
    "P198",
    "P270",
    "P354",
    "P201",
    "P169",
    "P123",
    # Arches graph UUIDs
    "DOCUMENT_GRAPH_ID",
    "COMPONENT_GRAPH_ID",
    "PROJECT_GRAPH_ID",
    "PLACE_GRAPH_ID",
    "PERSON_GRAPH_ID",
    "GROUP_GRAPH_ID",
    # Document NG/nodes
    "DOC_NAME_NG",
    "DOC_NAME_LABEL",
    "DOC_NAME_LANGUAGE",
    "DOC_NAME_TYPE",
    "DOC_IDENTIFIER_NG",
    "DOC_IDENTIFIER_VALUE",
    "DOC_IDENTIFIER_SOURCE",
    "DOC_IDENTIFIER_TYPE",
    "DOC_TYPE_NG",
    "DOC_TYPE_NODE",
    "DOC_STATEMENT_NG",
    "DOC_STATEMENT_CONTENT",
    "DOC_STATEMENT_LANGUAGE",
    "DOC_STATEMENT_SOURCE",
    "DOC_STATEMENT_TYPE",
    "DOC_FACSIMILES_NG",
    "DOC_FACSIMILES_NODE",
    "DOC_LOCATION_NG",
    "DOC_LOCATION_NODE",
    "DOC_LOCATION_LITERAL",
    "DOC_OWNER_NG",
    "DOC_OWNER_NODE",
    "DOC_PRODUCTION_NG",
    "DOC_PROD_ACTORS",
    "DOC_PROD_MOTIVATED",
    "DOC_PROD_PLACE",
    "DOC_PROD_INFLUENCES",
    "DOC_PROD_DATE_START",
    "DOC_PROD_DATE_END",
    "DOC_PROD_TIME_TYPE",
    "DOC_PROD_CULTURAL",
    "DOC_PROD_TECHNIQUES",
    "DOC_PERIOD_NG",
    "DOC_PERIOD_ABSOLUTE",
    "DOC_PERIOD_PRODUCTION",
    "DOC_DIMENSION_NG",
    "DOC_DIMENSION_TYPE",
    "DOC_DIMENSION_UNIT",
    "DOC_DIMENSION_VALUE",
    "DOC_COMPOSED_NG",
    "DOC_COMPOSED_TYPE",
    "DOC_COMPOSED_UNIT",
    "DOC_COMPOSED_VALUE",
    "DOC_PART_OF_NG",
    "DOC_PART_OF_NODE",
    # Project NG/nodes
    "PROJECT_STUDIED_OBJECTS_NG",
    "PROJECT_STUDIED_OBJECTS_NODE",
    # Component NG/nodes
    "COMP_TYPE_NG",
    "COMP_TYPE_NODE",
    "COMP_PARENT_DOC_NG",
    "COMP_PARENT_DOC_NODE",
    "COMP_ICONOGRAPHIC_NG",
    "COMP_ICONOGRAPHIC_NODE",
    "COMP_NAME_NG",
    "COMP_NAME_LABEL",
    "COMP_NAME_LANGUAGE",
    "COMP_NAME_TYPE",
    "COMP_CONTEXT_NG",
    "COMP_CONTEXT_NODE",
    "COMP_IDENTIFIER_NG",
    "COMP_IDENTIFIER_VALUE",
    "COMP_IDENTIFIER_SOURCE",
    "COMP_IDENTIFIER_TYPE",
    "COMP_STATEMENT_NG",
    "COMP_STATEMENT_CONTENT",
    "COMP_STATEMENT_LANGUAGE",
    "COMP_STATEMENT_SOURCE",
    "COMP_STATEMENT_TYPE",
    "COMP_PRODUCTION_NG",
    "COMP_PROD_ACTORS",
    "COMP_PROD_MOTIVATED",
    "COMP_PROD_PLACE",
    "COMP_PROD_INFLUENCES",
    "COMP_PROD_DATE_START",
    "COMP_PROD_DATE_END",
    "COMP_PROD_TIME_TYPE",
    "COMP_PERIOD_NG",
    "COMP_PERIOD_ABSOLUTE",
    "COMP_PERIOD_PRODUCTION",
    "COMP_LOCATION_DOC_NG",
    "COMP_LOCATION_DOC_NODE",
    "COMP_LOCATION_APPELLATION",
    # Place NG/nodes
    "PLACE_NAME_NG",
    "PLACE_NAME_LABEL",
    "PLACE_NAME_LANGUAGE",
    "PLACE_NAME_TYPE",
    "PLACE_IDENTIFIER_NG",
    "PLACE_IDENTIFIER_VALUE",
    "PLACE_IDENTIFIER_SOURCE",
    "PLACE_IDENTIFIER_TYPE",
    # Group NG/nodes
    "GROUP_NAME_NG",
    "GROUP_NAME_LABEL",
    "GROUP_NAME_LANGUAGE",
    "GROUP_NAME_TYPE",
    "GROUP_IDENTIFIER_NG",
    "GROUP_IDENTIFIER_VALUE",
    "GROUP_IDENTIFIER_SOURCE",
    "GROUP_IDENTIFIER_TYPE",
    "GROUP_MEMBER_OF_NG",
    "GROUP_MEMBER_OF_NODE",
    "GROUP_LOCATION_NG",
    "GROUP_LOCATION_NODE",
    # Person NG/nodes
    "PERSON_NAME_NG",
    "PERSON_NAME_LABEL",
    "PERSON_NAME_LANGUAGE",
    "PERSON_NAME_TYPE",
    "PERSON_IDENTIFIER_NG",
    "PERSON_IDENTIFIER_VALUE",
    "PERSON_IDENTIFIER_SOURCE",
    "PERSON_IDENTIFIER_TYPE",
    # Dependency lookup
    "DEP_NAME_CONFIG",
    # Concept defaults
    "CONCEPT_ALTERNATE_TITLES",
    "CONCEPT_FRENCH",
    "CONCEPT_PREFERRED_TERMS",
    "CONCEPT_PERSISTENT_ID",
    "CONCEPT_RECORD_ID",
    "CONCEPT_SOURCE_BIBLISSIMA",
    "CONCEPT_SOURCE_MANDRAGORE",
    "CONCEPT_SOURCE_BNF",
    "CONCEPT_DESCRIPTION",
    "CONCEPT_IDENTIFICATION",
    "CONCEPT_INSCRIPTIONS",
    "CONCEPT_MANUSCRIT",
    "CONCEPT_DECOR",
    "CONCEPT_SHELF_MARKS",
    "CONCEPT_MEDIEVAL",
    "RELATIONSHIP_CONCEPT",
    # Type mappings
    "BIBLISSIMA_TYPE_MAPPING",
    "BIBLISSIMA_TYPE_DEFAULT",
    "BIBLISSIMA_TYPE_VALUEID_LABELS",
    "VALUEID_MANUSCRIT",
    "VALUEID_TEXTE_IMPRIME",
    "BIBLISSIMA_DOCUMENT_NATURE_MAP",
    "DOCUMENT_NATURE_DEFAULT",
    "BIBLISSIMA_DOCUMENT_TYPE_VALUEID_LABELS",
    # Misc
    "_ARK_RE",
]
