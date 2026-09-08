import ipaddress
import socket
from unittest.mock import MagicMock, patch

import requests

from django.test import SimpleTestCase, override_settings

from manuspectrum.utils.http import (
    ResponseTooLargeError,
    UnsafeURLError,
    assert_url_is_safe,
    fetch_iiif_manifest,
    get_iiif_session,
    get_user_agent,
    safe_fetch,
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


def _resolve_as_written(host, *args, **kwargs):
    """An IP literal resolves to itself; any name resolves to a public address.

    Lets a test say which host was actually checked, instead of only whether
    the check passed.
    """
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return _gai("93.184.216.34")
    return _gai(host)


@override_settings(SSRF_ALLOW_PRIVATE=False)
class AssertUrlIsSafeTests(SimpleTestCase):
    """The guard as every environment runs it unless told otherwise."""

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

    @patch("manuspectrum.utils.http.socket.getaddrinfo")
    def test_rejects_a_non_web_port(self, mock_gai):
        # An http URL on 6379 is a probe of this host's Redis, not a fetch.
        mock_gai.return_value = _gai("93.184.216.34")
        for url in ("http://example.com:6379/x", "https://example.com:9200/x"):
            with self.assertRaises(UnsafeURLError):
                assert_url_is_safe(url)
        mock_gai.assert_not_called()

    @patch("manuspectrum.utils.http.socket.getaddrinfo")
    def test_allows_an_explicit_default_port(self, mock_gai):
        mock_gai.return_value = _gai("93.184.216.34")
        assert_url_is_safe("https://example.com:443/x")
        assert_url_is_safe("http://example.com:80/x")

    def test_rejects_a_malformed_port(self):
        with self.assertRaises(UnsafeURLError):
            assert_url_is_safe("http://example.com:notaport/x")

    @patch(
        "manuspectrum.utils.http.socket.getaddrinfo", side_effect=_resolve_as_written
    )
    def test_a_backslash_authority_is_read_the_way_requests_reads_it(self, mock_gai):
        # urlparse stops the authority at the last "@" and sees example.com;
        # requests stops it at the backslash and connects to the metadata
        # service. Checking one and connecting to the other is the bypass.
        with self.assertRaises(UnsafeURLError):
            assert_url_is_safe("http://169.254.169.254\\@example.com/latest/")

    @patch(
        "manuspectrum.utils.http.socket.getaddrinfo", side_effect=_resolve_as_written
    )
    def test_the_checked_host_is_the_one_that_will_be_connected_to(self, mock_gai):
        # Same string shape the other way round: urlparse reads the internal
        # address, requests connects to example.com. The guard follows requests.
        parsed = assert_url_is_safe("http://example.com\\@169.254.169.254/x")

        self.assertEqual(parsed.hostname, "example.com")

    @override_settings(DEBUG=True)
    @patch("manuspectrum.utils.http.socket.getaddrinfo")
    def test_debug_alone_does_not_open_the_guard(self, mock_gai):
        # The guard used to key off DEBUG; turning on the debug toolbar must
        # not also make loopback fetchable.
        mock_gai.return_value = _gai("127.0.0.1")
        with self.assertRaises(UnsafeURLError):
            assert_url_is_safe("http://127.0.0.1:8000/manifest/abc")


@override_settings(SSRF_ALLOW_PRIVATE=True)
class AssertUrlIsSafeAllowPrivateTests(SimpleTestCase):
    """SSRF_ALLOW_PRIVATE opens the guard for a local IIIF server."""

    @patch("manuspectrum.utils.http.socket.getaddrinfo")
    def test_private_targets_are_allowed_without_resolving(self, mock_gai):
        assert_url_is_safe("http://127.0.0.1:8000/manifest/abc")  # no raise
        assert_url_is_safe("http://localhost:8000/manifest/abc")  # no raise
        mock_gai.assert_not_called()

    def test_a_bad_scheme_is_still_rejected(self):
        with self.assertRaises(UnsafeURLError):
            assert_url_is_safe("file:///etc/passwd")


class AssertUrlIsSafeOverrideTests(SimpleTestCase):
    @override_settings(SSRF_ALLOW_PRIVATE=False)
    @patch("manuspectrum.utils.http.socket.getaddrinfo")
    def test_explicit_allow_private_overrides_the_setting(self, mock_gai):
        assert_url_is_safe("http://10.0.0.5/x", allow_private=True)
        mock_gai.assert_not_called()


def fake_response(
    *, status=200, headers=None, chunks=(b"{}",), url="https://ok.example/x"
):
    """A streamed ``requests`` response, as ``safe_fetch`` consumes one."""
    headers = headers or {}
    response = MagicMock()
    response.status_code = status
    response.headers = headers
    response.url = url
    response.is_redirect = 300 <= status < 400 and "Location" in headers
    response.iter_content.return_value = iter(chunks)
    return response


def fake_session(*responses):
    session = MagicMock()
    session.get.side_effect = list(responses)
    return session


@override_settings(
    MANIFEST_FETCH_RATE_LIMITS={}, SSRF_ALLOW_PRIVATE=False, SSRF_MAX_REDIRECTS=2
)
@patch("manuspectrum.utils.http.socket.getaddrinfo", return_value=_gai("93.184.216.34"))
class SafeFetchTests(SimpleTestCase):
    """The single outbound fetch path: guard, redirects, capped read."""

    def test_returns_the_body_and_never_lets_requests_redirect(self, mock_gai):
        session = fake_session(fake_response(chunks=(b'{"a"', b":1}")))

        response = safe_fetch("https://ok.example/manifest", session=session)

        self.assertEqual(response.json(), {"a": 1})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])
        self.assertTrue(session.get.call_args.kwargs["stream"])

    def test_the_url_sent_is_the_canonical_one_the_guard_checked(self, mock_gai):
        session = fake_session(fake_response())

        safe_fetch("https://ok.example/a manifest.json", session=session)

        self.assertEqual(
            session.get.call_args.args[0], "https://ok.example/a%20manifest.json"
        )

    def test_a_redirect_is_followed_only_after_the_guard_clears_it(self, mock_gai):
        session = fake_session(
            fake_response(
                status=302, headers={"Location": "https://elsewhere.example/final"}
            ),
            fake_response(chunks=(b'{"final":true}',)),
        )

        response = safe_fetch("https://ok.example/manifest", session=session)

        self.assertEqual(response.json(), {"final": True})
        self.assertEqual(
            [call.args[0] for call in session.get.call_args_list],
            ["https://ok.example/manifest", "https://elsewhere.example/final"],
        )

    def test_a_relative_redirect_is_resolved_against_the_current_url(self, mock_gai):
        session = fake_session(
            fake_response(status=301, headers={"Location": "/v3/manifest"}),
            fake_response(),
        )

        safe_fetch("https://ok.example/v2/manifest", session=session)

        self.assertEqual(
            session.get.call_args.args[0], "https://ok.example/v3/manifest"
        )

    def test_a_redirect_into_a_private_address_is_refused(self, mock_gai):
        # The classic bypass: a public URL answering 302 to the metadata service.
        mock_gai.side_effect = [_gai("93.184.216.34"), _gai("169.254.169.254")]
        session = fake_session(
            fake_response(
                status=302,
                headers={"Location": "http://metadata.example/latest/meta-data/"},
            ),
            fake_response(chunks=(b"SECRET",)),
        )

        with self.assertRaises(UnsafeURLError):
            safe_fetch("https://ok.example/manifest", session=session)
        self.assertEqual(session.get.call_count, 1)

    def test_a_redirect_loop_is_cut_at_the_configured_hop_count(self, mock_gai):
        session = fake_session(
            *[
                fake_response(
                    status=302, headers={"Location": "https://ok.example/next"}
                )
                for _ in range(4)
            ]
        )

        with self.assertRaises(UnsafeURLError):
            safe_fetch("https://ok.example/manifest", session=session)
        self.assertEqual(session.get.call_count, 3)  # 1 + SSRF_MAX_REDIRECTS

    def test_the_guard_runs_before_the_first_request(self, mock_gai):
        mock_gai.return_value = _gai("127.0.0.1")
        session = fake_session(fake_response())

        with self.assertRaises(UnsafeURLError):
            safe_fetch("https://rebound.example/manifest", session=session)
        session.get.assert_not_called()

    def test_a_body_past_the_cap_is_refused_mid_stream(self, mock_gai):
        session = fake_session(fake_response(chunks=(b"x" * 8, b"x" * 8)))

        with self.assertRaises(ResponseTooLargeError):
            safe_fetch("https://ok.example/big", session=session, max_bytes=10)

    def test_a_declared_length_past_the_cap_is_refused_before_reading(self, mock_gai):
        response = fake_response(headers={"Content-Length": "999999"})
        session = fake_session(response)

        with self.assertRaises(ResponseTooLargeError):
            safe_fetch("https://ok.example/big", session=session, max_bytes=10)
        response.iter_content.assert_not_called()

    def test_stacked_content_encodings_are_refused(self, mock_gai):
        # The shape of the urllib3 1.x decompression CVEs Arches' pin leaves open.
        session = fake_session(
            fake_response(headers={"Content-Encoding": "gzip, gzip"})
        )

        with self.assertRaises(ResponseTooLargeError):
            safe_fetch("https://ok.example/bomb", session=session)

    def test_a_single_content_encoding_is_normal(self, mock_gai):
        session = fake_session(
            fake_response(headers={"Content-Encoding": "gzip"}, chunks=(b"{}",))
        )

        self.assertEqual(safe_fetch("https://ok.example/x", session=session).json(), {})

    def test_the_response_carries_the_status_for_raise_for_status(self, mock_gai):
        session = fake_session(fake_response(status=404, chunks=(b"gone",)))

        response = safe_fetch("https://ok.example/gone", session=session)

        self.assertFalse(response.ok)
        with self.assertRaises(requests.HTTPError):
            response.raise_for_status()

    @override_settings(SSRF_TIMEOUT=7)
    def test_the_timeout_budget_comes_from_the_setting(self, mock_gai):
        session = fake_session(fake_response())

        safe_fetch("https://ok.example/x", session=session)

        self.assertEqual(session.get.call_args.kwargs["timeout"], (7, 7))


@override_settings(MANIFEST_FETCH_RATE_LIMITS={}, SSRF_ALLOW_PRIVATE=False)
@patch("manuspectrum.utils.http.socket.getaddrinfo", return_value=_gai("93.184.216.34"))
class FetchIiifManifestTests(SimpleTestCase):
    """The resilient, throttled IIIF manifest fetch helper."""

    def test_forces_no_redirects_on_the_request_itself(self, mock_gai):
        # allow_redirects=False is a security invariant (redirect-SSRF guard).
        session = fake_session(fake_response())

        fetch_iiif_manifest("https://example.org/iiif/manifest", session=session)

        session.get.assert_called_once()
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])

    @override_settings(SSRF_TIMEOUT=9)
    def test_keeps_a_longer_read_budget_than_the_connect_budget(self, mock_gai):
        session = fake_session(fake_response())

        fetch_iiif_manifest("https://example.org/iiif/manifest", session=session)

        connect, read = session.get.call_args.kwargs["timeout"]
        self.assertEqual(connect, 9)
        self.assertGreater(read, connect)

    def test_session_carries_user_agent_and_accept(self, mock_gai):
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
