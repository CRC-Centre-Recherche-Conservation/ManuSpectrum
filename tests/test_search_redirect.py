"""The homepage search form target: ``/{lang}/search-term?q=`` redirects to the filtered Arches search page.

Usage:
    python manage.py test tests.test_search_redirect --settings="tests.test_settings"
"""

import json
from urllib.parse import parse_qs, urlsplit

from django.test import TestCase

from manuspectrum.views.search_redirect import TERM_MAX_LENGTH


def term_filter(location):
    query = parse_qs(urlsplit(location).query)
    return query["paging-filter"], json.loads(query["term-filter"][0])


class SearchTermRedirectTests(TestCase):
    def test_a_term_becomes_one_string_term_filter_on_the_search_page(self):
        response = self.client.get("/en/search-term", {"q": "  Vermilion "})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlsplit(response["Location"]).path, "/en/search")
        paging, terms = term_filter(response["Location"])
        self.assertEqual(paging, ["1"])
        self.assertEqual(
            terms,
            [
                {
                    "inverted": False,
                    "type": "string",
                    "context": "",
                    "context_label": "",
                    "id": "Vermilion",
                    "text": "Vermilion",
                    "value": "Vermilion",
                }
            ],
        )

    def test_the_term_survives_quotes_ampersands_and_accents(self):
        term = 'plomb & "étain"'
        response = self.client.get("/fr/search-term", {"q": term})
        self.assertEqual(urlsplit(response["Location"]).path, "/fr/search")
        self.assertEqual(term_filter(response["Location"])[1][0]["value"], term)

    def test_a_blank_or_missing_term_opens_the_plain_search_page(self):
        for params in ({}, {"q": ""}, {"q": "   "}):
            response = self.client.get("/en/search-term", params)
            self.assertEqual(response.status_code, 302, params)
            self.assertEqual(response["Location"], "/en/search", params)

    def test_the_term_is_cut_to_the_bound(self):
        response = self.client.get("/en/search-term", {"q": "x" * 5000})
        value = term_filter(response["Location"])[1][0]["value"]
        self.assertEqual(value, "x" * TERM_MAX_LENGTH)

    def test_the_homepage_form_submits_to_the_route(self):
        html = self.client.get("/en/").content.decode()
        self.assertIn(
            'id="ms-search-form" action="/en/search-term"', html.replace("\n", " ")
        )

    def test_the_redirect_is_not_cached(self):
        response = self.client.get("/en/search-term", {"q": "a"})
        self.assertIn("no-store", response["Cache-Control"])
