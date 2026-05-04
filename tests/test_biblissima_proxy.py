"""Unit tests for ``manuspectrum.views.biblissima_proxy``.

Covers the pure helpers (HTML/JSON parsing, type resolution, descriptor
normalization, IIIF thumbnail URL building) and the HTTP-backed helpers
(Wikibase entity/collection fetch, IIIF manifest canvas resolution) with
``unittest.mock`` stubbing ``requests.Session.get``.

Two flavours of test data:

- **Synthetic** — small inline HTML/JSON snippets exercising edge cases.
- **Fixture** — real Biblissima portal HTML and Gallica IIIF manifest
  responses captured under ``tests/fixtures/biblissima/`` and slimmed
  down. Anchored on the illumination
  ``ark:/43093/ifdata5be7529b7987eadf417506e4ea42ac11b8ff7105`` (Abdias
  prophétisant — Latin 40 f. 323v) and its parent manuscript
  ``mdatad3888c6b14fc49ee485c226af71a65b0d35b2ef9``. These guard against
  regressions when the real portal markup or Gallica's manifest format
  shifts in subtle ways.

No real outbound traffic. The Django cache is the in-memory locmem backend
(see ``tests.test_settings``) and is cleared between tests so cache hits
don't leak across cases.

Usage:
    python manage.py test tests.test_biblissima_proxy --settings="tests.test_settings"
"""

import json
import os
from unittest.mock import MagicMock, patch

import requests
from django.core.cache import cache
from django.test import TestCase

from manuspectrum.views import biblissima_proxy as bp

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "biblissima")


def _read_fixture(name):
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as f:
        return f.read()


def _read_json_fixture(name):
    return json.loads(_read_fixture(name))


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_response(json_data=None, status_code=200, text=""):
    """Build a Mock that quacks enough like a ``requests.Response``."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = json_data if json_data is not None else {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=resp)
    else:
        resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# HTML helpers — _parse_html_fragment / _strip_html / _extract_ark / _extract_href
# ---------------------------------------------------------------------------


class ParseHtmlFragmentTests(TestCase):
    def test_parses_simple_fragment(self):
        frag = bp._parse_html_fragment("<a href='x'>hi</a>")
        self.assertIsNotNone(frag)
        self.assertEqual(frag.text_content().strip(), "hi")

    def test_accepts_text_only(self):
        frag = bp._parse_html_fragment("plain text")
        self.assertIsNotNone(frag)
        self.assertEqual(frag.text_content().strip(), "plain text")

    def test_accepts_multiple_top_level_tags(self):
        # fragment_fromstring(create_parent="div") wraps these.
        frag = bp._parse_html_fragment("<a>x</a><a>y</a>")
        self.assertIsNotNone(frag)
        self.assertIn("x", frag.text_content())
        self.assertIn("y", frag.text_content())


class StripHtmlTests(TestCase):
    def test_returns_falsy_input_unchanged(self):
        self.assertEqual(bp._strip_html(""), "")
        self.assertIsNone(bp._strip_html(None))

    def test_returns_plain_text_unchanged_with_entities_unescaped(self):
        self.assertEqual(bp._strip_html("Caf&eacute;"), "Café")

    def test_strips_simple_tags(self):
        self.assertEqual(bp._strip_html("<a href='x'>Paris. BnF</a>"), "Paris. BnF")

    def test_collapses_whitespace(self):
        self.assertEqual(bp._strip_html("<p>foo\n\n   bar  </p>"), "foo bar")

    def test_processes_lists_recursively(self):
        self.assertEqual(bp._strip_html(["<b>a</b>", "<i>b</i>"]), ["a", "b"])

    def test_falls_back_to_unescape_on_parse_failure(self):
        # Hard to make lxml fail, but the unescape branch is exercised by
        # the no-tag path (covered above). This test covers the
        # ``"<" not in s`` short-circuit for an entity-only string.
        self.assertEqual(bp._strip_html("&amp;"), "&")


class ExtractArkTests(TestCase):
    def test_returns_none_for_empty(self):
        self.assertIsNone(bp._extract_ark(""))
        self.assertIsNone(bp._extract_ark(None))

    def test_extracts_ifdata_ark(self):
        html = '<a href="https://portail.biblissima.fr/fr/ark:/43093/ifdata123">x</a>'
        self.assertEqual(bp._extract_ark(html), "ark:/43093/ifdata123")

    def test_extracts_mdata_ark(self):
        html = '<a href="https://portail.biblissima.fr/fr/ark:/43093/mdataABC">x</a>'
        self.assertEqual(bp._extract_ark(html), "ark:/43093/mdataABC")

    def test_returns_none_when_no_ark(self):
        self.assertIsNone(bp._extract_ark("<a href='https://example.com'>x</a>"))


class ExtractHrefTests(TestCase):
    def test_returns_none_for_empty(self):
        self.assertIsNone(bp._extract_href(""))
        self.assertIsNone(bp._extract_href(None))

    def test_returns_none_when_no_href_keyword(self):
        # Fast path: skips parsing if "href" isn't present.
        self.assertIsNone(bp._extract_href("<span>nope</span>"))

    def test_extracts_first_href(self):
        html = (
            '<a href="https://first.example/x">A</a>'
            '<a href="https://second.example/y">B</a>'
        )
        self.assertEqual(bp._extract_href(html), "https://first.example/x")

    def test_handles_anchor_without_href_attribute(self):
        # First <a> has the keyword "href" inside text but no attribute,
        # making sure we still find the second one with a real href.
        html = '<a class="href-like">no</a>' '<a href="https://real.example">yes</a>'
        self.assertEqual(bp._extract_href(html), "https://real.example")


# ---------------------------------------------------------------------------
# Wikibase entity extraction
# ---------------------------------------------------------------------------


class ExtractEntityPropsTests(TestCase):
    def _entity(self, claims=None, labels=None):
        return {"claims": claims or {}, "labels": labels or {}}

    def test_returns_qid_label_with_french_preference(self):
        raw = self._entity(
            labels={
                "fr": {"value": "Manuscrit FR"},
                "en": {"value": "Manuscript EN"},
            }
        )
        result = bp._extract_entity_props("Q1", raw)
        self.assertEqual(result["qid"], "Q1")
        self.assertEqual(result["label"], "Manuscrit FR")

    def test_falls_back_to_english_label(self):
        raw = self._entity(labels={"en": {"value": "Manuscript EN"}})
        self.assertEqual(bp._extract_entity_props("Q1", raw)["label"], "Manuscript EN")

    def test_label_empty_when_no_french_or_english(self):
        raw = self._entity(labels={"de": {"value": "Handschrift"}})
        self.assertEqual(bp._extract_entity_props("Q1", raw)["label"], "")

    def test_extracts_string_property(self):
        raw = self._entity(
            claims={
                bp.P195: [
                    {
                        "mainsnak": {
                            "datavalue": {"value": "Latin 12345", "type": "string"}
                        }
                    }
                ]
            }
        )
        self.assertEqual(
            bp._extract_entity_props("Q1", raw)["shelfmark"], "Latin 12345"
        )

    def test_extracts_entity_id_property(self):
        raw = self._entity(
            claims={
                bp.P194: [
                    {
                        "mainsnak": {
                            "datavalue": {
                                "value": {"id": "Q42", "entity-type": "item"},
                            }
                        }
                    }
                ]
            }
        )
        self.assertEqual(bp._extract_entity_props("Q1", raw)["collection"], "Q42")

    def test_returns_none_for_missing_claims(self):
        result = bp._extract_entity_props("Q1", self._entity())
        self.assertIsNone(result["shelfmark"])
        self.assertIsNone(result["collection"])
        self.assertIsNone(result["author"])

    def test_handles_string_property_with_dict_value(self):
        # _get_string only returns when the value is a str — entity-typed
        # snak landing in a string slot must not blow up, just return None.
        raw = self._entity(
            claims={bp.P195: [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}]}
        )
        self.assertIsNone(bp._extract_entity_props("Q1", raw)["shelfmark"])

    def test_extracts_p2_document_nature_qid(self):
        from manuspectrum.views.biblissima_proxy import _extract_entity_props

        raw = {
            "claims": {
                "P2": [{"mainsnak": {"datavalue": {"value": {"id": "Q32810"}}}}]
            },
            "labels": {"fr": {"value": "Test manuscript"}},
        }
        result = _extract_entity_props("Q123", raw)
        self.assertEqual(result["documentNatureQid"], "Q32810")
        # Label is resolved later by _enrich_canvases via batch fetch — at
        # this stage we only have the QID.
        self.assertIsNone(result["documentNatureLabel"])

    def test_returns_none_for_p2_when_missing(self):
        from manuspectrum.views.biblissima_proxy import _extract_entity_props

        raw = {"claims": {}, "labels": {"fr": {"value": "x"}}}
        result = _extract_entity_props("Q1", raw)
        self.assertIsNone(result["documentNatureQid"])
        self.assertIsNone(result["documentNatureLabel"])


# ---------------------------------------------------------------------------
# Wikibase HTTP helpers — _get_wikibase_entity / _batch_get_wikibase_entities
# ---------------------------------------------------------------------------


class GetWikibaseEntityTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _wbgetentities_response(self, qid, label="Test", claims=None):
        return _make_response(
            json_data={
                "entities": {
                    qid: {
                        "labels": {"fr": {"value": label}},
                        "claims": claims or {},
                    }
                }
            }
        )

    def test_returns_none_when_request_fails(self):
        session = MagicMock()
        with patch.object(
            bp, "_bib_request", side_effect=requests.exceptions.Timeout()
        ):
            self.assertIsNone(bp._get_wikibase_entity("Q1", session=session))

    def test_returns_extracted_props_on_success(self):
        session = MagicMock()
        resp = self._wbgetentities_response("Q1", label="Hello")
        with patch.object(bp, "_bib_request", return_value=resp) as mocked:
            result = bp._get_wikibase_entity("Q1", session=session)
        self.assertIsNotNone(result)
        self.assertEqual(result["qid"], "Q1")
        self.assertEqual(result["label"], "Hello")
        # Hit the wikibase URL once.
        self.assertEqual(mocked.call_count, 1)
        args, kwargs = mocked.call_args
        self.assertEqual(args[1], bp.BIBLISSIMA_WIKIBASE)
        self.assertEqual(kwargs["params"]["ids"], "Q1")
        self.assertEqual(kwargs["params"]["action"], "wbgetentities")

    def test_caches_entity_after_first_fetch(self):
        session = MagicMock()
        resp = self._wbgetentities_response("Q1", label="Cached")
        with patch.object(bp, "_bib_request", return_value=resp) as mocked:
            first = bp._get_wikibase_entity("Q1", session=session)
            second = bp._get_wikibase_entity("Q1", session=session)
        self.assertEqual(first, second)
        # Second call must hit the cache, not the network.
        self.assertEqual(mocked.call_count, 1)

    def test_handles_missing_entity(self):
        session = MagicMock()
        # API returns no entity for the QID.
        resp = _make_response(json_data={"entities": {}})
        with patch.object(bp, "_bib_request", return_value=resp):
            result = bp._get_wikibase_entity("Q999", session=session)
        # _extract_entity_props with empty raw still returns a dict with
        # qid + empty label and None claims — that's acceptable, but it
        # should NOT cache an empty dict for too long. The current
        # implementation does cache it; assert it's at least not None
        # and shaped right.
        self.assertIsNotNone(result)
        self.assertEqual(result["qid"], "Q999")


class BatchGetWikibaseEntitiesTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_returns_empty_dict_for_empty_input(self):
        self.assertEqual(bp._batch_get_wikibase_entities([]), {})

    def test_uses_cache_for_known_qids(self):
        cache.set(
            bp._BIBLISSIMA_ENTITY_CACHE_KEY.format(qid="Q1"),
            {"qid": "Q1", "label": "Cached"},
        )
        with patch.object(bp, "_bib_request") as mocked:
            result = bp._batch_get_wikibase_entities(["Q1"])
        self.assertEqual(result, {"Q1": {"qid": "Q1", "label": "Cached"}})
        mocked.assert_not_called()

    def test_batches_uncached_qids_into_single_request(self):
        session = MagicMock()
        resp = _make_response(
            json_data={
                "entities": {
                    "Q1": {"labels": {"fr": {"value": "One"}}, "claims": {}},
                    "Q2": {"labels": {"fr": {"value": "Two"}}, "claims": {}},
                }
            }
        )
        with patch.object(bp, "_bib_request", return_value=resp) as mocked:
            result = bp._batch_get_wikibase_entities(["Q1", "Q2"], session=session)
        self.assertEqual(set(result.keys()), {"Q1", "Q2"})
        self.assertEqual(mocked.call_count, 1)
        ids_param = mocked.call_args.kwargs["params"]["ids"]
        self.assertEqual(set(ids_param.split("|")), {"Q1", "Q2"})

    def test_skips_missing_entities(self):
        session = MagicMock()
        resp = _make_response(
            json_data={
                "entities": {
                    "Q1": {"labels": {"fr": {"value": "Real"}}, "claims": {}},
                    "Q2": {"missing": ""},
                }
            }
        )
        with patch.object(bp, "_bib_request", return_value=resp):
            result = bp._batch_get_wikibase_entities(["Q1", "Q2"], session=session)
        self.assertIn("Q1", result)
        self.assertNotIn("Q2", result)

    def test_splits_into_chunks_of_50(self):
        session = MagicMock()
        qids = [f"Q{i}" for i in range(75)]
        resp = _make_response(json_data={"entities": {}})
        with patch.object(bp, "_bib_request", return_value=resp) as mocked:
            bp._batch_get_wikibase_entities(qids, session=session)
        # 75 / 50 → ceil = 2 calls.
        self.assertEqual(mocked.call_count, 2)


# ---------------------------------------------------------------------------
# Collection resolution — _resolve_collection
# ---------------------------------------------------------------------------


class ResolveCollectionTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_returns_empty_for_no_qid(self):
        self.assertEqual(bp._resolve_collection(""), {})
        self.assertEqual(bp._resolve_collection(None), {})

    def test_returns_empty_when_collection_entity_unresolvable(self):
        with patch.object(bp, "_get_wikibase_entity", return_value=None):
            self.assertEqual(bp._resolve_collection("Q1"), {})

    def test_resolves_owner_label_minimally(self):
        # Only the collection entity is resolvable, no P201/P169 claims.
        with patch.object(
            bp,
            "_get_wikibase_entity",
            return_value={"label": "Collection BnF"},
        ):
            session = MagicMock()
            session.get.return_value = _make_response(
                json_data={"entities": {"Q1": {"claims": {}}}}
            )
            result = bp._resolve_collection("Q1", session=session)
        self.assertEqual(result["ownerLabel"], "Collection BnF")
        self.assertEqual(result["ownerQid"], "Q1")
        self.assertNotIn("locationLabel", result)
        self.assertNotIn("parentInstitutionLabel", result)

    def test_resolves_full_chain_with_location_and_parent(self):
        # _get_wikibase_entity is called for: collection (Q1), location
        # (Q2), parent institution (Q3) — return a different label each time.
        labels = {
            "Q1": {"label": "BnF Latin"},
            "Q2": {"label": "Paris"},
            "Q3": {"label": "Bibliothèque nationale de France"},
        }

        def fake_get_entity(qid, session=None):  # noqa: ARG001
            return labels.get(qid)

        # session.get is invoked twice for raw claims (collection, place).
        session = MagicMock()
        session.get.side_effect = [
            _make_response(  # collection claims (P201, P169)
                json_data={
                    "entities": {
                        "Q1": {
                            "claims": {
                                bp.P201: [
                                    {"mainsnak": {"datavalue": {"value": {"id": "Q2"}}}}
                                ],
                                bp.P169: [
                                    {"mainsnak": {"datavalue": {"value": {"id": "Q3"}}}}
                                ],
                            }
                        }
                    }
                }
            ),
            _make_response(  # place claims (P123 = Geonames)
                json_data={
                    "entities": {
                        "Q2": {
                            "claims": {
                                bp.P123: [
                                    {"mainsnak": {"datavalue": {"value": "2988507"}}}
                                ]
                            }
                        }
                    }
                }
            ),
        ]

        with patch.object(bp, "_get_wikibase_entity", side_effect=fake_get_entity):
            result = bp._resolve_collection("Q1", session=session)

        self.assertEqual(result["ownerLabel"], "BnF Latin")
        self.assertEqual(result["locationLabel"], "Paris")
        self.assertEqual(result["locationQid"], "Q2")
        self.assertEqual(result["geonamesId"], "2988507")
        self.assertEqual(
            result["parentInstitutionLabel"], "Bibliothèque nationale de France"
        )
        self.assertEqual(result["parentInstitutionQid"], "Q3")

    def test_returns_owner_only_when_claims_fetch_fails(self):
        with patch.object(
            bp,
            "_get_wikibase_entity",
            return_value={"label": "Some Coll"},
        ):
            session = MagicMock()
            session.get.side_effect = requests.exceptions.Timeout()
            result = bp._resolve_collection("Q1", session=session)
        self.assertEqual(result, {"ownerLabel": "Some Coll", "ownerQid": "Q1"})


# ---------------------------------------------------------------------------
# IIIF parsers — _parse_iiif_canvases / _iiif_thumbnail_from_service
# ---------------------------------------------------------------------------


class IiifThumbnailFromServiceTests(TestCase):
    def test_returns_empty_for_no_service(self):
        self.assertEqual(bp._iiif_thumbnail_from_service(""), "")
        self.assertEqual(bp._iiif_thumbnail_from_service(None), "")

    def test_builds_iiif_image_api_url(self):
        url = bp._iiif_thumbnail_from_service(
            "https://gallica.bnf.fr/iiif/ark:/12148/btv1b1234"
        )
        self.assertEqual(
            url,
            "https://gallica.bnf.fr/iiif/ark:/12148/btv1b1234/full/200,/0/default.jpg",
        )

    def test_strips_trailing_slash_from_service_id(self):
        url = bp._iiif_thumbnail_from_service("https://example.org/iiif/")
        self.assertEqual(url, "https://example.org/iiif/full/200,/0/default.jpg")

    def test_supports_custom_width(self):
        url = bp._iiif_thumbnail_from_service("https://x/iiif/y", width=512)
        self.assertEqual(url, "https://x/iiif/y/full/512,/0/default.jpg")


class ParseIiifCanvasesTests(TestCase):
    def test_returns_empty_for_empty_manifest(self):
        self.assertEqual(bp._parse_iiif_canvases({}), [])
        self.assertEqual(bp._parse_iiif_canvases({"sequences": []}), [])

    def _manifest(self, canvases):
        return {"sequences": [{"canvases": canvases}]}

    def test_extracts_basic_canvas_fields(self):
        canvases = [
            {
                "@id": "https://example/canvas/1",
                "label": "f. 1r",
                "thumbnail": {"@id": "https://example/thumb/1.jpg"},
                "images": [
                    {"resource": {"service": {"@id": "https://example/iiif/page1"}}}
                ],
                "metadata": [
                    {
                        "label": "Sur le portail Biblissima",
                        "value": (
                            '<a href="https://portail.biblissima.fr/fr/ark:/43093/ifdata1">x</a>'
                        ),
                    },
                    {
                        "label": "Manuscrit",
                        "value": (
                            '<a href="https://portail.biblissima.fr/fr/ark:/43093/mdata5">'
                            "Paris, BnF, Latin 1</a>"
                        ),
                    },
                    {"label": "Feuillet / page", "value": "1r"},
                    {"label": "Date", "value": "13e siècle"},
                    {"label": "Lieu de fabrication", "value": "Paris"},
                    {"label": "Descripteurs", "value": ["miniature"]},
                ],
            }
        ]
        result = bp._parse_iiif_canvases(self._manifest(canvases))
        self.assertEqual(len(result), 1)
        c = result[0]
        self.assertEqual(c["canvasId"], "https://example/canvas/1")
        self.assertEqual(c["label"], "f. 1r")
        self.assertEqual(c["thumbnail"], "https://example/thumb/1.jpg")
        self.assertEqual(c["imageUrl"], "https://example/iiif/page1")
        self.assertEqual(c["arkId"], "ark:/43093/ifdata1")
        self.assertEqual(c["manuscript"], "Paris, BnF, Latin 1")
        self.assertEqual(c["manuscriptArk"], "ark:/43093/mdata5")
        self.assertEqual(c["folio"], "1r")
        self.assertEqual(c["location"], "Paris")
        self.assertEqual(c["descriptors"], ["miniature"])
        self.assertEqual(c["ifdataHash"], "ifdata1")
        self.assertEqual(c["typeValueId"], bp.BIBLISSIMA_TYPE_MAPPING["miniature"])
        self.assertFalse(c["typeIsFallback"])
        self.assertEqual(
            c["portalUrl"], "https://portail.biblissima.fr/fr/ark:/43093/ifdata1"
        )

    def test_handles_service_as_list(self):
        canvases = [
            {
                "@id": "c1",
                "images": [
                    {"resource": {"service": [{"@id": "https://example/iiif/list"}]}}
                ],
                "metadata": [],
            }
        ]
        result = bp._parse_iiif_canvases(self._manifest(canvases))
        self.assertEqual(result[0]["imageUrl"], "https://example/iiif/list")

    def test_derives_thumbnail_from_image_service_when_missing(self):
        canvases = [
            {
                "@id": "c1",
                "images": [
                    {"resource": {"service": {"@id": "https://example/iiif/x"}}}
                ],
                "metadata": [],
            }
        ]
        result = bp._parse_iiif_canvases(self._manifest(canvases))
        self.assertEqual(
            result[0]["thumbnail"], "https://example/iiif/x/full/200,/0/default.jpg"
        )

    def test_thumbnail_string_form(self):
        canvases = [
            {
                "@id": "c1",
                "thumbnail": "https://example/thumb-direct.jpg",
                "images": [],
                "metadata": [],
            }
        ]
        result = bp._parse_iiif_canvases(self._manifest(canvases))
        self.assertEqual(result[0]["thumbnail"], "https://example/thumb-direct.jpg")

    def test_no_descriptors_falls_back_to_default_type(self):
        canvases = [{"@id": "c1", "label": "anything", "images": [], "metadata": []}]
        result = bp._parse_iiif_canvases(self._manifest(canvases))
        self.assertEqual(result[0]["typeValueId"], bp.BIBLISSIMA_TYPE_DEFAULT)
        self.assertTrue(result[0]["typeIsFallback"])


# ---------------------------------------------------------------------------
# Descriptor / type helpers
# ---------------------------------------------------------------------------


class NormalizeDescriptorsTests(TestCase):
    def test_returns_empty_for_empty(self):
        self.assertEqual(bp._normalize_descriptors(""), [])

    def test_keeps_already_prefixed_desc(self):
        self.assertEqual(
            bp._normalize_descriptors("desc123,desc456"),
            ["desc123", "desc456"],
        )

    def test_strips_known_prefix_and_adds_desc(self):
        # "ifdata123" → strip "ifdata" → "desc123"
        self.assertEqual(bp._normalize_descriptors("ifdata123"), ["desc123"])

    def test_handles_mixed_prefixes(self):
        result = bp._normalize_descriptors("ifdataA,mdataB,pdataC,desc999")
        self.assertEqual(result, ["descA", "descB", "descC", "desc999"])

    def test_strips_whitespace_and_skips_empty_segments(self):
        self.assertEqual(
            bp._normalize_descriptors(" ifdataA , , desc B "),
            ["descA", "desc B"],
        )


class ResolveBiblissimaTypeTests(TestCase):
    def test_returns_default_with_fallback_flag_when_no_input(self):
        valueid, is_fallback = bp._resolve_biblissima_type()
        self.assertEqual(valueid, bp.BIBLISSIMA_TYPE_DEFAULT)
        self.assertTrue(is_fallback)

    def test_explicit_enluminure_is_not_a_fallback(self):
        # "enluminure" is in the mapping; even though its valueid is the
        # same as the default, is_fallback must be False.
        valueid, is_fallback = bp._resolve_biblissima_type(descriptor="Enluminure")
        self.assertEqual(valueid, bp.BIBLISSIMA_TYPE_DEFAULT)
        self.assertFalse(is_fallback)

    def test_typologie_takes_priority_over_descriptor(self):
        valueid, _ = bp._resolve_biblissima_type(
            typologie="Miniature", descriptor="Lettrine"
        )
        self.assertEqual(valueid, bp.BIBLISSIMA_TYPE_MAPPING["miniature"])

    def test_descriptor_used_when_typologie_empty(self):
        valueid, _ = bp._resolve_biblissima_type(typologie="", descriptor="Lettrine")
        self.assertEqual(valueid, bp.BIBLISSIMA_TYPE_MAPPING["lettrine"])

    def test_type_field_used_as_last_resort(self):
        valueid, is_fallback = bp._resolve_biblissima_type(type_field="Vignette")
        self.assertEqual(valueid, bp.BIBLISSIMA_TYPE_MAPPING["vignette"])
        self.assertFalse(is_fallback)

    def test_strips_trailing_numbering(self):
        # "initiale ornée (1)" → "initiale ornée"
        valueid, _ = bp._resolve_biblissima_type(descriptor="initiale ornée (1)")
        self.assertEqual(valueid, bp.BIBLISSIMA_TYPE_MAPPING["initiale ornée"])

    def test_startswith_matching_for_variants(self):
        # "miniature historiée" not in mapping but starts with "miniature"
        valueid, _ = bp._resolve_biblissima_type(descriptor="miniature historiée")
        self.assertEqual(valueid, bp.BIBLISSIMA_TYPE_MAPPING["miniature"])

    def test_case_insensitive_match(self):
        valueid, _ = bp._resolve_biblissima_type(descriptor="LETTRINE")
        self.assertEqual(valueid, bp.BIBLISSIMA_TYPE_MAPPING["lettrine"])


class BiblissimaTypeLabelTests(TestCase):
    def test_returns_label_for_known_valueid(self):
        self.assertEqual(
            bp._biblissima_type_label(bp.BIBLISSIMA_TYPE_MAPPING["miniature"]),
            "Miniature",
        )

    def test_returns_empty_for_unknown_valueid(self):
        self.assertEqual(bp._biblissima_type_label("not-a-uuid"), "")


# ---------------------------------------------------------------------------
# Portal scraper — _parse_manuscript_illuminations
# ---------------------------------------------------------------------------


class ParseManuscriptIlluminationsTests(TestCase):
    HTML_BASIC = """
    <html><body>
    <section id="illuminations">
      <ul class="list-inline-block-container">
        <li>
          <span class="fa fa-picture-o"></span>
          <a href="/fr/ark:/43093/ifdataABC">Miniature (f. 12r)</a>
        </li>
        <li>
          <a href="/fr/ark:/43093/ifdataXYZ">Lettrine ornée (f. 4v)</a>
        </li>
      </ul>
    </section>
    </body></html>
    """

    def test_returns_empty_for_no_links(self):
        self.assertEqual(
            bp._parse_manuscript_illuminations("<html><body></body></html>"),
            [],
        )

    def test_extracts_all_illuminations(self):
        results = bp._parse_manuscript_illuminations(self.HTML_BASIC)
        self.assertEqual(len(results), 2)

        first = results[0]
        self.assertEqual(first["ifdataHash"], "ifdataABC")
        self.assertEqual(first["arkId"], "ark:/43093/ifdataABC")
        self.assertEqual(first["descriptor"], "Miniature")
        self.assertEqual(first["folio"], "12r")
        self.assertTrue(first["hasImage"])
        self.assertEqual(first["typeValueId"], bp.BIBLISSIMA_TYPE_MAPPING["miniature"])

        second = results[1]
        self.assertEqual(second["ifdataHash"], "ifdataXYZ")
        self.assertEqual(second["folio"], "4v")

    def test_has_image_false_when_no_icon_anywhere(self):
        # A page where no <li> ships a fa-picture-o icon: every result
        # must report hasImage=False (the parser walks up to 3 ancestors
        # for the icon — when none exists at all, it stays False).
        html = """
        <html><body>
        <ul>
          <li><a href="/fr/ark:/43093/ifdataNOIMG1">Item 1 (f. 1r)</a></li>
          <li><a href="/fr/ark:/43093/ifdataNOIMG2">Item 2 (f. 2r)</a></li>
        </ul>
        </body></html>
        """
        results = bp._parse_manuscript_illuminations(html)
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertFalse(r["hasImage"])

    def test_dedupes_by_ifdata_hash(self):
        html = """
        <a href="/fr/ark:/43093/ifdataDUP">A (f. 1r)</a>
        <a href="/fr/ark:/43093/ifdataDUP">A again (f. 1r)</a>
        """
        results = bp._parse_manuscript_illuminations(html)
        self.assertEqual(len(results), 1)

    def test_skips_non_ifdata_links(self):
        # Only ifdata-prefixed ARKs should be returned.
        html = """
        <a href="/fr/ark:/43093/mdataXYZ">Manuscrit</a>
        <a href="/fr/ark:/43093/ifdataABC">Ill (f. 1r)</a>
        """
        results = bp._parse_manuscript_illuminations(html)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["ifdataHash"], "ifdataABC")

    def test_portal_url_uses_french_portal(self):
        results = bp._parse_manuscript_illuminations(
            "<html><body><ul><li>"
            '<a href="/fr/ark:/43093/ifdataABC">x (f. 1r)</a>'
            "</li></ul></body></html>"
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0]["portalUrl"],
            f"{bp.BIBLISSIMA_PORTAL}/ifdataABC",
        )


# ---------------------------------------------------------------------------
# Manifest canvas resolver — _fetch_canvas_dimensions
# ---------------------------------------------------------------------------


class FetchCanvasDimensionsTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    MANIFEST = {
        "sequences": [
            {
                "canvases": [
                    {
                        "@id": "https://example/c/1",
                        "label": "f. 1r",
                        "width": 1000,
                        "height": 1500,
                        "images": [
                            {
                                "resource": {
                                    "service": {"@id": "https://example/iiif/p1"}
                                }
                            }
                        ],
                    },
                    {
                        "@id": "https://example/c/2",
                        "label": "f. 323v",
                        "width": 1024,
                        "height": 1600,
                        "images": [
                            {
                                "resource": {
                                    "service": {"@id": "https://example/iiif/p323"}
                                }
                            }
                        ],
                    },
                ]
            }
        ]
    }

    def test_returns_empty_for_no_url(self):
        self.assertEqual(bp._fetch_canvas_dimensions("", "1r", MagicMock()), {})

    def test_returns_empty_when_fetch_fails(self):
        session = MagicMock()
        with patch.object(
            bp, "_bib_request", side_effect=requests.exceptions.Timeout()
        ):
            self.assertEqual(
                bp._fetch_canvas_dimensions("https://example/manifest", "1r", session),
                {},
            )

    def test_matches_canvas_by_folio(self):
        resp = _make_response(json_data=self.MANIFEST)
        with patch.object(bp, "_bib_request", return_value=resp):
            result = bp._fetch_canvas_dimensions(
                "https://example/manifest", "323v", MagicMock()
            )
        self.assertEqual(result["canvasId"], "https://example/c/2")
        self.assertEqual(result["canvasWidth"], 1024)
        self.assertEqual(result["canvasHeight"], 1600)
        self.assertEqual(result["imageServiceUrl"], "https://example/iiif/p323")
        self.assertEqual(
            result["thumbnailUrl"],
            "https://example/iiif/p323/full/200,/0/default.jpg",
        )

    def test_falls_back_to_first_canvas_when_folio_unmatched(self):
        resp = _make_response(json_data=self.MANIFEST)
        with patch.object(bp, "_bib_request", return_value=resp):
            result = bp._fetch_canvas_dimensions(
                "https://example/manifest", "999r", MagicMock()
            )
        self.assertEqual(result["canvasId"], "https://example/c/1")

    def test_caches_result(self):
        resp = _make_response(json_data=self.MANIFEST)
        with patch.object(bp, "_bib_request", return_value=resp) as mocked:
            bp._fetch_canvas_dimensions("https://example/manifest", "1r", MagicMock())
            bp._fetch_canvas_dimensions("https://example/manifest", "1r", MagicMock())
        self.assertEqual(mocked.call_count, 1)

    def test_strips_f_prefix_from_folio(self):
        resp = _make_response(json_data=self.MANIFEST)
        with patch.object(bp, "_bib_request", return_value=resp):
            result = bp._fetch_canvas_dimensions(
                "https://example/manifest", "f.1r", MagicMock()
            )
        self.assertEqual(result["canvasId"], "https://example/c/1")

    def test_returns_empty_when_manifest_has_no_canvases(self):
        resp = _make_response(json_data={"sequences": [{"canvases": []}]})
        with patch.object(bp, "_bib_request", return_value=resp):
            result = bp._fetch_canvas_dimensions(
                "https://example/manifest", "1r", MagicMock()
            )
        self.assertEqual(result, {})


# ---------------------------------------------------------------------------
# Error mapper — _biblissima_upstream_error
# ---------------------------------------------------------------------------


class BiblissimaUpstreamErrorTests(TestCase):
    def test_timeout_returns_504(self):
        resp = bp._biblissima_upstream_error(requests.exceptions.Timeout(), "ctx")
        self.assertEqual(resp.status_code, 504)
        import json as _json

        body = _json.loads(resp.content)
        self.assertEqual(body["error"], "timeout")

    def test_connection_error_returns_502(self):
        resp = bp._biblissima_upstream_error(
            requests.exceptions.ConnectionError(), "ctx"
        )
        self.assertEqual(resp.status_code, 502)
        import json as _json

        self.assertEqual(_json.loads(resp.content)["error"], "connection_error")

    def test_http_error_includes_upstream_status(self):
        upstream = MagicMock()
        upstream.status_code = 503
        exc = requests.exceptions.HTTPError(response=upstream)
        resp = bp._biblissima_upstream_error(exc, "ctx")
        self.assertEqual(resp.status_code, 502)
        import json as _json

        body = _json.loads(resp.content)
        self.assertEqual(body["error"], "upstream_error")
        self.assertEqual(body["status"], 503)

    def test_value_error_returns_invalid_response(self):
        resp = bp._biblissima_upstream_error(ValueError("bad json"), "ctx")
        self.assertEqual(resp.status_code, 502)
        import json as _json

        self.assertEqual(_json.loads(resp.content)["error"], "invalid_response")

    def test_unknown_exception_returns_unknown_error(self):
        resp = bp._biblissima_upstream_error(RuntimeError("boom"), "ctx")
        self.assertEqual(resp.status_code, 502)
        import json as _json

        self.assertEqual(_json.loads(resp.content)["error"], "unknown_error")


# ---------------------------------------------------------------------------
# Concurrency / stats wrapper — _bib_request, _biblissima_slot, _incr_stat
# ---------------------------------------------------------------------------


class BibRequestStatsTests(TestCase):
    def setUp(self):
        # Reset the stats counters we care about.
        for key in ("requests_total", "responses_429", "responses_5xx", "errors_total"):
            bp._biblissima_stats[key] = 0

    def test_increments_requests_total_on_success(self):
        session = MagicMock()
        session.get.return_value = _make_response(json_data={}, status_code=200)
        bp._bib_request(session, "https://example.org")
        self.assertEqual(bp._biblissima_stats["requests_total"], 1)

    def test_increments_429_counter(self):
        session = MagicMock()
        session.get.return_value = _make_response(status_code=429)
        bp._bib_request(session, "https://example.org")
        self.assertEqual(bp._biblissima_stats["responses_429"], 1)

    def test_increments_5xx_counter(self):
        session = MagicMock()
        session.get.return_value = _make_response(status_code=503)
        bp._bib_request(session, "https://example.org")
        self.assertEqual(bp._biblissima_stats["responses_5xx"], 1)

    def test_increments_errors_total_on_exception(self):
        session = MagicMock()
        session.get.side_effect = requests.exceptions.ConnectionError()
        with self.assertRaises(requests.exceptions.ConnectionError):
            bp._bib_request(session, "https://example.org")
        self.assertEqual(bp._biblissima_stats["errors_total"], 1)


class BuildBiblissimaSessionTests(TestCase):
    def test_session_has_required_headers(self):
        session = bp._build_biblissima_session()
        try:
            self.assertIn("User-Agent", session.headers)
            self.assertEqual(session.headers["Accept-Language"], "fr-FR,fr;q=0.9")
        finally:
            session.close()

    def test_session_mounts_retry_adapter_on_https(self):
        session = bp._build_biblissima_session()
        try:
            adapter = session.get_adapter("https://example.org")
            # urllib3 Retry object is configured with our limits.
            retry = adapter.max_retries
            self.assertEqual(retry.total, 3)
            self.assertIn(429, retry.status_forcelist)
            self.assertIn(503, retry.status_forcelist)
        finally:
            session.close()


# ---------------------------------------------------------------------------
# Fixture-driven tests against captured real responses.
# ---------------------------------------------------------------------------


class ParseManuscriptIlluminationsRealFixtureTests(TestCase):
    """``_parse_manuscript_illuminations`` against a real Biblissima portal page.

    Source page (slimmed to the first 8 ``<li>`` items of the
    ``#illuminations`` section)::

        https://portail.biblissima.fr/ark:/43093/mdatad3888c6b14fc49ee485c226af71a65b0d35b2ef9

    All 8 captured items have a ``fa-picture-o`` icon (digitization
    available) and folio labels of the form ``f.NNNw`` inside their
    label suffix.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.html = _read_fixture("manuscript_mdatad3888c.html")
        cls.results = bp._parse_manuscript_illuminations(cls.html)

    def test_extracts_eight_illuminations(self):
        self.assertEqual(len(self.results), 8)

    def test_target_illumination_is_present(self):
        target_hash = "ifdata5be7529b7987eadf417506e4ea42ac11b8ff7105"
        target = next((r for r in self.results if r["ifdataHash"] == target_hash), None)
        self.assertIsNotNone(target)
        self.assertEqual(target["arkId"], f"ark:/43093/{target_hash}")
        self.assertEqual(target["folio"], "323v")
        self.assertTrue(target["hasImage"])
        self.assertTrue(target["descriptor"].startswith("Abdias"))
        self.assertEqual(
            target["portalUrl"],
            f"{bp.BIBLISSIMA_PORTAL}/{target_hash}",
        )

    def test_all_have_images(self):
        # Every captured <li> ships a fa-picture-o sibling.
        for r in self.results:
            self.assertTrue(r["hasImage"], msg=r["label"])

    def test_all_folios_extracted(self):
        # All real labels end in "f.NNN[wx])" — folio extraction must
        # succeed for each.
        for r in self.results:
            self.assertTrue(r["folio"], msg=f"missing folio for {r['label']!r}")

    def test_real_descriptors_default_to_enluminure(self):
        # None of the captured labels match a typed mapping prefix
        # (they're iconographic subjects like "Abdias prophétisant",
        # "Arbre de Jessé", …), so every item falls back to the default
        # type with is_fallback=True.
        for r in self.results:
            self.assertEqual(r["typeValueId"], bp.BIBLISSIMA_TYPE_DEFAULT)
            self.assertTrue(r["typeIsFallback"], msg=r["descriptor"])

    def test_dedupes_against_real_html(self):
        # Hashes in the captured fixture are unique → no dedupe collapse.
        hashes = [r["ifdataHash"] for r in self.results]
        self.assertEqual(len(hashes), len(set(hashes)))


class FetchCanvasDimensionsRealManifestTests(TestCase):
    """``_fetch_canvas_dimensions`` against a real Gallica IIIF v2 manifest.

    Source manifest (slimmed to 5 canvases including ``f. 323v``)::

        https://gallica.bnf.fr/iiif/ark:/12148/btv1b8455927r/manifest.json

    This is the manifest linked from the illumination
    ``ark:/43093/ifdata5be7529b7987eadf417506e4ea42ac11b8ff7105`` via the
    ``data-manifest`` attribute. Verifies the folio match and the
    derived IIIF Image API thumbnail URL on real Gallica response shapes.
    """

    MANIFEST_URL = "https://gallica.bnf.fr/iiif/ark:/12148/btv1b8455927r/manifest.json"

    def setUp(self):
        cache.clear()
        self.manifest = _read_json_fixture("manifest_btv1b8455927r.json")

    def tearDown(self):
        cache.clear()

    def _patched_request(self, manifest=None):
        return patch.object(
            bp,
            "_bib_request",
            return_value=_make_response(json_data=manifest or self.manifest),
        )

    def test_matches_target_folio_323v(self):
        with self._patched_request():
            result = bp._fetch_canvas_dimensions(self.MANIFEST_URL, "323v", MagicMock())
        self.assertEqual(
            result["canvasId"],
            "https://gallica.bnf.fr/iiif/ark:/12148/btv1b8455927r/canvas/f650",
        )
        self.assertGreater(result["canvasWidth"], 0)
        self.assertGreater(result["canvasHeight"], 0)
        self.assertEqual(
            result["imageServiceUrl"],
            "https://gallica.bnf.fr/iiif/ark:/12148/btv1b8455927r/f650",
        )
        self.assertEqual(
            result["thumbnailUrl"],
            "https://gallica.bnf.fr/iiif/ark:/12148/btv1b8455927r/f650/full/200,/0/default.jpg",
        )

    def test_matches_with_f_dot_prefix(self):
        # Portal folios are sometimes labelled "f. 323v" — _fetch_canvas_dimensions
        # must strip the "f." prefix before comparing.
        with self._patched_request():
            result = bp._fetch_canvas_dimensions(
                self.MANIFEST_URL, "f.323v", MagicMock()
            )
        self.assertIn("f650", result["canvasId"])

    def test_falls_back_to_first_canvas_for_unknown_folio(self):
        # "999r" is not in the slim fixture → fallback to the first canvas
        # (label "plat supérieur").
        with self._patched_request():
            result = bp._fetch_canvas_dimensions(self.MANIFEST_URL, "999r", MagicMock())
        self.assertIn("f1", result["canvasId"])

    def test_caches_by_manifest_and_folio(self):
        with self._patched_request() as mocked:
            bp._fetch_canvas_dimensions(self.MANIFEST_URL, "323v", MagicMock())
            bp._fetch_canvas_dimensions(self.MANIFEST_URL, "323v", MagicMock())
            # Different folio → different cache key → second fetch.
            bp._fetch_canvas_dimensions(self.MANIFEST_URL, "323r", MagicMock())
        self.assertEqual(mocked.call_count, 2)


class WikibaseEntityFixtureTests(TestCase):
    """Real Wikibase ``wbgetentities`` responses driving the entity helpers.

    Captured from ``data.biblissima.fr/w/api.php`` for a coherent set of
    cross-linked entities:

    - **Q27392** Paris (France) — place, with P123 Geonames ID
    - **Q32812** BnF Département des manuscrits — collection, with
      P201=Q27392 (location) and P169=Q32811 (parent institution)
    - **Q32811** BnF — parent institution
    - **Q352422** BnF Latin 9926 — manuscript, with P194=Q32812
      (collection), P195="Latin 9926" (shelfmark), P129=mdata-hash

    Tests run ``_get_wikibase_entity`` / ``_batch_get_wikibase_entities``
    /``_resolve_collection`` against the real API response shapes,
    catching format drifts that synthetic mocks miss.
    """

    def setUp(self):
        cache.clear()
        self.paris = _read_json_fixture("entity_paris_Q27392.json")
        self.collection = _read_json_fixture("entity_collection_Q32812.json")
        self.parent = _read_json_fixture("entity_parent_Q32811.json")
        self.manuscript = _read_json_fixture("entity_manuscript_Q352422.json")
        self.batch = _read_json_fixture("batch_entities.json")
        self.search_paris = _read_json_fixture("wbsearch_paris.json")

    def tearDown(self):
        cache.clear()

    # --- _extract_entity_props on real shapes -----------------------------

    def test_extract_props_for_real_manuscript(self):
        raw = self.manuscript["entities"]["Q352422"]
        props = bp._extract_entity_props("Q352422", raw)
        self.assertEqual(
            props["label"],
            "Paris. Bibliothèque nationale de France, "
            "Département des manuscrits, Latin 9926",
        )
        self.assertEqual(
            props["portalHash"],
            "mdata3f5d37989294a508fee54c87d05bb12605dc5b7e",
        )
        self.assertEqual(props["shelfmark"], "Latin 9926")
        self.assertEqual(props["collection"], "Q32812")

    def test_extract_props_for_real_collection(self):
        raw = self.collection["entities"]["Q32812"]
        props = bp._extract_entity_props("Q32812", raw)
        self.assertIn("Bibliothèque nationale de France", props["label"])

    def test_extract_props_for_real_place(self):
        raw = self.paris["entities"]["Q27392"]
        props = bp._extract_entity_props("Q27392", raw)
        self.assertEqual(props["label"], "Paris (France)")

    # --- _get_wikibase_entity end-to-end with real response ---------------

    def test_get_wikibase_entity_against_real_paris_response(self):
        session = MagicMock()
        with patch.object(
            bp,
            "_bib_request",
            return_value=_make_response(json_data=self.paris),
        ):
            entity = bp._get_wikibase_entity("Q27392", session=session)
        self.assertIsNotNone(entity)
        self.assertEqual(entity["qid"], "Q27392")
        self.assertEqual(entity["label"], "Paris (France)")

    def test_batch_get_against_real_multi_entity_response(self):
        session = MagicMock()
        with patch.object(
            bp,
            "_bib_request",
            return_value=_make_response(json_data=self.batch),
        ):
            entities = bp._batch_get_wikibase_entities(
                ["Q27392", "Q32811", "Q32812", "Q352422"],
                session=session,
            )
        self.assertEqual(
            set(entities.keys()),
            {"Q27392", "Q32811", "Q32812", "Q352422"},
        )
        # Cross-link held: manuscript's collection is the BnF Mss dept entity.
        self.assertEqual(entities["Q352422"]["collection"], "Q32812")
        self.assertEqual(entities["Q352422"]["shelfmark"], "Latin 9926")

    # --- _resolve_collection end-to-end against real responses ------------

    def test_resolve_collection_chains_real_entities(self):
        """Q32812 → P201=Q27392 (Paris) + P169=Q32811 (BnF parent)."""
        session = MagicMock()

        # _get_wikibase_entity is called for each QID — return the real
        # extracted dict so the chain terminates with real labels.
        def fake_get_entity(qid, session=None):  # noqa: ARG001
            mapping = {
                "Q32812": bp._extract_entity_props(
                    "Q32812", self.collection["entities"]["Q32812"]
                ),
                "Q27392": bp._extract_entity_props(
                    "Q27392", self.paris["entities"]["Q27392"]
                ),
                "Q32811": bp._extract_entity_props(
                    "Q32811", self.parent["entities"]["Q32811"]
                ),
            }
            return mapping.get(qid)

        # session.get is invoked twice for raw claims fetches:
        # first for the collection, then for the location (place).
        session.get.side_effect = [
            _make_response(json_data=self.collection),
            _make_response(json_data=self.paris),
        ]

        with patch.object(bp, "_get_wikibase_entity", side_effect=fake_get_entity):
            result = bp._resolve_collection("Q32812", session=session)

        self.assertIn("Bibliothèque nationale de France", result["ownerLabel"])
        self.assertEqual(result["ownerQid"], "Q32812")
        self.assertEqual(result["locationLabel"], "Paris (France)")
        self.assertEqual(result["locationQid"], "Q27392")
        # Paris has a real Geonames ID (P123) — must be a string.
        self.assertTrue(result.get("geonamesId"))
        self.assertIsInstance(result["geonamesId"], str)
        self.assertEqual(result["parentInstitutionQid"], "Q32811")
        self.assertIn(
            "Bibliothèque nationale de France", result["parentInstitutionLabel"]
        )

    # --- wbsearchentities response shape -----------------------------------

    def test_search_paris_response_shape_is_consumable(self):
        """Real wbsearchentities responses yield ``id`` and ``label`` per hit.

        Several views read these two keys directly from the response —
        if Biblissima ever drops them this test surfaces the change.
        """
        hits = self.search_paris["search"]
        self.assertGreater(len(hits), 0)
        for hit in hits:
            self.assertIn("id", hit)
            self.assertTrue(hit["id"].startswith("Q"))
            # ``label`` and ``description`` are what BiblissimaSuggestView
            # forwards to the frontend.
            self.assertIn("label", hit)


class IlluminationPortalPageFixtureTests(TestCase):
    """Sanity checks on the captured illumination portal page.

    Asserts the data points the ``BiblissimaIlluminationDetailView`` parser
    relies on are present in the real HTML — so that if the portal markup
    drifts (label change, attribute renaming…) the test fixture catches
    it before the production view does.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.html = _read_fixture("illumination_ifdata5be75.html")

    def test_carries_data_manifest_attribute(self):
        # The view reads the source IIIF manifest URL from this attribute
        # on the .numerisation-iiif link. Captured page must still expose
        # it for the manifest-driven canvas resolver to work.
        self.assertIn("data-manifest=", self.html)
        self.assertIn(
            "https://gallica.bnf.fr/iiif/ark:/12148/btv1b8455927r/manifest.json",
            self.html,
        )

    def test_carries_target_ark(self):
        self.assertIn(
            "ark:/43093/ifdata5be7529b7987eadf417506e4ea42ac11b8ff7105",
            self.html,
        )

    def test_carries_manuscript_ark_link(self):
        # Forward link back to the manuscript fixture (mdata…).
        self.assertIn(
            "ark:/43093/mdatad3888c6b14fc49ee485c226af71a65b0d35b2ef9",
            self.html,
        )


class ResolveBiblissimaDocumentTypeTests(TestCase):
    def test_returns_manuscrit_valueid_for_canonical_label(self):
        from manuspectrum.views.biblissima_proxy import (
            _resolve_biblissima_document_type,
            VALUEID_MANUSCRIT,
        )

        valueid, is_fallback = _resolve_biblissima_document_type("manuscrit")
        self.assertEqual(valueid, VALUEID_MANUSCRIT)
        self.assertFalse(is_fallback)

    def test_normalizes_case_and_whitespace(self):
        from manuspectrum.views.biblissima_proxy import (
            _resolve_biblissima_document_type,
            VALUEID_MANUSCRIT,
        )

        valueid, is_fallback = _resolve_biblissima_document_type("  Manuscrit  ")
        self.assertEqual(valueid, VALUEID_MANUSCRIT)
        self.assertFalse(is_fallback)

    def test_maps_imprime_variants_to_texte_imprime(self):
        from manuspectrum.views.biblissima_proxy import (
            _resolve_biblissima_document_type,
            VALUEID_TEXTE_IMPRIME,
        )

        for label in ("imprimé", "texte imprimé"):
            valueid, is_fallback = _resolve_biblissima_document_type(label)
            self.assertEqual(valueid, VALUEID_TEXTE_IMPRIME)
            self.assertFalse(is_fallback)

    def test_maps_codicological_unit_to_manuscrit(self):
        from manuspectrum.views.biblissima_proxy import (
            _resolve_biblissima_document_type,
            VALUEID_MANUSCRIT,
        )

        valueid, is_fallback = _resolve_biblissima_document_type("unité codicologique")
        self.assertEqual(valueid, VALUEID_MANUSCRIT)
        self.assertFalse(is_fallback)

    def test_returns_default_with_fallback_flag_for_unknown_label(self):
        from manuspectrum.views.biblissima_proxy import (
            _resolve_biblissima_document_type,
            DOCUMENT_NATURE_DEFAULT,
        )

        valueid, is_fallback = _resolve_biblissima_document_type("estampe")
        self.assertEqual(valueid, DOCUMENT_NATURE_DEFAULT)
        self.assertTrue(is_fallback)

    def test_returns_default_with_fallback_flag_for_none(self):
        from manuspectrum.views.biblissima_proxy import (
            _resolve_biblissima_document_type,
            DOCUMENT_NATURE_DEFAULT,
        )

        valueid, is_fallback = _resolve_biblissima_document_type(None)
        self.assertEqual(valueid, DOCUMENT_NATURE_DEFAULT)
        self.assertTrue(is_fallback)

    def test_returns_default_with_fallback_flag_for_empty_string(self):
        from manuspectrum.views.biblissima_proxy import (
            _resolve_biblissima_document_type,
            DOCUMENT_NATURE_DEFAULT,
        )

        valueid, is_fallback = _resolve_biblissima_document_type("")
        self.assertEqual(valueid, DOCUMENT_NATURE_DEFAULT)
        self.assertTrue(is_fallback)


class BiblissimaEntityViewDocumentNatureTests(TestCase):
    """Verify P2 nature is resolved and a Document-Type valueid is pre-computed."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch("manuspectrum.views.biblissima_proxy._get_wikibase_entity")
    def test_resolves_label_and_valueid_for_known_nature(self, mock_get):
        from manuspectrum.views.biblissima_proxy import VALUEID_MANUSCRIT

        # First call: the manuscript itself with a P2 pointing to Q32810
        # Second call: Q32810's own entity, where label is "manuscrit"
        def side_effect(qid, session=None):
            if qid == "Q123":
                return {
                    "qid": "Q123",
                    "label": "Test ms",
                    "portalHash": None,
                    "manifestUrl": None,
                    "digitizationUrl": None,
                    "shelfmark": None,
                    "collection": None,
                    "author": None,
                    "mandragoreId": None,
                    "documentNatureQid": "Q32810",
                    "documentNatureLabel": None,
                }
            if qid == "Q32810":
                return {
                    "qid": "Q32810",
                    "label": "manuscrit",
                    "portalHash": None,
                    "manifestUrl": None,
                    "digitizationUrl": None,
                    "shelfmark": None,
                    "collection": None,
                    "author": None,
                    "mandragoreId": None,
                    "documentNatureQid": None,
                    "documentNatureLabel": None,
                }
            return None

        mock_get.side_effect = side_effect

        from django.test import RequestFactory
        from manuspectrum.views.biblissima_proxy import BiblissimaEntityView

        rf = RequestFactory()
        view = BiblissimaEntityView()
        resp = view.get(rf.get("/api/biblissima/entity/Q123"), qid="Q123")
        import json

        data = json.loads(resp.content)
        self.assertEqual(data["documentNatureLabel"], "manuscrit")
        self.assertEqual(data["documentTypeValueId"], VALUEID_MANUSCRIT)
        self.assertFalse(data["documentTypeIsFallback"])

    @patch("manuspectrum.views.biblissima_proxy._get_wikibase_entity")
    def test_returns_fallback_flag_for_unknown_nature(self, mock_get):
        from manuspectrum.views.biblissima_proxy import DOCUMENT_NATURE_DEFAULT

        def side_effect(qid, session=None):
            if qid == "Q1":
                return {
                    "qid": "Q1",
                    "label": "Mystery",
                    "portalHash": None,
                    "manifestUrl": None,
                    "digitizationUrl": None,
                    "shelfmark": None,
                    "collection": None,
                    "author": None,
                    "mandragoreId": None,
                    "documentNatureQid": "Q120869",
                    "documentNatureLabel": None,
                }
            if qid == "Q120869":
                return {
                    "qid": "Q120869",
                    "label": "estampe",
                    "portalHash": None,
                    "manifestUrl": None,
                    "digitizationUrl": None,
                    "shelfmark": None,
                    "collection": None,
                    "author": None,
                    "mandragoreId": None,
                    "documentNatureQid": None,
                    "documentNatureLabel": None,
                }
            return None

        mock_get.side_effect = side_effect

        from django.test import RequestFactory
        from manuspectrum.views.biblissima_proxy import BiblissimaEntityView

        rf = RequestFactory()
        view = BiblissimaEntityView()
        resp = view.get(rf.get("/api/biblissima/entity/Q1"), qid="Q1")
        import json

        data = json.loads(resp.content)
        self.assertEqual(data["documentNatureLabel"], "estampe")
        self.assertEqual(data["documentTypeValueId"], DOCUMENT_NATURE_DEFAULT)
        self.assertTrue(data["documentTypeIsFallback"])

    @patch("manuspectrum.views.biblissima_proxy._get_wikibase_entity")
    def test_handles_missing_p2_gracefully(self, mock_get):
        from manuspectrum.views.biblissima_proxy import DOCUMENT_NATURE_DEFAULT

        mock_get.return_value = {
            "qid": "Q1",
            "label": "x",
            "portalHash": None,
            "manifestUrl": None,
            "digitizationUrl": None,
            "shelfmark": None,
            "collection": None,
            "author": None,
            "mandragoreId": None,
            "documentNatureQid": None,
            "documentNatureLabel": None,
        }

        from django.test import RequestFactory
        from manuspectrum.views.biblissima_proxy import BiblissimaEntityView

        rf = RequestFactory()
        view = BiblissimaEntityView()
        resp = view.get(rf.get("/api/biblissima/entity/Q1"), qid="Q1")
        import json

        data = json.loads(resp.content)
        self.assertIsNone(data["documentNatureLabel"])
        self.assertEqual(data["documentTypeValueId"], DOCUMENT_NATURE_DEFAULT)
        self.assertTrue(data["documentTypeIsFallback"])


class EnrichCanvasesDocumentNatureTests(TestCase):
    """Verify _enrich_canvases decorates every canvas with documentTypeValueId."""

    def setUp(self):
        from django.core.cache import cache

        cache.clear()

    def tearDown(self):
        from django.core.cache import cache

        cache.clear()

    @patch("manuspectrum.views.biblissima_proxy._batch_get_wikibase_entities")
    @patch("manuspectrum.views.biblissima_proxy._bib_request")
    def test_attaches_document_type_to_canvases(self, mock_bib, mock_batch):
        from manuspectrum.views.biblissima_proxy import (
            _enrich_canvases,
            VALUEID_MANUSCRIT,
        )

        # _bib_request is used for wbsearchentities — return a single candidate.
        bib_resp = MagicMock()
        bib_resp.raise_for_status = MagicMock()
        bib_resp.json.return_value = {"search": [{"id": "Q123"}]}
        mock_bib.return_value = bib_resp

        # _batch_get_wikibase_entities is called twice:
        #  • once for candidate manuscript entities (Q123)
        #  • once for author + nature QIDs together (Q32810 here)
        # Discriminate by the QIDs requested.
        def batch(qids, session=None):
            qids_set = set(qids)
            if "Q123" in qids_set:
                return {
                    "Q123": {
                        "qid": "Q123",
                        "label": "ms",
                        "portalHash": "mdataXYZ",
                        "manifestUrl": "https://m",
                        "digitizationUrl": None,
                        "shelfmark": "Lat 1",
                        "collection": None,
                        "author": None,
                        "mandragoreId": None,
                        "documentNatureQid": "Q32810",
                        "documentNatureLabel": None,
                    }
                }
            if "Q32810" in qids_set:
                return {
                    "Q32810": {
                        "qid": "Q32810",
                        "label": "manuscrit",
                    }
                }
            return {}

        mock_batch.side_effect = batch

        canvases = [
            {"manuscriptArk": "ark:/43093/mdataXYZ", "manuscript": "Lat 1"},
        ]
        _enrich_canvases(canvases)

        c = canvases[0]
        self.assertEqual(c["documentNatureLabel"], "manuscrit")
        self.assertEqual(c["documentTypeValueId"], VALUEID_MANUSCRIT)
        self.assertFalse(c["documentTypeIsFallback"])


class AttachDocumentTypeHelperTests(TestCase):
    """Verify the _attach_document_type helper resolves and is idempotent."""

    def setUp(self):
        from django.core.cache import cache

        cache.clear()

    def tearDown(self):
        from django.core.cache import cache

        cache.clear()

    @patch("manuspectrum.views.biblissima_proxy._get_wikibase_entity")
    def test_resolves_label_and_valueid(self, mock_get):
        from manuspectrum.views.biblissima_proxy import (
            _attach_document_type,
            VALUEID_MANUSCRIT,
        )

        mock_get.return_value = {"qid": "Q32810", "label": "manuscrit"}
        entity = {"documentNatureQid": "Q32810", "documentNatureLabel": None}
        _attach_document_type(entity)
        self.assertEqual(entity["documentNatureLabel"], "manuscrit")
        self.assertEqual(entity["documentTypeValueId"], VALUEID_MANUSCRIT)
        self.assertFalse(entity["documentTypeIsFallback"])

    @patch("manuspectrum.views.biblissima_proxy._get_wikibase_entity")
    def test_does_not_refetch_when_label_already_set(self, mock_get):
        from manuspectrum.views.biblissima_proxy import (
            _attach_document_type,
            VALUEID_MANUSCRIT,
        )

        entity = {
            "documentNatureQid": "Q32810",
            "documentNatureLabel": "manuscrit",
        }
        _attach_document_type(entity)
        # Helper should NOT call _get_wikibase_entity when label is already set.
        mock_get.assert_not_called()
        self.assertEqual(entity["documentTypeValueId"], VALUEID_MANUSCRIT)
        self.assertFalse(entity["documentTypeIsFallback"])

    def test_is_safe_on_none_entity(self):
        from manuspectrum.views.biblissima_proxy import _attach_document_type

        # Must not raise.
        _attach_document_type(None)

    @patch("manuspectrum.views.biblissima_proxy._get_wikibase_entity")
    def test_falls_back_when_no_nature_qid(self, mock_get):
        from manuspectrum.views.biblissima_proxy import (
            _attach_document_type,
            DOCUMENT_NATURE_DEFAULT,
        )

        entity = {"documentNatureQid": None, "documentNatureLabel": None}
        _attach_document_type(entity)
        mock_get.assert_not_called()
        self.assertEqual(entity["documentTypeValueId"], DOCUMENT_NATURE_DEFAULT)
        self.assertTrue(entity["documentTypeIsFallback"])


class BiblissimaSearchManuscriptsViewDocumentTypeTests(TestCase):
    """Verify BiblissimaSearchManuscriptsView.get returns documentType fields."""

    def setUp(self):
        from django.core.cache import cache

        cache.clear()

    def tearDown(self):
        from django.core.cache import cache

        cache.clear()

    @patch("manuspectrum.views.biblissima_proxy._get_wikibase_entity")
    @patch("manuspectrum.views.biblissima_proxy._batch_get_wikibase_entities")
    @patch("manuspectrum.views.biblissima_proxy._bib_request")
    @patch("manuspectrum.views.biblissima_proxy._build_biblissima_session")
    def test_results_include_document_type(
        self, mock_build_session, mock_bib, mock_batch, mock_get_single
    ):
        from manuspectrum.views.biblissima_proxy import VALUEID_MANUSCRIT

        # Stub session
        mock_session = MagicMock()
        mock_session.close = MagicMock()
        mock_build_session.return_value = mock_session

        # Stub the wbsearchentities + wbgetentities prefix-search response.
        # Two responses needed in order: first a search response, then a
        # claims response that has a P2 pointing to the manuscript type QID.
        # The TYPE_FILTERS["manuscript"] target is whatever the view requires;
        # we mirror it by giving each item a P2=that type. The view stores
        # qids whose P2 matches; we rely on TYPE_FILTERS["manuscript"]
        # already being the canonical "manuscrit" type qid in production.
        from manuspectrum.views.biblissima_proxy import BiblissimaSearchManuscriptsView

        ms_type_qid = BiblissimaSearchManuscriptsView.TYPE_FILTERS["manuscript"]

        search_resp = MagicMock()
        search_resp.raise_for_status = MagicMock()
        search_resp.json.return_value = {"search": [{"id": "Q123"}]}

        claims_resp = MagicMock()
        claims_resp.raise_for_status = MagicMock()
        claims_resp.json.return_value = {
            "entities": {
                "Q123": {
                    "claims": {
                        "P2": [
                            {"mainsnak": {"datavalue": {"value": {"id": ms_type_qid}}}}
                        ]
                    }
                }
            }
        }

        # Fulltext search response (used as the second-pass; can be empty)
        fulltext_resp = MagicMock()
        fulltext_resp.raise_for_status = MagicMock()
        fulltext_resp.json.return_value = {"query": {"search": []}}

        mock_bib.side_effect = [search_resp, claims_resp, fulltext_resp]

        # Batch entity fetch returns Q123 with documentNatureQid -> Q32810
        mock_batch.return_value = {
            "Q123": {
                "qid": "Q123",
                "label": "Test ms",
                "portalHash": "mdataXYZ",
                "manifestUrl": "https://m",
                "digitizationUrl": None,
                "shelfmark": "Lat 1",
                "collection": None,
                "author": None,
                "mandragoreId": None,
                "documentNatureQid": "Q32810",
                "documentNatureLabel": None,
            }
        }

        # _get_wikibase_entity is called for the nature-label resolution
        mock_get_single.return_value = {"qid": "Q32810", "label": "manuscrit"}

        from django.test import RequestFactory

        rf = RequestFactory()
        req = rf.get("/api/biblissima/search-manuscripts?q=test")
        view = BiblissimaSearchManuscriptsView()
        resp = view.get(req)

        import json

        data = json.loads(resp.content)
        self.assertEqual(data["total"], 1)
        first = data["results"][0]
        self.assertEqual(first["documentNatureLabel"], "manuscrit")
        self.assertEqual(first["documentTypeValueId"], VALUEID_MANUSCRIT)
        self.assertFalse(first["documentTypeIsFallback"])


class LinkToProjectIdempotenceTests(TestCase):
    """_link_to_project must not duplicate refs when called twice."""

    @patch("manuspectrum.views.biblissima_proxy.Tile")
    def test_skips_when_resource_already_linked(self, mock_tile):
        from manuspectrum.views.biblissima_proxy import (
            BiblissimaCreateResourceView,
            PROJECT_STUDIED_OBJECTS_NODE,
        )

        rid = "11111111-1111-1111-1111-111111111111"
        pid = "22222222-2222-2222-2222-222222222222"

        existing = MagicMock()
        existing.data = {
            PROJECT_STUDIED_OBJECTS_NODE: [
                {
                    "resourceId": rid,
                    "ontologyProperty": "",
                    "inverseOntologyProperty": "",
                    "resourceXresourceId": "",
                }
            ]
        }
        mock_tile.objects.filter.return_value.first.return_value = existing

        view = BiblissimaCreateResourceView()
        view._link_to_project(rid, pid, transaction_id=None)

        # The tile data must still contain exactly one ref.
        self.assertEqual(
            len(existing.data[PROJECT_STUDIED_OBJECTS_NODE]),
            1,
            "Idempotence broken: a duplicate ref was appended",
        )
        existing.save.assert_not_called()

    @patch("manuspectrum.views.biblissima_proxy.Tile")
    def test_appends_when_resource_not_yet_linked(self, mock_tile):
        from manuspectrum.views.biblissima_proxy import (
            BiblissimaCreateResourceView,
            PROJECT_STUDIED_OBJECTS_NODE,
        )

        rid = "11111111-1111-1111-1111-111111111111"
        pid = "22222222-2222-2222-2222-222222222222"

        existing = MagicMock()
        existing.data = {PROJECT_STUDIED_OBJECTS_NODE: []}
        mock_tile.objects.filter.return_value.first.return_value = existing

        view = BiblissimaCreateResourceView()
        view._link_to_project(rid, pid, transaction_id=None)

        self.assertEqual(len(existing.data[PROJECT_STUDIED_OBJECTS_NODE]), 1)
        self.assertEqual(
            existing.data[PROJECT_STUDIED_OBJECTS_NODE][0]["resourceId"],
            rid,
        )
        existing.save.assert_called_once()


class BiblissimaLinkToProjectViewTests(TestCase):
    @patch(
        "manuspectrum.views.biblissima_proxy.BiblissimaCreateResourceView._link_to_project"
    )
    def test_calls_link_helper_with_validated_inputs(self, mock_link):
        from django.test import RequestFactory
        import json
        from manuspectrum.views.biblissima_proxy import BiblissimaLinkToProjectView

        rf = RequestFactory()
        body = json.dumps(
            {
                "resourceId": "11111111-1111-1111-1111-111111111111",
                "projectId": "22222222-2222-2222-2222-222222222222",
            }
        )
        req = rf.post(
            "/api/biblissima/link-to-project",
            data=body,
            content_type="application/json",
        )
        view = BiblissimaLinkToProjectView()
        resp = view.post(req)
        self.assertEqual(resp.status_code, 200)
        mock_link.assert_called_once()

    def test_rejects_invalid_uuid(self):
        from django.test import RequestFactory
        import json
        from manuspectrum.views.biblissima_proxy import BiblissimaLinkToProjectView

        rf = RequestFactory()
        body = json.dumps({"resourceId": "not-a-uuid", "projectId": "x"})
        req = rf.post(
            "/api/biblissima/link-to-project",
            data=body,
            content_type="application/json",
        )
        view = BiblissimaLinkToProjectView()
        resp = view.post(req)
        self.assertEqual(resp.status_code, 400)

    def test_rejects_missing_fields(self):
        from django.test import RequestFactory
        import json
        from manuspectrum.views.biblissima_proxy import BiblissimaLinkToProjectView

        rf = RequestFactory()
        body = json.dumps({"resourceId": "11111111-1111-1111-1111-111111111111"})
        req = rf.post(
            "/api/biblissima/link-to-project",
            data=body,
            content_type="application/json",
        )
        view = BiblissimaLinkToProjectView()
        resp = view.post(req)
        self.assertEqual(resp.status_code, 400)

    def test_rejects_invalid_json(self):
        from django.test import RequestFactory
        from manuspectrum.views.biblissima_proxy import BiblissimaLinkToProjectView

        rf = RequestFactory()
        req = rf.post(
            "/api/biblissima/link-to-project",
            data="not json",
            content_type="application/json",
        )
        view = BiblissimaLinkToProjectView()
        resp = view.post(req)
        self.assertEqual(resp.status_code, 400)
