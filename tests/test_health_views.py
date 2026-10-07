from django.test import TestCase, override_settings
from django.urls import reverse


class HealthzViewTests(TestCase):
    def test_healthz_answers_plain_ok(self):
        response = self.client.get(reverse("healthz"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
        self.assertEqual(response["Content-Type"], "text/plain")

    def test_healthz_is_never_cached(self):
        response = self.client.get("/healthz")
        self.assertIn("no-store", response["Cache-Control"])

    def test_healthz_has_no_language_twin(self):
        self.assertEqual(self.client.get("/en/healthz").status_code, 404)
        self.assertEqual(self.client.get("/fr/healthz").status_code, 404)


@override_settings(ALLOWED_HOSTS=["manuspectrum.test", "web"])
class HealthzHostTests(TestCase):
    """The host list of settings_docker: public names and the Compose service name only."""

    def test_service_name_and_public_name_are_served(self):
        for host in ("web", "manuspectrum.test"):
            with self.subTest(host=host):
                self.assertEqual(
                    self.client.get("/healthz", HTTP_HOST=host).status_code, 200
                )

    def test_localhost_is_refused(self):
        for host in ("localhost", "127.0.0.1"):
            with self.subTest(host=host):
                self.assertEqual(
                    self.client.get("/healthz", HTTP_HOST=host).status_code, 400
                )
