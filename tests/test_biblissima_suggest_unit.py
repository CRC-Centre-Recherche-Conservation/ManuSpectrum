"""The Biblissima suggest endpoint: budget, memo and prefix reuse.

Upstream is ``FakeWikibase``, a stand-in for ``_bib_request`` that answers the
suggest calls from a small corpus with the matching rules of Wikibase listed
in its docstring. No live call, no database.

Run:
    /home/rayondemiel/venv/bin/python manage.py test \\
        tests.test_biblissima_suggest_unit --settings="tests.test_settings" --noinput
"""

import json
import re
import threading
import time
import unicodedata
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qsl, urlsplit

import requests
from django.core.cache import cache
from django.test import RequestFactory, TestCase

from manuspectrum.views import biblissima_proxy as bp

DESCRIPTOR = "Q304387"
MANUSCRIPT = "Q32810"


def _wikibase_fold(text):
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def entity(label, *, types=(DESCRIPTOR,), aliases=None, lang="fr", p129=None):
    return {
        "labels": {lang: label},
        "aliases": aliases or {},
        "types": list(types),
        "p129": p129,
    }


class FakeWikibase:
    """Answers ``_bib_request`` from ``corpus`` (id → ``entity()``).

    ``wbsearchentities``: an entity id typed in full matches that entity
    exactly; otherwise the entities one of whose labels or aliases starts with
    the search (case and accents ignored), ranked exact match, then label
    match, then alias match, then corpus order; ``search-continue`` past
    ``limit``. ``query``: the entities whose labels hold every word of the text
    as a whole word. ``slow`` maps an action to seconds slept before
    answering; ``errors`` maps an action to a MediaWiki error code.
    """

    def __init__(self, corpus, *, slow=None, errors=None):
        self.corpus = corpus
        self.slow = slow or {}
        self.errors = errors or {}
        self.calls = []
        self.sessions = []
        self.kwargs = []
        self.lock = threading.Lock()

    def __call__(self, session, url, **kwargs):
        params = dict(parse_qsl(urlsplit(url).query))
        with self.lock:
            self.calls.append(params)
            self.sessions.append(session)
            self.kwargs.append(kwargs)
        action = params["action"]
        time.sleep(self.slow.get(action, 0))
        if action in self.errors:
            payload = {"error": {"code": self.errors[action]}}
        elif action == "wbsearchentities":
            payload = self._search(params)
        elif action == "wbgetentities":
            payload = self._entities(params)
        else:
            payload = self._fulltext(params)
        response = MagicMock()
        response.json.return_value = payload
        response.raise_for_status.return_value = None
        return response

    def actions(self):
        return [call["action"] for call in self.calls]

    def searches(self):
        return [c["search"] for c in self.calls if c["action"] == "wbsearchentities"]

    @staticmethod
    def _label(record, lang):
        return record["labels"].get(lang) or next(iter(record["labels"].values()))

    def _search(self, params):
        needle = _wikibase_fold(params["search"])
        typed_id = params["search"].strip().upper()
        ranked = []
        for position, (qid, record) in enumerate(self.corpus.items()):
            labels = [_wikibase_fold(t) for t in record["labels"].values()]
            aliases = [_wikibase_fold(t) for v in record["aliases"].values() for t in v]
            if qid == typed_id or needle in labels + aliases:
                rank = 0
            elif any(t.startswith(needle) for t in labels):
                rank = 1
            elif any(t.startswith(needle) for t in aliases):
                rank = 2
            else:
                continue
            hit = {"id": qid, "label": self._label(record, params["language"])}
            ranked.append((rank, position, hit))
        hits = [hit for _, _, hit in sorted(ranked, key=lambda row: row[:2])]
        limit = int(params["limit"])
        payload = {"search": hits[:limit]}
        if len(hits) > limit:
            payload["search-continue"] = limit
        return payload

    def _entities(self, params):
        wanted = params["languages"].split("|") if "languages" in params else None
        props = params["props"].split("|")
        out = {}
        for qid in params["ids"].split("|"):
            record = self.corpus[qid]
            item = {}
            if "labels" in props:
                item["labels"] = {
                    code: {"language": code, "value": value}
                    for code, value in record["labels"].items()
                    if wanted is None or code in wanted
                }
            if "aliases" in props:
                item["aliases"] = {
                    code: [{"language": code, "value": v} for v in values]
                    for code, values in record["aliases"].items()
                    if wanted is None or code in wanted
                }
            if "descriptions" in props:
                item["descriptions"] = {}
            if "claims" in props:
                claims = {
                    "P2": [
                        {"mainsnak": {"datavalue": {"value": {"id": t}}}}
                        for t in record["types"]
                    ]
                }
                if record["p129"]:
                    claims["P129"] = [
                        {"mainsnak": {"datavalue": {"value": record["p129"]}}}
                    ]
                item["claims"] = claims
            out[qid] = item
        return {"entities": out}

    def _fulltext(self, params):
        text, _, statement = params["srsearch"].partition(" haswbstatement:P2=")
        words = re.findall(r"\w+", _wikibase_fold(text))
        hits = []
        for qid, record in self.corpus.items():
            if statement and statement not in record["types"]:
                continue
            label_words = set(
                re.findall(r"\w+", _wikibase_fold(" ".join(record["labels"].values())))
            )
            if words and all(word in label_words for word in words):
                hits.append({"title": f"Item:{qid}"})
        return {"query": {"search": hits[: int(params["srlimit"])]}}


class SuggestTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.factory = RequestFactory()
        self.start(patch.object(bp.logger, "warning"))

    def start(self, patcher):
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def upstream(self, corpus, **kwargs):
        fake = FakeWikibase(corpus, **kwargs)
        self.start(patch.object(bp, "_bib_request", side_effect=fake))
        return fake

    def suggest(self, **params):
        request = self.factory.get("/api/biblissima/suggest", params)
        response = bp.BiblissimaSuggestView().get(request)
        return response, json.loads(response.content)


DRAGONS = {
    "Q1": entity("dragon"),
    "Q2": entity("Draguignan (Var)", types=("Q168",)),
    "Q3": entity("dragée", aliases={"en": ["sugared almond"]}),
}


class SuggestBudgetTests(SuggestTestCase):
    def test_no_upstream_call_is_made_once_the_budget_is_spent(self):
        fake = self.upstream(DRAGONS)
        self.start(patch.object(bp, "SUGGEST_DEADLINE", 0))

        response, payload = self.suggest(q="drag", type="descriptor")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake.calls, [])
        self.assertEqual(payload["results"], [])
        self.assertTrue(payload["degraded"])
        self.assertTrue(payload["partial"])

    def test_the_results_in_hand_survive_a_spent_budget(self):
        fake = self.upstream(DRAGONS, slow={"wbgetentities": 0.3})
        self.start(patch.object(bp, "SUGGEST_DEADLINE", 0.2))

        _, payload = self.suggest(q="drag", type="descriptor")

        self.assertEqual([r["id"] for r in payload["results"]], ["Q1", "Q3"])
        self.assertFalse(payload["degraded"])
        self.assertTrue(payload["partial"])
        self.assertEqual(fake.actions(), ["wbsearchentities", "wbgetentities"])

    def test_the_suggest_path_never_retries(self):
        fake = self.upstream(DRAGONS)

        self.suggest(q="drag", type="descriptor")

        self.assertTrue(fake.sessions)
        for session in fake.sessions:
            self.assertIs(session, bp._get_besteffort_session())
            self.assertEqual(session.get_adapter("https://x/").max_retries.total, 0)

    def test_every_call_goes_through_the_guarded_fetch_within_the_budget(self):
        fake = self.upstream(DRAGONS)
        self.start(patch.object(bp, "SUGGEST_DEADLINE", 2.0))

        started = time.monotonic()
        self.suggest(q="drag", type="descriptor")
        finished = time.monotonic()

        self.assertTrue(fake.kwargs)
        for kwargs in fake.kwargs:
            self.assertIs(kwargs["guarded"], True)
            self.assertTrue(0 < kwargs["slot_timeout"] <= 2.0)
            self.assertTrue(started + 2.0 <= kwargs["deadline"] <= finished + 2.0)

    def test_a_saturated_semaphore_costs_no_more_than_the_budget(self):
        semaphore = threading.BoundedSemaphore(1)
        semaphore.acquire()
        self.start(patch.object(bp, "_biblissima_semaphore", semaphore))
        self.start(patch.dict(bp._biblissima_stats))
        self.start(patch.object(bp, "SUGGEST_DEADLINE", 0.3))

        started = time.monotonic()
        _, payload = self.suggest(q="drag", type="descriptor")

        self.assertLess(time.monotonic() - started, 2.0)
        self.assertTrue(payload["degraded"])

    def test_an_error_answer_is_a_failed_branch(self):
        self.upstream(DRAGONS, errors={"wbsearchentities": "badvalue"})

        _, payload = self.suggest(q="drag", type="descriptor")

        self.assertTrue(payload["partial"])
        self.assertEqual(payload["results"], [])

    def test_a_read_timeout_is_a_failed_branch(self):
        self.start(
            patch.object(
                bp,
                "_bib_request",
                side_effect=requests.exceptions.ConnectionError("Read timed out."),
            )
        )

        response, payload = self.suggest(q="drag", type="descriptor")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["degraded"])


SAINTS = {
    f"Q{100 + i}": entity(f"Saint {name}")
    for i, name in enumerate(
        [
            "Agnès",
            "Ambroise",
            "André",
            "Antoine",
            "Augustin",
            "Barbe",
            "Benoît",
            "Bernard",
            "Blaise",
            "Catherine",
            "Cécile",
            "Christophe",
            "Claire",
            "Denis",
            "Dominique",
            "Étienne",
            "Eustache",
            "François",
            "Georges",
            "Grégoire",
            "Hilaire",
            "Hubert",
            "Ignace",
            "Isidore",
            "Jacques",
            "Jean",
            "Joseph",
            "Julien",
            "Laurent",
            "Léger",
            "Louis",
            "Luc",
            "Marc",
            "Marguerite",
            "Marie-Madeleine",
            "Martin",
            "Matthieu",
            "Maurice",
            "Michel",
            "Nicolas",
            "Paul",
            "Pierre",
            "Rémi",
            "Roch",
            "Sébastien",
            "Simon",
            "Thomas",
            "Urbain",
            "Valentin",
            "Vincent",
            "Yves",
        ]
    )
}
SAINTS["Q8844"] = entity(
    "Jérôme (saint, 0345?-0420)",
    types=("Q168", DESCRIPTOR),
    aliases={"fr": ["saint Jérôme", "Sainc Hiérome"], "la": ["Hieronymus"]},
)


def _by_id(payload):
    return {result["id"]: result for result in payload["results"]}


class SuggestMemoTests(SuggestTestCase):
    def test_an_identical_query_is_answered_from_the_memo(self):
        fake = self.upstream(DRAGONS)
        self.suggest(q="drag", type="descriptor")
        calls = len(fake.calls)

        self.suggest(q="drag", type="descriptor")

        self.assertEqual(len(fake.calls), calls)

    def test_case_accents_and_spaces_share_one_answer(self):
        fake = self.upstream(DRAGONS)
        self.suggest(q="  Dragée  ", type="descriptor")
        calls = len(fake.calls)

        self.suggest(q="dragee", type="descriptor")

        self.assertEqual(len(fake.calls), calls)

    def test_the_upstream_receives_the_folded_query(self):
        fake = self.upstream(SAINTS)

        self.suggest(q="Saint  Jéro", type="descriptor")

        self.assertEqual(fake.searches(), ["saint jero"])

    def test_a_partial_answer_expires_quickly(self):
        self.upstream(DRAGONS, errors={"query": "internal"})
        setter = self.start(patch.object(bp.cache, "set", wraps=bp.cache.set))

        _, payload = self.suggest(q="dragon", type="descriptor")

        self.assertTrue(payload["partial"])
        key = bp._suggest_key("dragon", DESCRIPTOR, "fr", 10)
        timeouts = [c.args[2] for c in setter.call_args_list if c.args[0] == key]
        self.assertEqual(timeouts[-1], bp.SUGGEST_PARTIAL_TTL)

    def test_a_complete_answer_is_kept_half_an_hour(self):
        self.upstream(DRAGONS)
        setter = self.start(patch.object(bp.cache, "set", wraps=bp.cache.set))

        self.suggest(q="dragon", type="descriptor")

        key = bp._suggest_key("dragon", DESCRIPTOR, "fr", 10)
        timeouts = [c.args[2] for c in setter.call_args_list if c.args[0] == key]
        self.assertEqual(timeouts, [bp.SUGGEST_ANSWER_TTL])

    def test_the_browser_keeps_only_complete_answers(self):
        self.upstream(DRAGONS, errors={"query": "internal"})
        partial, _ = self.suggest(q="dragon", type="descriptor")
        self.assertIn("max-age=0", partial["Cache-Control"])

        cache.clear()
        self.upstream(DRAGONS)
        complete, _ = self.suggest(q="dragon", type="descriptor")
        self.assertIn(f"max-age={bp.SUGGEST_ANSWER_TTL}", complete["Cache-Control"])
        self.assertIn("private", complete["Cache-Control"])

    def test_an_unknown_lang_falls_back_to_french(self):
        fake = self.upstream(DRAGONS)

        self.suggest(q="drag", type="descriptor", lang="xx")

        self.assertEqual(fake.calls[0]["language"], "fr")

    def test_an_overlong_query_is_refused(self):
        fake = self.upstream(DRAGONS)

        response, payload = self.suggest(q="a" * 101, type="descriptor")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload, {"error": "query too long"})
        self.assertEqual(fake.calls, [])

    def test_the_untyped_path_asks_no_batch(self):
        fake = self.upstream({"Q9": entity("mdata" + "a" * 40, types=(MANUSCRIPT,))})

        self.suggest(q="mdata" + "a" * 40, limit="5")

        self.assertEqual(fake.actions(), ["wbsearchentities", "query"])

    def test_concurrent_identical_misses_reach_the_upstream_once(self):
        fake = self.upstream(DRAGONS, slow={"wbsearchentities": 0.3})
        threads = [
            threading.Thread(
                target=self.suggest, kwargs={"q": "drag", "type": "descriptor"}
            )
            for _ in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(fake.searches(), ["drag"])


class SuggestPrefixEntryTests(SuggestTestCase):
    def test_a_complete_entry_is_stored_for_the_biblissima_ttl(self):
        self.upstream(DRAGONS)
        setter = self.start(patch.object(bp.cache, "set", wraps=bp.cache.set))

        self.suggest(q="drag", type="descriptor")

        key = bp._suggest_prefix_key("drag", "fr")
        timeouts = [c.args[2] for c in setter.call_args_list if c.args[0] == key]
        self.assertEqual(timeouts, [bp._BIBLISSIMA_CACHE_TTL])

    def test_a_truncated_entry_is_not_stored(self):
        self.upstream(SAINTS)

        self.suggest(q="sain", type="descriptor")

        self.assertIsNone(cache.get(bp._suggest_prefix_key("sain", "fr")))

    def test_an_error_answer_never_becomes_a_prefix_entry(self):
        self.upstream(DRAGONS, errors={"wbsearchentities": "badvalue"})

        self.suggest(q="drag", type="descriptor")

        self.assertIsNone(cache.get(bp._suggest_prefix_key("drag", "fr")))

    def test_an_entry_serves_both_types(self):
        corpus = {
            "Q1": entity("dragon"),
            "Q5": entity("Dragon de Metz", types=(MANUSCRIPT,)),
        }
        fake = self.upstream(corpus)
        self.suggest(q="drag", type="descriptor")
        before = len(fake.calls)

        _, payload = self.suggest(q="drag", type="manuscript")

        self.assertNotIn("wbsearchentities", fake.actions()[before:])
        self.assertEqual([r["id"] for r in payload["results"]], ["Q5"])


class SuggestPrefixReuseTests(SuggestTestCase):
    def test_a_longer_query_under_a_complete_prefix_asks_no_prefix_call(self):
        fake = self.upstream(DRAGONS)
        self.suggest(q="drag", type="descriptor")
        before = len(fake.calls)

        _, payload = self.suggest(q="dragon", type="descriptor")

        self.assertNotIn("wbsearchentities", fake.actions()[before:])
        self.assertEqual([r["id"] for r in payload["results"]], ["Q1"])

    def test_a_truncated_prefix_is_not_reused(self):
        fake = self.upstream(SAINTS)
        self.suggest(q="sain", type="descriptor")

        _, payload = self.suggest(q="saint jero", type="descriptor")

        self.assertEqual(fake.searches(), ["sain", "saint jero"])
        self.assertIn("Q8844", [r["id"] for r in payload["results"]])

    def test_an_alias_in_another_language_is_found_from_the_prefix_entry(self):
        fake = self.upstream(SAINTS)
        self.suggest(q="hier", type="descriptor")

        _, payload = self.suggest(q="hieron", type="descriptor")

        self.assertEqual(fake.searches(), ["hier"])
        self.assertEqual([r["id"] for r in payload["results"]], ["Q8844"])

    def test_a_hyphenated_label_is_found_from_the_prefix_entry(self):
        corpus = {
            "Q7": entity("Saint-Jacques-de-Compostelle"),
            "Q8": entity("Saint Jacques"),
        }
        fake = self.upstream(corpus)
        self.suggest(q="saint", type="descriptor")

        _, payload = self.suggest(q="saint jac", type="descriptor")

        self.assertEqual(fake.searches(), ["saint"])
        self.assertEqual({r["id"] for r in payload["results"]}, {"Q7", "Q8"})

    def test_an_entity_id_is_never_answered_from_a_prefix(self):
        corpus = {**DRAGONS, "Q8844": SAINTS["Q8844"]}
        fake = self.upstream(corpus)
        self.suggest(q="q88", type="descriptor")

        _, payload = self.suggest(q="q8844", type="descriptor")

        self.assertEqual(fake.searches(), ["q88", "q8844"])
        self.assertIn("Q8844", [r["id"] for r in payload["results"]])

    def test_more_typed_hits_than_the_limit_go_upstream(self):
        corpus = {f"Q{10 + i}": entity(f"dragon {i}") for i in range(12)}
        fake = self.upstream(corpus)
        self.suggest(q="drag", type="descriptor")

        self.suggest(q="drago", type="descriptor")

        self.assertEqual(fake.searches(), ["drag", "drago"])

    def test_derived_answers_equal_fresh_answers(self):
        corpus = {**DRAGONS, **SAINTS}
        for sequence in (
            ["drag", "drago", "dragon"],
            ["jer", "jero", "jerom", "jerome"],
            ["hie", "hier", "hieron"],
            ["sain", "saint", "saint j", "saint jero"],
            ["q8", "q88", "q884", "q8844"],
        ):
            cache.clear()
            self.upstream(corpus)
            typed = [self.suggest(q=q, type="descriptor")[1] for q in sequence]
            for q, derived in zip(sequence, typed):
                cache.clear()
                self.upstream(corpus)
                _, fresh = self.suggest(q=q, type="descriptor")
                self.assertEqual(_by_id(derived), _by_id(fresh), q)
