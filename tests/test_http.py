import socket
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from manuspectrum.utils.http import (
    UnsafeURLError,
    assert_url_is_safe,
    fetch_iiif_manifest,
    get_iiif_session,
    get_user_agent,
)


class UserAgentTests(SimpleTestCase):
    """The outbound User-Agent identifies us to external hosts (issue #29).

    In production it must carry a way back to a human (public site + contact
    inbox) so an operator who sees our traffic can reach us; in DEBUG that
    block is omitted — a localhost URL and a dev mailbox tell them nothing.
    """

    def setUp(self):
        # The builder is lru_cached; override_settings must not read a stale value.
        get_user_agent.cache_clear()
        self.addCleanup(get_user_agent.cache_clear)

    @override_settings(
        DEBUG=True,
        PUBLIC_SERVER_ADDRESS="http://localhost:8000/",
        CONTACT_EMAIL="dev@example.org",
    )
    def test_debug_omits_contact_block(self):
        ua = get_user_agent()
        self.assertNotIn("(", ua)
        self.assertNotIn("localhost", ua)
        self.assertNotIn("dev@example.org", ua)

    @override_settings(
        DEBUG=False,
        PUBLIC_SERVER_ADDRESS="https://manuspectrum.fr/",
        CONTACT_EMAIL="team@manuspectrum.fr",
    )
    def test_prod_appends_site_and_contact_email(self):
        self.assertTrue(
            get_user_agent().endswith(
                "(+https://manuspectrum.fr/about/contact; team@manuspectrum.fr)"
            ),
            get_user_agent(),
        )

    @override_settings(
        DEBUG=False,
        PUBLIC_SERVER_ADDRESS="https://manuspectrum.fr",  # no trailing slash
        CONTACT_EMAIL="team@manuspectrum.fr",
    )
    def test_site_url_joins_cleanly_without_trailing_slash(self):
        self.assertIn("+https://manuspectrum.fr/about/contact;", get_user_agent())

    @override_settings(
        DEBUG=False,
        PUBLIC_SERVER_ADDRESS="https://manuspectrum.fr/",
        CONTACT_EMAIL="",
        DEFAULT_FROM_EMAIL="team@manuspectrum.fr",
    )
    def test_falls_back_to_default_from_email(self):
        self.assertIn("team@manuspectrum.fr", get_user_agent())

    @override_settings(
        DEBUG=False,
        PUBLIC_SERVER_ADDRESS="https://manuspectrum.fr/",
        CONTACT_EMAIL="",
        DEFAULT_FROM_EMAIL="xxxx@xxx.com",
    )
    def test_placeholder_email_is_never_published(self):
        ua = get_user_agent()
        self.assertNotIn("xxxx@xxx.com", ua)
        self.assertTrue(ua.endswith("(+https://manuspectrum.fr/about/contact)"), ua)

    @override_settings(
        DEBUG=False,
        PUBLIC_SERVER_ADDRESS="http://localhost:8000/",  # Arches' shipped default
        CONTACT_EMAIL="team@manuspectrum.fr",
    )
    def test_unconfigured_local_address_is_not_advertised(self):
        # A prod deploy that forgot to set PUBLIC_SERVER_ADDRESS must not tell
        # remote hosts to visit their own localhost.
        ua = get_user_agent()
        self.assertNotIn("localhost", ua)
        self.assertTrue(ua.endswith("(team@manuspectrum.fr)"), ua)

    @override_settings(
        DEBUG=False,
        PUBLIC_SERVER_ADDRESS="",
        CONTACT_EMAIL="team@manuspectrum.fr",
    )
    def test_email_only_when_no_public_address(self):
        self.assertTrue(get_user_agent().endswith("(team@manuspectrum.fr)"))

    @override_settings(
        DEBUG=False,
        PUBLIC_SERVER_ADDRESS="",
        CONTACT_EMAIL="",
        DEFAULT_FROM_EMAIL="",
    )
    def test_nothing_configured_leaves_the_bare_agent(self):
        self.assertNotIn("(", get_user_agent())

    @override_settings(
        DEBUG=False,
        PUBLIC_SERVER_ADDRESS="https://manuspectrum.fr/",
        CONTACT_EMAIL="team@manuspectrum.fr",
    )
    def test_stays_a_single_header_line(self):
        # A newline in a header value is a header-injection vector.
        ua = get_user_agent()
        self.assertNotIn("\n", ua)
        self.assertNotIn("\r", ua)


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


@override_settings(MANIFEST_FETCH_RATE_LIMITS={"bnf.fr": 3.0, "default": 1.0})
class RateBucketTests(SimpleTestCase):
    """Per-host throttle bucketing (finding #10).

    A configured suffix (bnf.fr) shares one bucket + stricter interval; every
    other host gets its OWN bucket so throttling one host never serialises
    requests to unrelated hosts.
    """

    def test_bnf_subdomains_share_one_bucket(self):
        from manuspectrum.utils.http import _rate_key_and_interval

        self.assertEqual(_rate_key_and_interval("gallica.bnf.fr"), ("bnf.fr", 3.0))
        self.assertEqual(_rate_key_and_interval("api.bnf.fr"), ("bnf.fr", 3.0))

    def test_unrelated_hosts_get_distinct_buckets(self):
        from manuspectrum.utils.http import _rate_key_and_interval

        k1, i1 = _rate_key_and_interval("e-codices.unifr.ch")
        k2, i2 = _rate_key_and_interval("digi.vatlib.it")
        self.assertEqual((k1, i1), ("e-codices.unifr.ch", 1.0))
        self.assertEqual((k2, i2), ("digi.vatlib.it", 1.0))
        # The bug: both would have been keyed "default" and serialised together.
        self.assertNotEqual(k1, k2)

    def test_empty_host_uses_default_key(self):
        from manuspectrum.utils.http import _rate_key_and_interval

        self.assertEqual(_rate_key_and_interval(None), ("default", 1.0))
        self.assertEqual(_rate_key_and_interval(""), ("default", 1.0))

    def test_throttle_uses_per_host_locks(self):
        import manuspectrum.utils.http as http_mod

        # First call per host records a timestamp but never sleeps (no prior
        # timestamp -> negative wait), so this does not block the test.
        http_mod.throttle_for_host("https://e-codices.unifr.ch/a/manifest.json")
        http_mod.throttle_for_host("https://digi.vatlib.it/b/manifest.json")

        self.assertIn("e-codices.unifr.ch", http_mod._host_rate_locks)
        self.assertIn("digi.vatlib.it", http_mod._host_rate_locks)
        # Distinct locks -> a wait on one host cannot block the other.
        self.assertIsNot(
            http_mod._host_rate_locks["e-codices.unifr.ch"],
            http_mod._host_rate_locks["digi.vatlib.it"],
        )
