import socket
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from manuspectrum.utils.http import (
    UnsafeURLError,
    assert_url_is_safe,
    fetch_iiif_manifest,
    get_iiif_session,
)


def _gai(ip):
    """Fake ``socket.getaddrinfo`` result resolving a host to a single ``ip``."""
    if ":" in ip:
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 0, 0, 0))]
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


@override_settings(DEBUG=False)
class AssertUrlIsSafeProdTests(SimpleTestCase):
    """In production the SSRF guard is enforced."""

    def test_rejects_non_http_scheme(self):
        for url in ("ftp://example.com/x", "file:///etc/passwd", "gopher://x/"):
            with self.assertRaises(UnsafeURLError):
                assert_url_is_safe(url)

    def test_rejects_missing_host(self):
        with self.assertRaises(UnsafeURLError):
            assert_url_is_safe("http:///no-host")

    @patch("manuspectrum.utils.http.socket.getaddrinfo")
    def test_allows_public_address(self, mock_gai):
        mock_gai.return_value = _gai("93.184.216.34")
        # Should not raise.
        assert_url_is_safe("https://example.com/iiif/manifest.json")

    @patch("manuspectrum.utils.http.socket.getaddrinfo")
    def test_rejects_loopback(self, mock_gai):
        mock_gai.return_value = _gai("127.0.0.1")
        with self.assertRaises(UnsafeURLError):
            assert_url_is_safe("http://127.0.0.1/x")

    @patch("manuspectrum.utils.http.socket.getaddrinfo")
    def test_rejects_cloud_metadata_link_local(self, mock_gai):
        mock_gai.return_value = _gai("169.254.169.254")
        with self.assertRaises(UnsafeURLError):
            assert_url_is_safe("http://169.254.169.254/latest/meta-data/")

    @patch("manuspectrum.utils.http.socket.getaddrinfo")
    def test_rejects_private_rfc1918(self, mock_gai):
        for ip in ("10.0.0.5", "192.168.1.1", "172.16.0.9"):
            mock_gai.return_value = _gai(ip)
            with self.assertRaises(UnsafeURLError):
                assert_url_is_safe(f"http://{ip}/x")

    @patch("manuspectrum.utils.http.socket.getaddrinfo")
    def test_rejects_dns_rebinding_to_private(self, mock_gai):
        # A public-looking host that resolves to an internal address.
        mock_gai.return_value = _gai("10.0.0.5")
        with self.assertRaises(UnsafeURLError):
            assert_url_is_safe("https://evil.example.com/manifest.json")

    @patch("manuspectrum.utils.http.socket.getaddrinfo")
    def test_rejects_ipv4_mapped_ipv6_loopback(self, mock_gai):
        mock_gai.return_value = _gai("::ffff:127.0.0.1")
        with self.assertRaises(UnsafeURLError):
            assert_url_is_safe("http://[::ffff:127.0.0.1]/x")

    @patch("manuspectrum.utils.http.socket.getaddrinfo")
    def test_rejects_ipv6_loopback(self, mock_gai):
        mock_gai.return_value = _gai("::1")
        with self.assertRaises(UnsafeURLError):
            assert_url_is_safe("http://[::1]/x")

    @patch("manuspectrum.utils.http.socket.getaddrinfo")
    def test_dns_failure_raises(self, mock_gai):
        mock_gai.side_effect = socket.gaierror("name resolution failed")
        with self.assertRaises(UnsafeURLError):
            assert_url_is_safe("https://does-not-resolve.example/x")


@override_settings(DEBUG=True)
class AssertUrlIsSafeDebugTests(SimpleTestCase):
    """In DEBUG, private/loopback targets are allowed (local IIIF dev)."""

    @patch("manuspectrum.utils.http.socket.getaddrinfo")
    def test_debug_allows_private_without_resolving(self, mock_gai):
        assert_url_is_safe("http://127.0.0.1:8000/manifest/abc")  # no raise
        assert_url_is_safe("http://localhost:8000/manifest/abc")  # no raise
        mock_gai.assert_not_called()

    def test_debug_still_rejects_bad_scheme(self):
        with self.assertRaises(UnsafeURLError):
            assert_url_is_safe("file:///etc/passwd")


class AssertUrlIsSafeOverrideTests(SimpleTestCase):
    @override_settings(DEBUG=False)
    @patch("manuspectrum.utils.http.socket.getaddrinfo")
    def test_explicit_allow_private_overrides_prod(self, mock_gai):
        assert_url_is_safe("http://10.0.0.5/x", allow_private=True)
        mock_gai.assert_not_called()


class FetchIiifManifestTests(SimpleTestCase):
    """The resilient, throttled IIIF manifest fetch helper."""

    @override_settings(MANIFEST_FETCH_RATE_LIMITS={})
    @patch("manuspectrum.utils.http.get_iiif_session")
    def test_forces_no_redirects(self, mock_session_factory):
        # allow_redirects=False is a security invariant (redirect-SSRF guard).
        session = MagicMock()
        mock_session_factory.return_value = session
        fetch_iiif_manifest("https://example.org/iiif/manifest")
        session.get.assert_called_once()
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])

    def test_session_carries_user_agent_and_accept(self):
        session = get_iiif_session()
        self.assertIn("User-Agent", session.headers)
        self.assertIn("Accept", session.headers)
