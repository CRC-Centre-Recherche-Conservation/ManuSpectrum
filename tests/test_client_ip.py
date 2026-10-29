from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings
from django_ratelimit.core import _get_ip, is_ratelimited

from manuspectrum.utils.client_ip import client_ip

KEY = "manuspectrum.utils.client_ip.client_ip"


def request(real_ip=None, remote="10.0.0.2"):
    extra = {"REMOTE_ADDR": remote}
    if real_ip is not None:
        extra["HTTP_X_REAL_IP"] = real_ip
    return RequestFactory().get("/", **extra)


class ClientIpTests(SimpleTestCase):
    def test_valid_real_ip_is_returned(self):
        for value in ("203.0.113.7", "2001:db8::1", " 203.0.113.7 "):
            with self.subTest(value=value):
                self.assertEqual(client_ip(request(value)), value.strip())

    def test_invalid_or_missing_real_ip_falls_back_to_remote_addr(self):
        for value in (None, "", "1.2.3.4, 5.6.7.8", "unknown", "1" * 300):
            with self.subTest(value=value):
                self.assertEqual(client_ip(request(value)), "10.0.0.2")

    @override_settings(RATELIMIT_IP_META_KEY=KEY)
    def test_ratelimit_reads_real_ip(self):
        self.assertEqual(_get_ip(request("203.0.113.7")), "203.0.113.7")

    @override_settings(RATELIMIT_IP_META_KEY=KEY)
    def test_visitors_behind_one_proxy_get_separate_buckets(self):
        cache.clear()
        self.addCleanup(cache.clear)
        limited = [
            is_ratelimited(
                request(ip),
                group="client-ip-test",
                key="ip",
                rate="1/m",
                increment=True,
            )
            for ip in ("203.0.113.7", "203.0.113.8")
        ]
        self.assertEqual(limited, [False, False])
