import json

from django.test import TestCase
from django.urls import reverse

from manuspectrum.observability import csp, metrics
from tests.observability_helpers import delta

URL = "/api/csp-report"
METRIC = "manuspectrum_csp_violations_total"


def legacy(**body):
    return json.dumps({"csp-report": body})


def reporting(*bodies):
    return json.dumps([{"type": "csp-violation", "body": b} for b in bodies])


class CspReportTests(TestCase):
    def post(self, data, content_type="application/csp-report"):
        return self.client.post(URL, data=data, content_type=content_type)

    def test_route_name_and_path(self):
        self.assertEqual(reverse("csp-report"), URL)

    def test_legacy_report_is_a_bodyless_204_and_counts(self):
        with delta(METRIC, directive="script-src-elem") as d:
            response = self.post(
                legacy(**{"effective-directive": "script-src-elem"}),
            )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertEqual(d.value, 1)

    def test_reporting_api_batch_counts_every_violation(self):
        with (
            delta(METRIC, directive="img-src") as images,
            delta(METRIC, directive="font-src") as fonts,
        ):
            response = self.post(
                reporting(
                    {"effectiveDirective": "img-src"},
                    {"effectiveDirective": "img-src"},
                    {"effectiveDirective": "font-src"},
                ),
                "application/reports+json",
            )
        self.assertEqual(response.status_code, 204)
        self.assertEqual((images.value, fonts.value), (2, 1))

    def test_other_report_types_are_ignored(self):
        body = json.dumps([{"type": "deprecation", "body": {"id": "x"}}])
        with delta(METRIC, directive="other") as d:
            response = self.post(body, "application/reports+json")
        self.assertEqual((response.status_code, d.value), (204, 0))

    def test_content_type_does_not_matter(self):
        for content_type in (
            "text/plain",
            "application/json",
            "application/octet-stream",
        ):
            with self.subTest(content_type), delta(METRIC, directive="style-src") as d:
                response = self.post(
                    legacy(**{"effective-directive": "style-src"}), content_type
                )
                self.assertEqual(response.status_code, 204)
            self.assertEqual(d.value, 1)

    def test_directive_falls_back_to_the_first_token_of_the_violated_one(self):
        with delta(METRIC, directive="connect-src") as d:
            self.post(legacy(**{"violated-directive": "connect-src 'self' https:"}))
        self.assertEqual(d.value, 1)

    def test_directive_is_case_insensitive(self):
        with delta(METRIC, directive="frame-src") as d:
            self.post(legacy(**{"effective-directive": "Frame-Src"}))
        self.assertEqual(d.value, 1)

    def test_unknown_directive_is_other(self):
        with (
            delta(METRIC, directive="other") as d,
            delta(METRIC, directive="evil-src") as raw,
        ):
            self.post(legacy(**{"effective-directive": "evil-src"}))
            self.post(legacy(**{"blocked-uri": "inline"}))
        self.assertEqual((d.value, raw.value), (2, 0))

    def test_every_declared_directive_is_a_distinct_label(self):
        for directive in metrics.CSP_DIRECTIVES:
            with self.subTest(directive), delta(METRIC, directive=directive) as d:
                self.post(legacy(**{"effective-directive": directive}))
            self.assertEqual(d.value, 1)

    def test_get_is_405(self):
        self.assertEqual(self.client.get(URL).status_code, 405)

    def test_body_over_16_kib_is_413(self):
        padding = "a" * (csp.MAX_BODY_BYTES + 1)
        with delta(METRIC, directive="other") as d:
            response = self.post(legacy(**{"effective-directive": padding}))
        self.assertEqual((response.status_code, d.value), (413, 0))

    def test_an_empty_content_length_is_400(self):
        response = self.client.generic(
            "POST",
            URL,
            data=b"{}",
            content_type="application/csp-report",
            CONTENT_LENGTH="",
        )
        self.assertEqual(response.status_code, 400)

    def test_invalid_json_is_400(self):
        for data in ("{not json", "", b"\xff\xfe"):
            with self.subTest(data):
                self.assertEqual(self.post(data).status_code, 400)

    def test_deeply_nested_json_is_400(self):
        self.assertEqual(self.post("[" * 3000 + "]" * 3000).status_code, 400)

    def test_a_single_reporting_api_report_as_a_dict_counts(self):
        report = {"type": "csp-violation", "body": {"effectiveDirective": "img-src"}}
        with delta(METRIC, directive="img-src") as d:
            response = self.post(json.dumps(report), "application/reports+json")
        self.assertEqual((response.status_code, d.value), (204, 1))

    def test_a_non_string_directive_is_other(self):
        with delta(METRIC, directive="other") as d:
            response = self.post(legacy(**{"effective-directive": ["img-src"]}))
        self.assertEqual((response.status_code, d.value), (204, 1))

    def test_json_of_another_shape_is_accepted_and_ignored(self):
        for data in ('"text"', "12", "null", "[1, 2]", "{}"):
            with self.subTest(data):
                self.assertEqual(self.post(data).status_code, 204)

    def test_at_most_twenty_violations_are_read(self):
        bodies = [{"effectiveDirective": "media-src"}] * (csp.MAX_VIOLATIONS + 10)
        with delta(METRIC, directive="media-src") as d:
            self.post(reporting(*bodies), "application/reports+json")
        self.assertEqual(d.value, csp.MAX_VIOLATIONS)

    def test_csrf_and_login_are_not_required(self):
        from django.test import Client

        response = Client(enforce_csrf_checks=True).post(
            URL, data="{}", content_type="application/csp-report"
        )
        self.assertEqual(response.status_code, 204)


class CspLogLineTests(TestCase):
    def report(self, **body):
        with self.assertLogs("manuspectrum.csp", level="INFO") as logs:
            response = self.client.post(
                URL,
                data=json.dumps({"csp-report": body}),
                content_type="application/csp-report",
                REMOTE_ADDR="203.0.113.77",
                HTTP_USER_AGENT="SecretBrowser/1.0",
            )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(len(logs.records), 1)
        return logs.records[0]

    def test_the_line_holds_only_the_four_fields(self):
        record = self.report(
            **{
                "effective-directive": "img-src",
                "blocked-uri": "https://cdn.example.org:8443/a/b.png?token=SECRET#x",
                "document-uri": "https://manuspectrum.test/en/search?q=private#top",
                "disposition": "report",
                "script-sample": "sampled code",
                "source-file": "https://manuspectrum.test/static/app.js",
            }
        )
        self.assertEqual(record.directive, "img-src")
        self.assertEqual(record.blocked, "https://cdn.example.org")
        self.assertEqual(record.document, "search_home")
        self.assertEqual(record.disposition, "report")
        text = json.dumps(record.__dict__, default=str)
        for leaked in (
            "SECRET",
            "b.png",
            "private",
            "203.0.113.77",
            "SecretBrowser",
            "sampled",
            "8443",
            "manuspectrum.test",
        ):
            self.assertNotIn(leaked, text)

    def test_blocked_keywords_stay_as_they_are(self):
        for value in ("inline", "eval", "wasm-eval", "data", "blob", "self"):
            with self.subTest(value):
                self.assertEqual(csp.blocked_target(value), value)

    def test_data_and_blob_urls_are_reduced_to_their_scheme(self):
        self.assertEqual(csp.blocked_target("data:image/png;base64,AAAA"), "data")
        self.assertEqual(csp.blocked_target("blob:https://x.test/uuid"), "blob")

    def test_credentials_port_path_and_query_are_dropped(self):
        self.assertEqual(
            csp.blocked_target("https://user:pw@Tiles.Example.ORG:99/p?q=1"),
            "https://tiles.example.org",
        )

    def test_unparseable_blocked_values_are_other(self):
        for value in ("", "not a url", "http://[::1", "//nohost"):
            with self.subTest(value):
                self.assertEqual(csp.blocked_target(value), "other")

    def test_control_characters_are_stripped(self):
        record = self.report(
            **{
                "effective-directive": "script-src",
                "document-uri": "https://x.test/a\nb\r\x1b[31mc\u2028d",
                "blocked-uri": "https://evil\n.test/",
                "disposition": "enforce\n",
            }
        )
        for value in (record.document, record.blocked, record.disposition):
            self.assertFalse(any(c in value for c in "\n\r\x1b\u2028"), value)
        self.assertEqual(record.disposition, "enforce")

    def test_unknown_disposition_is_other_and_long_values_are_cut(self):
        record = self.report(
            **{
                "effective-directive": "script-src",
                "disposition": "whatever",
                "document-uri": "https://x.test/" + "a" * 5000,
            }
        )
        self.assertEqual(record.disposition, "other")
        self.assertLessEqual(len(record.document), csp.MAX_FIELD_LENGTH)

    def test_a_page_path_never_reaches_the_record(self):
        for path, name in (
            ("/fr/account/activate/MQ/abc-123SECRET", "account-activate"),
            ("/en/reset/MQ/tokSECRET-1/", "password_reset_confirm"),
            ("/fr/account/two-factor/reset/tokSECRET", "account-two-factor-reset"),
        ):
            with self.subTest(path):
                record = self.report(
                    **{
                        "effective-directive": "img-src",
                        "document-uri": f"https://manuspectrum.test{path}?k=1",
                    }
                )
                text = json.dumps(record.__dict__, default=str)
                self.assertNotIn("SECRET", text)
                self.assertNotIn("abc-123", text)
                self.assertNotIn(path, text)
                self.assertEqual(record.document, name)

    def test_the_page_is_logged_as_its_route_name(self):
        uuid = "6a2f8d37-1f4c-4f3c-9b3e-2a4b2d8f9e11"
        for path, name in (
            (f"/en/resource/{uuid}", "resource_editor"),
            (f"/fr/account/activate/MQ/abc", "account-activate"),
            ("/en/search", "search_home"),
        ):
            with self.subTest(path):
                record = self.report(
                    **{
                        "effective-directive": "img-src",
                        "document-uri": f"https://manuspectrum.test{path}",
                    }
                )
                self.assertEqual(record.document, name)
                self.assertNotIn(uuid, json.dumps(record.__dict__, default=str))

    def test_an_unresolvable_or_odd_page_is_other(self):
        for value in (
            "https://manuspectrum.test/nowhere/1",
            "https://manuspectrum.test/xx/search",
            "relative/path",
            "http://[::1",
            "https://manuspectrum.test/" + "%" * 50,
            "",
        ):
            with self.subTest(value):
                record = self.report(
                    **{"effective-directive": "img-src", "document-uri": value}
                )
                self.assertEqual(record.document, "other")
