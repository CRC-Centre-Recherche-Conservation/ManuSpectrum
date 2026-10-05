import socket
from unittest.mock import MagicMock, patch

import requests
from django.test import SimpleTestCase, override_settings

from manuspectrum.utils import http
from tests.observability_helpers import delta


@override_settings(SSRF_ALLOW_PRIVATE=False)
class SsrfRejectionTests(SimpleTestCase):
    def rejected(self, url, reason, **patches):
        with delta("manuspectrum_ssrf_rejections_total", reason=reason) as counted:
            with self.assertRaises(http.UnsafeURLError) as raised:
                http.assert_url_is_safe(url)
        self.assertEqual(raised.exception.reason, reason)
        self.assertEqual(counted.value, 1)

    def test_reasons(self):
        self.rejected("ftp://example.org/x", "scheme")
        self.rejected("http://exa mple.org:99999999/x", "malformed")
        self.rejected("http://example.org:22/x", "port")
        with patch("socket.getaddrinfo", side_effect=socket.gaierror()):
            self.rejected("http://nowhere.invalid/x", "dns")
        with patch(
            "socket.getaddrinfo", return_value=[(0, 0, 0, "", ("10.0.0.1", 80))]
        ):
            self.rejected("http://internal.example/x", "private")

    def test_redirect_cap(self):
        session = MagicMock()
        response = MagicMock(is_redirect=True, headers={"Location": "/again"})
        session.get.return_value = response
        with (
            patch.object(
                http,
                "assert_url_is_safe",
                side_effect=lambda u, **k: requests.compat.urlparse(u),
            ),
            override_settings(SSRF_MAX_REDIRECTS=1),
            delta("manuspectrum_ssrf_rejections_total", reason="redirects") as counted,
        ):
            with self.assertRaises(http.UnsafeURLError):
                http.safe_fetch("http://example.org/x", session=session, throttle=False)
        self.assertEqual(counted.value, 1)


class OutboundFetchTests(SimpleTestCase):
    def fetch(self, purpose, **kwargs):
        return http.safe_fetch(
            "http://example.org/x", purpose=purpose, throttle=False, **kwargs
        )

    def test_outcomes_by_purpose(self):
        ok = MagicMock(is_redirect=False, status_code=200, headers={})
        missing = MagicMock(is_redirect=False, status_code=404, headers={})
        session = MagicMock()
        with (
            patch.object(
                http,
                "assert_url_is_safe",
                side_effect=lambda u, **k: requests.compat.urlparse(u),
            ),
            patch.object(http, "_read_capped", return_value=b"{}"),
        ):
            session.get.return_value = ok
            with (
                delta(
                    "manuspectrum_outbound_fetches_total",
                    purpose="manifest",
                    outcome="ok",
                ) as fine,
                delta(
                    "manuspectrum_outbound_fetch_seconds_count", purpose="manifest"
                ) as timed,
            ):
                self.fetch("manifest", session=session)
            session.get.return_value = missing
            with delta(
                "manuspectrum_outbound_fetches_total",
                purpose="thumbnail",
                outcome="http_error",
            ) as http_error:
                self.fetch("thumbnail", session=session)
            session.get.side_effect = requests.exceptions.ReadTimeout()
            with delta(
                "manuspectrum_outbound_fetches_total",
                purpose="other",
                outcome="timeout",
            ) as timeout:
                with self.assertRaises(requests.exceptions.Timeout):
                    self.fetch("weird-purpose", session=session)
        self.assertEqual(
            (fine.value, timed.value, http_error.value, timeout.value), (1, 1, 1, 1)
        )

    @override_settings(SSRF_ALLOW_PRIVATE=False)
    def test_an_unsafe_url_is_counted_as_fetch_and_as_rejection(self):
        with (
            patch(
                "socket.getaddrinfo", return_value=[(0, 0, 0, "", ("127.0.0.1", 80))]
            ),
            delta(
                "manuspectrum_outbound_fetches_total",
                purpose="thumbnail",
                outcome="unsafe",
            ) as unsafe,
            delta("manuspectrum_ssrf_rejections_total", reason="private") as rejected,
        ):
            with self.assertRaises(http.UnsafeURLError):
                self.fetch("thumbnail")
        self.assertEqual((unsafe.value, rejected.value), (1, 1))
